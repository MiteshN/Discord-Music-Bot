"""Lyrics lookup: LRCLIB first (free, no key, has time-synced lyrics), Genius as an optional fallback."""

from __future__ import annotations

import asyncio
import logging
import re
from collections import OrderedDict
from dataclasses import dataclass, field

import aiohttp

log = logging.getLogger("mugetsu.lyrics")

LRCLIB_URL = "https://lrclib.net/api"
USER_AGENT = "Mugetsu Discord music bot (https://github.com/MiteshN/Discord-Music-Bot)"

# Noise commonly found in YouTube titles that hurts lyric matching
_TITLE_NOISE = re.compile(
    r"[\(\[][^)\]]*(official|video|audio|lyric|visuali[sz]er|remaster|hd|4k|mv|m/v|live|explicit)[^)\]]*[\)\]]"
    r"|\b(official (music )?video|lyrics?|hq|hd)\b",
    re.IGNORECASE,
)
_FEAT = re.compile(r"\s+\(?(ft|feat|featuring)\.?\s.*$", re.IGNORECASE)
_LRC_TIME = re.compile(r"\[(\d{1,3}):(\d{1,2}(?:[.:]\d{1,3})?)\]")


@dataclass
class LyricLine:
    time: float
    text: str


@dataclass
class Lyrics:
    plain: str
    synced: list[LyricLine] = field(default_factory=list)
    source: str = ""

    def to_dict(self) -> dict:
        return {
            "plain": self.plain,
            "synced": [{"time": round(line.time, 2), "text": line.text} for line in self.synced],
            "source": self.source,
        }


def clean_title(title: str) -> str:
    title = _TITLE_NOISE.sub("", title)
    title = _FEAT.sub("", title)
    return re.sub(r"\s{2,}", " ", title).strip(" -|")


def split_artist(title: str) -> tuple[str, str]:
    """Best-effort "Artist - Song" split of a video title. Returns ("", title) if there's no artist."""
    cleaned = clean_title(title)
    for sep in (" - ", " – ", " — ", " | "):
        if sep in cleaned:
            artist, song = cleaned.split(sep, 1)
            return artist.strip(), clean_title(song)
    return "", cleaned


def parse_lrc(text: str) -> list[LyricLine]:
    """Parse LRC text (``[mm:ss.xx] line``, possibly several stamps per line) into sorted lines."""
    lines: list[LyricLine] = []
    for raw in (text or "").splitlines():
        stamps = list(_LRC_TIME.finditer(raw))
        if not stamps:
            continue
        lyric = raw[stamps[-1].end():].strip()
        for m in stamps:
            seconds = int(m.group(1)) * 60 + float(m.group(2).replace(":", "."))
            lines.append(LyricLine(seconds, lyric))
    lines.sort(key=lambda line: line.time)
    return lines


def pick_best(results: list[dict], duration: int) -> dict | None:
    """Choose the LRCLIB result that best fits: duration within a few seconds, synced lyrics preferred."""
    usable = [r for r in results if r.get("plainLyrics") or r.get("syncedLyrics")]
    if not usable:
        return None

    def score(r: dict) -> tuple:
        diff = abs((r.get("duration") or 0) - duration) if duration else 0
        return (diff > 5, not r.get("syncedLyrics"), diff)

    best = min(usable, key=score)
    if duration and best.get("duration") and abs(best["duration"] - duration) > 20:
        return None  # almost certainly a different song (or a very different edit)
    return best


def split_lyrics(lyrics: str, limit: int = 4096) -> list[str]:
    chunks = []
    while len(lyrics) > limit:
        split_at = lyrics.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(lyrics[:split_at])
        lyrics = lyrics[split_at:].lstrip("\n")
    if lyrics:
        chunks.append(lyrics)
    return chunks


class LyricsFetcher:
    def __init__(self, genius_token: str = ""):
        self.genius = None
        self._cache: OrderedDict[str, Lyrics | None] = OrderedDict()
        if genius_token:
            # Optional fallback: a broken or changed lyricsgenius must never stop the bot from starting
            try:
                import lyricsgenius

                self.genius = lyricsgenius.Genius(genius_token, remove_section_headers=True, timeout=10, retries=1)
            except Exception as e:
                log.warning("Genius lyrics disabled, couldn't initialise lyricsgenius: %s", e)

    async def fetch(
        self, session: aiohttp.ClientSession, title: str, *, artist: str = "", track: str = "", duration: int = 0
    ) -> Lyrics | None:
        key = f"{artist}\0{track}\0{title}\0{duration}".lower()
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        result, complete = await self._lookup(session, title, artist=artist, track=track, duration=duration)
        if result is not None or complete:  # don't remember a miss caused by a network error
            self._cache[key] = result
            while len(self._cache) > 128:
                self._cache.popitem(last=False)
        return result

    async def _lookup(self, session, title, *, artist, track, duration) -> tuple[Lyrics | None, bool]:
        if not (artist and track):
            artist, track = split_artist(title)
        result = None
        complete = True
        try:
            if artist and track:
                result = await self._lrclib_get(session, artist, track, duration)
            if result is None:
                params = {"track_name": track, "artist_name": artist} if artist else {"q": track}
                result = pick_best(await self._lrclib_search(session, params), duration)
            if result is None and artist:
                result = pick_best(await self._lrclib_search(session, {"q": f"{artist} {track}"}), duration)
        except (TimeoutError, aiohttp.ClientError, ValueError) as e:
            log.debug("LRCLIB lookup failed for %r: %s", title, e)
            complete = False

        if result:
            plain = result.get("plainLyrics") or ""
            synced = parse_lrc(result.get("syncedLyrics") or "")
            if not plain and synced:
                plain = "\n".join(line.text for line in synced)
            if plain.strip():
                return Lyrics(plain.strip(), synced, "LRCLIB"), True

        if self.genius:
            query = f"{artist} {track}".strip() if artist else track
            try:
                song = await asyncio.to_thread(self.genius.search_song, query)
                if song and song.lyrics:
                    return Lyrics(song.lyrics.strip(), [], "Genius"), True
            except Exception as e:
                log.debug("Genius lookup failed for %r: %s", query, e)
                complete = False
        return None, complete

    async def _lrclib_get(self, session, artist: str, track: str, duration: int) -> dict | None:
        params = {"artist_name": artist, "track_name": track}
        if duration:
            params["duration"] = str(duration)
        async with session.get(
            f"{LRCLIB_URL}/get", params=params, headers={"User-Agent": USER_AGENT},
            timeout=aiohttp.ClientTimeout(total=8),
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            return data if data.get("plainLyrics") or data.get("syncedLyrics") else None

    async def _lrclib_search(self, session, params: dict) -> list[dict]:
        async with session.get(
            f"{LRCLIB_URL}/search", params=params, headers={"User-Agent": USER_AGENT},
            timeout=aiohttp.ClientTimeout(total=8),
        ) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            return data if isinstance(data, list) else []
