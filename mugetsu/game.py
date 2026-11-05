"""Guess the song: the bot plays short clips and people race to type the title or artist in chat."""

from __future__ import annotations

import asyncio
import logging
import random
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

import discord

from mugetsu.media import youtube
from mugetsu.media.lyrics import split_artist
from mugetsu.media.spotify import SpotifyResolver
from mugetsu.player.models import PlayerError, Song
from mugetsu.util import short_error

if TYPE_CHECKING:
    from mugetsu.player.player import GuildPlayer

log = logging.getLogger("mugetsu.game")

TITLE_POINTS = 2
ARTIST_POINTS = 1
ROUND_GAP = 5  # seconds between the reveal and the next clip
ACCENT = discord.Color(0x8B5CF6)

_BRACKETS = re.compile(r"[\(\[].*?[\)\]]")
_DASH_SUFFIX = re.compile(r"\s+-\s+.*$")  # "Song - Remastered 2011", "Song - Radio Edit"
_FEAT = re.compile(r"\b(feat|ft|featuring|with)\b.*$")
_ARTIST_SPLIT = re.compile(r"\s*(?:,|&|\bx\b|\band\b|\bfeat\.?|\bft\.?|\bwith\b)\s*", re.IGNORECASE)
_DECADE = re.compile(r"\b(?:(19|20)?(\d)0)'?s\b")
_YEAR_RANGE = re.compile(r"\b(19\d\d|20\d\d)\s*-\s*(19\d\d|20\d\d)\b")
_YEAR = re.compile(r"\b(19\d\d|20\d\d)\b")
_VIDEO_NOISE = re.compile(
    r"\b(m/?v|official\s+(music\s+)?video|lyrics?(\s+video)?|visuali[sz]er|official\s+audio|performance\s+video)\b",
    re.IGNORECASE,
)


# --- Answer matching ---

def normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = (folded if folded.strip() else text).casefold()  # keep non-Latin titles as they are
    text = _BRACKETS.sub(" ", text)
    text = _DASH_SUFFIX.sub("", text)
    text = _FEAT.sub("", text)
    text = text.replace("&", " and ")
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"^the\s+", "", text.strip())
    return " ".join(text.split())


def matches(guess: str, answer: str) -> bool:
    """Forgiving comparison: ignores case, accents, punctuation, "(Remastered)" and small typos."""
    g, a = normalize(guess), normalize(answer)
    if not g or not a:
        return False
    if g == a:
        return True
    if len(a) >= 4:
        if f" {a} " in f" {g} ":  # e.g. "loser tame impala" names both
            return True
        if SequenceMatcher(None, g, a).ratio() >= 0.82:
            return True
    return len(g) >= 6 and len(g) >= 0.7 * len(a) and a.startswith(g)


def artists_of(artist: str) -> list[str]:
    return [a for a in (p.strip() for p in _ARTIST_SPLIT.split(artist or "")) if a]


# --- Where the songs come from ---

def spotify_query(source: str) -> str:
    """Turn "80s rock", "pop 2018" or "1990-1999" into a Spotify search query."""
    text = source.strip()
    years = ""
    if m := _YEAR_RANGE.search(text):
        years, text = f"year:{m[1]}-{m[2]}", text.replace(m[0], " ")
    elif m := _DECADE.search(text):
        century = m[1] or ("20" if m[2] in "012" else "19")
        start = int(f"{century}{m[2]}0")
        years, text = f"year:{start}-{start + 9}", text.replace(m[0], " ")
    elif m := _YEAR.search(text):
        years, text = f"year:{m[1]}", text.replace(m[0], " ")
    genre = " ".join(text.split())
    parts = [f'genre:"{genre}"' if genre else "", years]
    return " ".join(p for p in parts if p) or "year:2010-2026"


def _song(title: str, artist: str, duration: int, thumbnail: str, search: bool, query: str = "") -> Song:
    full = f"{artist} - {title}" if artist else title
    return Song(title=full, query=query or full, duration=duration, thumbnail=thumbnail, artist=artist,
                track_name=title, search_music=search, requester="Guess the song", requester_id=0)


