"""Owns every guild's player plus the shared services they use (cache, Spotify, lyrics, settings)."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

import aiohttp
import discord

from mugetsu.media import youtube
from mugetsu.media.cache import CacheManager
from mugetsu.media.ffmpeg import AudioInput, build_source, get_filter, is_opus
from mugetsu.media.lyrics import Lyrics, LyricsFetcher
from mugetsu.media.radio import RadioBrowser, Station, parse_radio_query
from mugetsu.media.spotify import SpotifyResolver
from mugetsu.player.events import EventBus, StateNotifier
from mugetsu.player.models import LoopMode, PlayerError, Song, song_key
from mugetsu.player.player import GuildPlayer
from mugetsu.player.settings import GuildSettings
from mugetsu.store import Store
from mugetsu.util import short_error

if TYPE_CHECKING:
    from mugetsu.config import Config

log = logging.getLogger("mugetsu.manager")

URL_RE = re.compile(r"^https?://", re.IGNORECASE)
YOUTUBE_PLAYLIST_RE = re.compile(r"(youtube\.com/.*[?&]list=|youtu\.be/.*[?&]list=)([\w-]+)")
INACTIVITY_INTERVAL = 30
SEARCH_TTL = 300
SESSION_SAVE_DELAY = 2.0  # coalesce bursts of changes into one write
STATS_PERIODS = {"week": 7 * 86400, "month": 30 * 86400, "all": None}
AUTOPLAY_BATCH = 3
AUTOPLAY_MAX_LENGTH = 15 * 60  # skip hour-long mixes and the like
RADIO_QUERY = "radio:"


@dataclass(frozen=True)
class Requester:
    name: str
    id: int
    avatar: str = ""

    @classmethod
    def of(cls, member: discord.abc.User) -> Requester:
        return cls(member.display_name, member.id, member.display_avatar.with_size(64).url)

    def fields(self) -> dict:
        return {"requester": self.name, "requester_id": self.id, "requester_avatar": self.avatar}


class PlayerHooks:
    """How the player reaches Discord chat. The UI layer replaces these no-op defaults."""

    async def notice(self, player: GuildPlayer, text: str):
        pass

    async def track_started(self, player: GuildPlayer, song: Song, *, announce: bool):
        pass

    async def track_cleared(self, player: GuildPlayer):
        pass

    async def resumed(self, player: GuildPlayer, song: Song, position: float):
        pass


class PlayerManager:
    def __init__(self, bot: discord.Client, config: Config):
        self.bot = bot
        self.config = config
        self.settings = GuildSettings(config.cache_dir)
        self.cache = CacheManager(config.cache_dir, config.cache_limit_mb, config.max_cache_duration)
        self.spotify = SpotifyResolver(config.spotify_client_id, config.spotify_client_secret)
        self.lyrics = LyricsFetcher(config.genius_token)
        self.store = Store(config.cache_dir)
        self.radio = RadioBrowser(lambda: self.http, prefer_country=config.radio_country)
        self.http: aiohttp.ClientSession | None = None
        self.events = EventBus()
        self.notify = StateNotifier(self.events, self.snapshot)
        self.hooks = PlayerHooks()
        self.make_source = build_source  # swapped out in tests
        self._players: dict[int, GuildPlayer] = {}
        self._inactivity_task: asyncio.Task | None = None
        self._search_cache: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self._search_slot = asyncio.Semaphore(1)  # keep a worker free for playback
        self._pending_saves: dict[int, asyncio.TimerHandle] = {}
        self._background: set[asyncio.Task] = set()
        self._restored = False

    async def start(self):
        await self.settings.initialize()
        await self.cache.initialize()
        await self.store.initialize()
        self.http = aiohttp.ClientSession()
        self._inactivity_task = asyncio.create_task(self._inactivity_loop())

    async def close(self):
        if self._inactivity_task:
            self._inactivity_task.cancel()
        for handle in self._pending_saves.values():
            handle.cancel()
        for guild_id in list(self._players):
            try:
                await self._save_session(guild_id)  # so a restart can pick up from here
                await self.destroy(guild_id, keep_session=True)
            except Exception:
                log.exception("[Guild %d] Error while shutting down the player", guild_id)
        if self._background:
            await asyncio.gather(*self._background, return_exceptions=True)
        await self.cache.close()
        await self.settings.close()
        await self.store.close()
        if self.http:
            await self.http.close()
        youtube.shutdown()

    def background(self, coro) -> asyncio.Task:
        """Run bookkeeping (database writes) without making playback wait for it."""
        task = asyncio.create_task(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        return task

    def changed(self, guild_id: int):
        """Something about a guild's player changed: push it to the dashboard and save it for restarts."""
        self.notify(guild_id)
        if self.config.resume_window <= 0 or guild_id in self._pending_saves:
            return

        def save():
            self._pending_saves.pop(guild_id, None)
            self.background(self._save_session(guild_id))

        self._pending_saves[guild_id] = asyncio.get_running_loop().call_later(SESSION_SAVE_DELAY, save)

    # --- Players ---

    def get(self, guild_id: int) -> GuildPlayer:
        player = self._players.get(guild_id)
        if player is None:
            player = GuildPlayer(self, guild_id, self.settings.get(guild_id))
            self._players[guild_id] = player
        return player

    def peek(self, guild_id: int) -> GuildPlayer | None:
        return self._players.get(guild_id)

    def snapshot(self, guild_id: int) -> dict:
        player = self._players.get(guild_id) or GuildPlayer(self, guild_id, self.settings.get(guild_id))
        return player.snapshot()

    async def destroy(self, guild_id: int, *, disconnect: bool = True, keep_session: bool = False):
        """The single path for leaving a guild: reset state and optionally disconnect."""
        if not keep_session:
            handle = self._pending_saves.pop(guild_id, None)
            if handle:
                handle.cancel()
            self.background(self.store.clear_session(guild_id))
        player = self._players.pop(guild_id, None)
        if player:
            await player.close(disconnect=disconnect)
        elif disconnect:
            guild = self.bot.get_guild(guild_id)
            if guild and guild.voice_client:
                await guild.voice_client.disconnect(force=True)
        self.notify(guild_id)

    # --- Permissions ---

    def dj_role(self, guild: discord.Guild) -> discord.Role | None:
        return discord.utils.get(guild.roles, name=self.config.dj_role)

    def is_dj(self, member: discord.Member) -> bool:
        role = self.dj_role(member.guild)
        return role is None or member.guild_permissions.administrator or role in member.roles

    def can_force_skip(self, member: discord.Member, player: GuildPlayer) -> bool:
        role = self.dj_role(member.guild)
        return (
            member.guild_permissions.administrator
            or (role is not None and role in member.roles)
            or (player.current is not None and player.current.requester_id == member.id)
        )

    def require_dj(self, member: discord.Member | None):
        if member is not None and not self.is_dj(member):
            raise PlayerError(f"You need the {self.config.dj_role} role to do that.")

    # --- Voice ---

    async def join(self, member: discord.Member) -> discord.VoiceClient:
        if not member.voice or not member.voice.channel:
            raise PlayerError("Join a voice channel first.")
        target = member.voice.channel
        guild = member.guild
        vc = guild.voice_client
        player = self.get(guild.id)
        if vc and vc.is_connected():
            if vc.channel != target:
                if player.current and player.listeners():
                    raise PlayerError(f"I'm already playing in {vc.channel.mention}.")
                await vc.move_to(target)
                self.notify(guild.id)
            return vc
        perms = target.permissions_for(guild.me)
        if not (perms.connect and perms.speak):
            raise PlayerError(f"I need permission to connect and speak in {target.mention}.")
        try:
            vc = await target.connect(self_deaf=True, timeout=20)
        except (TimeoutError, discord.ClientException) as e:
            raise PlayerError(f"Couldn't connect to {target.mention}: {short_error(e)}") from e
        player.idle_since = time.monotonic()
        player.alone_since = None
        self.notify(guild.id)
        return vc

    async def _inactivity_loop(self):
        await self.bot.wait_until_ready()
        while True:
            await asyncio.sleep(INACTIVITY_INTERVAL)
            try:
                await self.check_inactivity()
            except Exception:
                log.exception("Inactivity check failed")

    async def check_inactivity(self):
        now = time.monotonic()
        for vc in list(self.bot.voice_clients):
            guild = vc.guild
            player = self.get(guild.id)
            if player.twenty_four_seven:
                continue
            if player.listeners():
                player.alone_since = None
            else:
                player.alone_since = player.alone_since or now
                if now - player.alone_since > self.config.alone_timeout:
                    log.info("[Guild %d] Leaving: nobody listening", guild.id)
                    await self.hooks.notice(player, "👋 Left the voice channel since everyone left.")
                    await self.destroy(guild.id)
                    continue
            if player.current is None and player.idle_since and now - player.idle_since > self.config.idle_timeout:
                log.info("[Guild %d] Leaving: idle for %d min", guild.id, self.config.idle_timeout // 60)
                await self.destroy(guild.id)

    # --- Resolving tracks ---

    async def _extract(self, song: Song) -> youtube.Track:
        query = song.query
        if song.search_music:
            query = await youtube.music_search(song.query) or f"ytsearch1:{song.query}"
        return await youtube.extract_track(query)

    @staticmethod
    def apply_track(song: Song, track: youtube.Track):
        song.track = track
        song.url = track.webpage_url
        song.duration = track.duration or song.duration
        if not song.search_music:  # keep Spotify's cleaner title and album art
            song.title = track.title
            song.thumbnail = track.thumbnail or song.thumbnail

    async def resolve_input(self, song: Song, *, cache: bool = True) -> AudioInput:
        """Where to read audio from: the local cache if possible, otherwise a live stream."""
        if song.stream_url:  # internet radio: play the station's stream as-is
            return AudioInput(song.stream_url, is_local=False, is_opus=False)
        checked_key = None
        if song.url:
            checked_key = CacheManager.extract_cache_key(song.url)
            entry = await self.cache.lookup(checked_key)
            if entry:
                song.title = song.title if song.search_music else (entry.title or song.title)
                song.duration = entry.duration or song.duration
                song.thumbnail = song.thumbnail or entry.thumbnail
                return AudioInput(entry.path, is_local=True, is_opus=is_opus(entry.acodec, entry.path))

        track = song.track if song.track and song.track.fresh else await self._extract(song)
        self.apply_track(song, track)
        key = CacheManager.extract_cache_key(track.webpage_url)
        if key != checked_key:
            entry = await self.cache.lookup(key)
            if entry:
                return AudioInput(entry.path, is_local=True, is_opus=is_opus(entry.acodec, entry.path))
        if cache and self.cache.cacheable(track.duration, track.is_live):
            self.cache.schedule_download(
                key, track.webpage_url, title=song.title, duration=track.duration, thumbnail=song.thumbnail
            )
        return AudioInput(track.stream_url, is_local=False, is_opus=track.acodec == "opus", user_agent=track.user_agent)

    async def prefetch(self, song: Song) -> bool:
        """Resolve and start caching a queued song ahead of time. Returns True if its metadata changed."""
        if song.stream_url:
            return False
        if song.url and await self.cache.contains(CacheManager.extract_cache_key(song.url)):
            return False
        changed = False
        if not (song.track and song.track.fresh):
            self.apply_track(song, await self._extract(song))
            changed = True
        track = song.track
        key = CacheManager.extract_cache_key(track.webpage_url)
        if self.cache.cacheable(track.duration, track.is_live) and not await self.cache.contains(key):
            self.cache.schedule_download(key, track.webpage_url, title=song.title,
                                         duration=track.duration, thumbnail=song.thumbnail)
        return changed

    async def resolve_query(self, query: str, requester: Requester) -> tuple[list[Song], str]:
        """Turn user input into songs. Returns (songs, collection label or "")."""
        who = requester.fields()
        query = query.strip().strip("<>")
        if not query:
            raise PlayerError("Type something to play.")

        if query.startswith(RADIO_QUERY):
            try:
                station = await self.radio.by_uuid(query.removeprefix(RADIO_QUERY))
            except Exception as e:
                raise PlayerError(f"Couldn't reach the radio directory: {short_error(e)}") from e
            if station is None:
                raise PlayerError("That radio station isn't listed anymore.")
            return [self.station_song(station, requester)], ""

        if SpotifyResolver.is_spotify_url(query):
            if not self.spotify.enabled:
                raise PlayerError("Spotify isn't set up on this bot.")
            try:
                name, tracks = await asyncio.to_thread(self.spotify.resolve, query)
            except Exception as e:
                raise PlayerError(f"Couldn't load that Spotify link: {short_error(e)}") from e
            if not tracks:
                raise PlayerError("That Spotify link has no playable tracks.")
            songs = [
                Song(title=t["title"], query=t["title"], duration=t["duration"], thumbnail=t["thumbnail"],
                     artist=t["artist"], track_name=t["name"], origin_url=t.get("url", ""), search_music=True, **who)
                for t in tracks
            ]
            return songs, name if len(songs) > 1 else ""

        playlist = YOUTUBE_PLAYLIST_RE.search(query)
        # Mixes (list=RD…) are endless auto-generated radios: just play the linked video
        if playlist and not (playlist.group(2).startswith("RD") and "v=" in query):
            try:
                entries = await youtube.extract_playlist(query)
            except Exception as e:
                raise PlayerError(f"Couldn't load that playlist: {short_error(e)}") from e
            if not entries:
                raise PlayerError("That playlist is empty or private.")
            songs = [
                Song(title=e["title"], query=e["url"], url=e["url"], duration=e["duration"],
                     thumbnail=e["thumbnail"], **who)
                for e in entries
            ]
            return songs, "YouTube playlist"

        # Single track: resolve now so the queue shows real metadata and errors surface immediately
        is_url = bool(URL_RE.match(query))
        if is_url:
            entry = await self.cache.lookup(CacheManager.extract_cache_key(query))
            if entry:
                return [Song(title=entry.title or query, query=query, url=query, duration=entry.duration,
                             thumbnail=entry.thumbnail, **who)], ""
        try:
            track = await youtube.extract_track(query if is_url else f"ytsearch1:{query}")
        except LookupError as e:
            raise PlayerError(str(e)) from e
        except Exception as e:
            raise PlayerError(f"Couldn't load that: {short_error(e)}") from e
        song = Song(title=track.title, query=query, **who)
        self.apply_track(song, track)
        return [song], ""

    # --- Dashboard helpers ---

    async def search(self, query: str) -> dict:
        """Spotify songs and albums plus YouTube videos, cached briefly."""
        key = query.strip().lower()
        hit = self._search_cache.get(key)
        if hit and time.monotonic() - hit[0] < SEARCH_TTL:
            return hit[1]

        if key.startswith("radio ") or key == "radio":
            try:
                name, country = parse_radio_query(query.strip()[6:])
                stations = await self.radio.search(name, country, limit=8)
            except Exception as e:
                log.warning("Radio search failed for %r: %s", query, e)
                stations = []
            result = {"songs": [], "albums": [], "videos": [], "stations": [s.to_dict() for s in stations]}
            self._search_cache[key] = (time.monotonic(), result)
            return result

        async def spotify():
            if not self.spotify.enabled:
                return {"songs": [], "albums": []}
            # Don't let a slow Spotify API hold up the YouTube results
            return await asyncio.wait_for(asyncio.to_thread(self.spotify.search, query, 5, 2), timeout=4)

        async def videos():
            async with self._search_slot:
                return await youtube.search(query, count=6)

        found_videos, found = await asyncio.gather(videos(), spotify(), return_exceptions=True)
        failed = False
        for name, result in (("YouTube", found_videos), ("Spotify", found)):
            if isinstance(result, BaseException):
                failed = True
                log.warning("%s search failed for %r: %r", name, query, result)
        found = found if isinstance(found, dict) else {"songs": [], "albums": []}
        result = {
            "songs": found["songs"],
            "albums": found["albums"],
            "videos": found_videos if isinstance(found_videos, list) else [],
            "stations": [],
        }
        if not failed:
            self._search_cache[key] = (time.monotonic(), result)
            while len(self._search_cache) > 200:
                self._search_cache.popitem(last=False)
        return result

    async def lyrics_for(self, song: Song) -> Lyrics | None:
        return await self.lyrics.fetch(
            self.http, song.title, artist=song.artist, track=song.track_name, duration=song.duration
        )

    # --- Internet radio ---

    def station_song(self, station: Station, requester: Requester) -> Song:
        self.radio.count_click(station.uuid)
        return Song(
            title=station.name, query=f"{RADIO_QUERY}{station.uuid}", url=station.homepage,
            stream_url=station.stream_url, thumbnail=station.favicon, artist=station.summary,
            **requester.fields(),
        )

    # --- Play history and stats ---

    async def log_play(self, guild_id: int, song: Song) -> int | None:
        try:
            return await self.store.log_play(guild_id, song.to_record())
        except Exception:
            log.exception("[Guild %d] Couldn't log a play", guild_id)
            return None

    async def finish_play(self, logged: asyncio.Task, seconds: float):
        try:
            play_id = await logged
            if play_id is not None:
                await self.store.finish_play(play_id, seconds)
        except Exception:
            log.exception("Couldn't finish logging a play")

    async def stats(self, guild_id: int, period: str = "week") -> dict:
        if period not in STATS_PERIODS:
            raise PlayerError("Period must be `week`, `month` or `all`.")
        window = STATS_PERIODS[period]
        data = await self.store.stats(guild_id, since=None if window is None else time.time() - window)
        return {**data, "period": period}

    async def recent_songs(self, guild_id: int, member: discord.abc.User, count: int) -> list[Song]:
        records = await self.store.recent_requests(guild_id, member.id, count)
        who = Requester.of(member).fields()
        return [Song.from_record(r, who) for r in records]

    # --- Autoplay ---

    async def recommend(self, seed: Song, exclude: set[str], count: int = AUTOPLAY_BATCH) -> list[Song]:
        """Songs to play after `seed` when the queue runs out, skipping anything in `exclude`."""
        video_id = CacheManager.extract_cache_key(seed.url) if seed.url else ""
        if len(video_id) != 11 or seed.stream_url:
            return []
        try:
            entries = await youtube.related(video_id)
        except Exception as e:
            log.debug("Autoplay lookup failed for %r: %s", seed.title, e)
            return []
        songs = []
        for e in entries:
            key = song_key(e["url"], e["title"])
            if key in exclude or key == video_id or not 0 < e["duration"] <= AUTOPLAY_MAX_LENGTH:
                continue
            exclude.add(key)
            artist = e.get("artist") or ""
            title = f"{artist} - {e['title']}" if artist and artist.lower() not in e["title"].lower() else e["title"]
            songs.append(Song(title=title, query=e["url"], url=e["url"], duration=e["duration"],
                              thumbnail=e["thumbnail"], artist=artist, track_name=e["title"],
                              requester="Autoplay", requester_id=0))
            if len(songs) >= count:
                break
        return songs

    # --- Picking up after a restart ---

    def _session_data(self, player: GuildPlayer) -> dict | None:
        vc = player.voice
        if player.game or not vc or not vc.is_connected() or not (player.current or player.q.queue):
            return None
        q = player.q
        return {
            "voice_channel_id": vc.channel.id,
            "text_channel_id": player.text_channel_id,
            "current": q.current.to_record() if q.current else None,
            "position": round(q.position, 1) if q.current else 0,
            "paused": vc.is_paused(),
            "loop": q.loop_mode.value,
            "effect": q.audio_filter.key if q.audio_filter else "",
            "queue": [s.to_record() for s in q.queue][:1000],
        }

    async def _save_session(self, guild_id: int):
        player = self._players.get(guild_id)
        data = self._session_data(player) if player else None
        try:
            if data:
                await self.store.save_session(guild_id, data)
            else:
                await self.store.clear_session(guild_id)
        except Exception:
            log.exception("[Guild %d] Couldn't save the session", guild_id)

    async def restore_sessions(self):
        """After a restart, rejoin voice and carry on where each server left off."""
        if self._restored or self.config.resume_window <= 0:
            return
        self._restored = True
        try:
            sessions = await self.store.sessions(self.config.resume_window)
        except Exception:
            log.exception("Couldn't read saved sessions")
            return
        for guild_id, data in sessions:
            try:
                await self._restore(guild_id, data)
            except Exception:
                log.exception("[Guild %d] Couldn't resume the session", guild_id)
                await self.store.clear_session(guild_id)

    async def _restore(self, guild_id: int, data: dict):
        guild = self.bot.get_guild(guild_id)
        channel = guild.get_channel(data.get("voice_channel_id") or 0) if guild else None
        if channel is None or guild.voice_client:
            await self.store.clear_session(guild_id)
            return
        player = self.get(guild_id)
        if not any(not m.bot for m in channel.members) and not player.twenty_four_seven:
            log.info("[Guild %d] Not resuming: nobody is in %s", guild_id, channel.name)
            await self.destroy(guild_id, disconnect=False)
            return
        perms = channel.permissions_for(guild.me)
        if not (perms.connect and perms.speak):
            await self.destroy(guild_id, disconnect=False)
            return
        await channel.connect(self_deaf=True, timeout=20)
        player.text_channel_id = data.get("text_channel_id")
        try:
            player.q.loop_mode = LoopMode(data.get("loop", "off"))
        except ValueError:
            pass
        try:
            player.q.audio_filter = get_filter(data.get("effect", ""))
        except ValueError:
            pass
        player.q.add([Song.from_record(r) for r in data.get("queue", [])])
        current = Song.from_record(data["current"]) if data.get("current") else None
        position = float(data.get("position") or 0)
        if current and current.duration and position >= current.duration - 3:
            position = 0  # it had all but finished
        started = await player.resume_session(current, position, paused=bool(data.get("paused")))
        log.info("[Guild %d] Resumed after restart: %s", guild_id, started.title if started else "queue only")
        if started:
            await self.hooks.resumed(player, started, position if started is current else 0)