async def build_pool(spotify: SpotifyResolver, source: str, size: int) -> list[Song]:
    """Songs for a game, shuffled. `source` is a playlist link, a genre/decade, or empty."""
    source = (source or "").strip().strip("<>")
    if SpotifyResolver.is_spotify_url(source):
        if not spotify.enabled:
            raise PlayerError("Spotify isn't set up on this bot.")
        _, tracks = await asyncio.to_thread(spotify.resolve, source)
        pool = [_song(t["name"], t["artist"], t["duration"], t["thumbnail"], True) for t in tracks]
    elif re.match(r"https?://", source):
        try:
            entries = await youtube.extract_playlist(source)
        except Exception as e:
            raise PlayerError(f"Couldn't load that playlist: {short_error(e)}") from e
        pool = []
        for e in entries:
            artist, title = split_artist(e["title"])
            title = _VIDEO_NOISE.sub("", title).strip(" '\"‘’“”|-")  # "'DESERVE' M/V" -> DESERVE
            pool.append(_song(title, artist or e.get("artist", ""), e["duration"], e["thumbnail"], False, e["url"]))
    else:
        if not spotify.enabled:
            raise PlayerError("Genre and decade games need Spotify set up. A YouTube playlist link works without it.")
        query = spotify_query(source)
        offsets = random.sample(range(0, 250, 50), 3)
        batches = await asyncio.gather(
            *(asyncio.to_thread(spotify.search_tracks, query, 50, o) for o in offsets), return_exceptions=True
        )
        tracks = [t for b in batches if isinstance(b, list) for t in b]
        popular = [t for t in tracks if t.get("popularity", 0) >= 40] or tracks  # songs people might know
        pool, seen = [], set()
        for t in popular:
            key = (t["artist"].lower(), t["name"].lower())
            if key not in seen:
                seen.add(key)
                pool.append(_song(t["name"], t["artist"], t["duration"], t["thumbnail"], True))
    pool = [s for s in pool if s.track_name]
    random.shuffle(pool)
    if not pool:
        raise PlayerError("Couldn't find any songs for that. Try another genre, decade or playlist.")
    return pool[: max(size * 2, size + 5)]  # spares in case some won't play


# --- The game ---

@dataclass
class Round:
    number: int
    song: Song
    title_by: tuple[int, str] | None = None
    artist_by: tuple[int, str] | None = None

    @property
    def complete(self) -> bool:
        return self.title_by is not None and (self.artist_by is not None or not self.song.artist)


@dataclass
class Score:
    name: str
    points: int = 0


@dataclass
class GuessTheSong:
    player: GuildPlayer
    channel: discord.abc.Messageable
    starter: discord.Member
    pool: list[Song]
    rounds: int = 10
    clip_seconds: int = 25
    scores: dict[int, Score] = field(default_factory=dict)
    current: Round | None = None
    last: Round | None = None
    _done: asyncio.Event = field(default_factory=asyncio.Event)
    _aborted: bool = False
    _task: asyncio.Task | None = None

    def start(self):
        self.player.game = self
        self._task = asyncio.create_task(self._run())

    def abort(self):
        self._aborted = True
        self._done.set()

    def can_stop(self, member: discord.Member) -> bool:
        return member.id == self.starter.id or self.player.manager.is_dj(member)

    # --- What the dashboard sees (never the answer while a round is on) ---

    def placeholder(self) -> dict:
        n = self.current.number if self.current else (self.last.number if self.last else 0)
        return {
            "id": 0, "title": "Guess the song", "url": "", "duration": 0, "thumbnail": "",
            "artist": f"Round {n} of {self.rounds}", "requester": self.starter.display_name,
            "requester_id": str(self.starter.id), "requester_avatar": "", "source": "game", "live": True,
        }

    def leaderboard(self) -> list[tuple[int, Score]]:
        return sorted(self.scores.items(), key=lambda kv: -kv[1].points)

    def public_state(self) -> dict:
        last = None
        if self.last and (self.current is None or self.current.number != self.last.number):
            s = self.last.song
            last = {"title": s.track_name, "artist": s.artist, "thumbnail": s.thumbnail}
        return {
            "round": self.current.number if self.current else (self.last.number if self.last else 0),
            "rounds": self.rounds,
            "clip_seconds": self.clip_seconds,
            "starter": self.starter.display_name,
            "scores": [{"id": str(uid), "name": p.name, "points": p.points} for uid, p in self.leaderboard()[:10]],
            "last": last,
        }

    # --- Guesses ---

    async def on_message(self, message: discord.Message):
        r = self.current
        if r is None or message.author.bot or message.channel.id != getattr(self.channel, "id", None):
            return
        vc = self.player.voice
        voice = getattr(message.author, "voice", None)
        if not vc or not voice or voice.channel != vc.channel:
            return  # only people who can hear it can play
        who = (message.author.id, message.author.display_name)
        got = []
        if r.title_by is None and matches(message.content, r.song.track_name):
            r.title_by = who
            got.append(("the title", TITLE_POINTS))
        if r.artist_by is None and r.song.artist and any(matches(message.content, a) for a in artists_of(r.song.artist)):
            r.artist_by = who
            got.append(("the artist", ARTIST_POINTS))
        if not got:
            return
        entry = self.scores.setdefault(message.author.id, Score(message.author.display_name))
        entry.points += sum(points for _, points in got)
        what = " and ".join(name for name, _ in got)
        try:
            await message.add_reaction("✅")
            await self.channel.send(f"**{discord.utils.escape_markdown(entry.name)}** got {what}! "
                                    f"(+{sum(p for _, p in got)})")
        except discord.HTTPException:
            pass
        self.player.notify()
        if r.complete:
            self._done.set()

    # --- Running it ---

    async def _send(self, **kwargs):
        try:
            return await self.channel.send(**kwargs)
        except discord.HTTPException as e:
            log.debug("Game message failed: %s", e)
            return None

    async def _set_status(self, text: str | None):
        vc = self.player.voice
        try:
            if vc and vc.channel:
                await vc.channel.edit(status=text)
        except (discord.HTTPException, AttributeError, TypeError):
            pass

    async def _ready_song(self) -> Song | None:
        """The next song that actually resolves; broken ones are skipped quietly."""
        while self.pool and not self._aborted:
            song = self.pool.pop()
            try:
                await self.player.manager.resolve_input(song, cache=False)
                return song
            except Exception as e:
                log.debug("Skipping %r in the game: %s", song.title, e)
        return None

    def _clip_start(self, song: Song) -> float:
        length = song.duration or (song.track.duration if song.track else 0)
        if length < self.clip_seconds + 30:
            return 0
        latest = max(0, length - self.clip_seconds - 10)
        return min(latest, random.uniform(0.25, 0.55) * length)  # past the intro, before the end

    async def _wait(self, seconds: float) -> bool:
        """Wait, or stop early if the round is done or the game ends. True if it ended early."""
        try:
            await asyncio.wait_for(self._done.wait(), timeout=seconds)
            return True
        except TimeoutError:
            return False

    def _hint(self, song: Song) -> str:
        words = song.track_name.split()
        return f"💡 Hint: the title has **{len(words)}** word{'s' * (len(words) != 1)} and starts with **{song.track_name[0]}**."

    async def _run(self):
        try:
            await self._set_status("🎮 Guess the song")
            intro = discord.Embed(
                title="🎮 Guess the song",
                description=(f"**{self.rounds}** rounds, **{self.clip_seconds}s** each. Type your guesses here!\n"
                             f"Title: **+{TITLE_POINTS}** · Artist: **+{ARTIST_POINTS}** · "
                             f"Only people in {self.player.voice.channel.mention} can play."),
                color=ACCENT,
            )
            await self._send(embed=intro)
            upcoming = asyncio.create_task(self._ready_song())
            for number in range(1, self.rounds + 1):
                song = await upcoming
                if song is None or self._aborted:
                    if song is None and not self._aborted:
                        await self._send(content="Ran out of songs that would play, so that's the game!")
                    break
                upcoming = asyncio.create_task(self._ready_song())  # get the next one ready meanwhile
                self.current = Round(number, song)
                self._done.clear()
                await self.player.play_clip(song, self._clip_start(song))
                await self._send(content=f"🎵 **Round {number}/{self.rounds}**: what's this song?")
                if not await self._wait(self.clip_seconds * 0.6) and not self.current.title_by and not self._aborted:
                    await self._send(content=self._hint(song))
                    await self._wait(self.clip_seconds * 0.4)
                await self.player.stop_clip()
                self.last, self.current = self.current, None
                if self._aborted:
                    break
                await self._reveal(self.last)
                self._done.clear()
                if number < self.rounds and await self._wait(ROUND_GAP) and self._aborted:
                    break
            upcoming.cancel()
            await self._finish()
        except Exception:
            log.exception("Guess the song crashed")
            await self._send(content="⚠️ The game hit a problem and had to stop.")
        finally:
            self.player.game = None
            self.current = None
            try:
                await self.player.stop_clip()
            except Exception:
                pass
            await self._set_status(None)
            self.player.notify()

    async def _reveal(self, r: Round):
        s = r.song
        embed = discord.Embed(description=f"It was **{discord.utils.escape_markdown(s.track_name)}**"
                                          + (f" by **{discord.utils.escape_markdown(s.artist)}**" if s.artist else ""),
                              color=ACCENT)
        embed.set_author(name=f"Round {r.number}/{self.rounds}")
        if s.thumbnail:
            embed.set_thumbnail(url=s.thumbnail)
        got = []
        if r.title_by:
            got.append(f"Title: **{r.title_by[1]}**")
        if r.artist_by:
            got.append(f"Artist: **{r.artist_by[1]}**")
        embed.add_field(name="Got it", value=" · ".join(got) or "Nobody this time!", inline=False)
        if self.scores:
            embed.add_field(name="Scores", value=self._table(5), inline=False)
        await self._send(embed=embed)

    def _table(self, limit: int) -> str:
        medals = ["🥇", "🥈", "🥉"]
        return "\n".join(
            f"{medals[i] if i < 3 else f'`{i + 1}.`'} **{discord.utils.escape_markdown(p.name)}**: {p.points}"
            for i, (_, p) in enumerate(self.leaderboard()[:limit])
        )

    async def _finish(self):
        board = self.leaderboard()
        embed = discord.Embed(title="🏁 Game over", color=ACCENT)
        if board:
            winner_id, winner = board[0]
            embed.description = f"🏆 **{discord.utils.escape_markdown(winner.name)}** wins with **{winner.points}** points!"
            embed.add_field(name="Final scores", value=self._table(10), inline=False)
            try:
                await self.player.manager.store.add_game_result(
                    self.player.guild_id, {uid: (p.name, p.points) for uid, p in board}, winner_id
                )
            except Exception:
                log.exception("Couldn't save game scores")
        else:
            embed.description = "Nobody scored. Tough crowd!"
        await self._send(embed=embed)
