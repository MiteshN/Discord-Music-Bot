"""yt-dlp extraction.

Extraction is CPU-heavy pure Python, so it runs in a small pool of worker
*processes* rather than threads. That keeps it from competing with
discord.py's audio thread for the GIL, which is what causes audible stutter
when a song is being resolved while another is playing.
"""

import asyncio
import functools
import logging
import multiprocessing
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from urllib.parse import quote_plus

log = logging.getLogger("bot.ytdl")

# Opus is what Discord speaks, so an Opus source can be passed through untouched.
AUDIO_FORMAT = "bestaudio[acodec=opus]/bestaudio/best"

_BASE_OPTIONS = {
    "format": AUDIO_FORMAT,
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
}

_OPTIONS = {
    "track": _BASE_OPTIONS,
    "flat": {**_BASE_OPTIONS, "extract_flat": "in_playlist", "ignoreerrors": True},
    "playlist": {**_BASE_OPTIONS, "noplaylist": False, "extract_flat": "in_playlist", "ignoreerrors": True},
    # Only the top hit: without this yt-dlp pages through every search result
    "music": {**_BASE_OPTIONS, "extract_flat": "in_playlist", "playlist_items": "1"},
}

# Resolved stream URLs expire after ~6h; refresh well before that.
STREAM_TTL = 30 * 60


@dataclass
class Track:
    """A fully resolved, playable track."""

    title: str
    webpage_url: str
    stream_url: str
    duration: int
    thumbnail: str
    is_live: bool
    acodec: str
    user_agent: str = ""
    resolved_at: float = field(default_factory=time.time)

    @property
    def fresh(self) -> bool:
        return time.time() - self.resolved_at < STREAM_TTL


def youtube_thumbnail(video_id: str | None) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg" if video_id else ""


# --- Worker-process side ---

_ydl_instances: dict = {}


class ExtractionError(Exception):
    """Plain, picklable stand-in for yt-dlp errors (theirs carry tracebacks that can't cross processes)."""


class _QuietLogger:
    # Failures are reported to users and logged by the bot; don't also dump them to stderr
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


def _picklable_errors(func):
    @functools.wraps(func)
    def wrapper(*args):
        try:
            return func(*args)
        except LookupError:
            raise
        except Exception as e:
            raise ExtractionError(str(e).replace("ERROR: ", "")) from None
    return wrapper


def _ydl(kind: str):
    if kind not in _ydl_instances:
        import yt_dlp

        _ydl_instances[kind] = yt_dlp.YoutubeDL({**_OPTIONS[kind], "logger": _QuietLogger()})
    return _ydl_instances[kind]


def _flat_entry(e: dict) -> dict | None:
    if not e or not e.get("title"):
        return None
    url = e.get("url") or e.get("webpage_url") or ""
    if not url and e.get("id"):
        url = f"https://www.youtube.com/watch?v={e['id']}"
    return {
        "title": e["title"],
        "url": url,
        "duration": int(e.get("duration") or 0),
        "thumbnail": e.get("thumbnail") or youtube_thumbnail(e.get("id")),
        "is_video": e.get("ie_key") != "YoutubeTab" and bool(e.get("duration")),
    }


@_picklable_errors
def _extract_track(query: str) -> dict:
    info = _ydl("track").extract_info(query, download=False)
    if info.get("entries") is not None:
        entries = [e for e in info["entries"] if e]
        if not entries:
            shown = query.split(":", 1)[1] if query.startswith("ytsearch") else query
            raise LookupError(f"No results for `{shown}`")
        info = entries[0]
    return {
        "title": info.get("title") or "Unknown",
        "webpage_url": info.get("webpage_url") or query,
        "stream_url": info["url"],
        "duration": int(info.get("duration") or 0),
        "thumbnail": info.get("thumbnail") or "",
        "is_live": bool(info.get("is_live")),
        "acodec": info.get("acodec") or "",
        "user_agent": (info.get("http_headers") or {}).get("User-Agent", ""),
    }


@_picklable_errors
def _search(query: str, count: int) -> list[dict]:
    # Ask for extra to account for channels/playlists mixed into results
    info = _ydl("flat").extract_info(f"ytsearch{count + 3}:{query}", download=False)
    entries = [_flat_entry(e) for e in info.get("entries") or []]
    return [e for e in entries if e and e["is_video"]][:count]


@_picklable_errors
def _music_search(query: str) -> str | None:
    """Best matching song on YouTube Music: official audio, no video intros/outros."""
    url = f"https://music.youtube.com/search?q={quote_plus(query)}#songs"
    info = _ydl("music").extract_info(url, download=False)
    for e in info.get("entries") or []:
        if e and e.get("url"):
            return e["url"]
    return None


@_picklable_errors
def _playlist(url: str) -> list[dict]:
    info = _ydl("playlist").extract_info(url, download=False)
    entries = [_flat_entry(e) for e in info.get("entries") or []]
    return [e for e in entries if e]


# --- Event-loop side ---

_pool: ProcessPoolExecutor | None = None


def _get_pool() -> ProcessPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context("spawn"))
    return _pool


async def _run(func, *args):
    global _pool
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(_get_pool(), func, *args)
    except BrokenProcessPool:
        log.warning("yt-dlp worker pool died, restarting it")
        _pool = None
        return await loop.run_in_executor(_get_pool(), func, *args)


def shutdown():
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=False, cancel_futures=True)
        _pool = None


async def extract_track(query: str) -> Track:
    """Resolve a URL or search text to a playable track."""
    log.debug("Extracting: %s", query)
    return Track(**await _run(_extract_track, query))


async def search(query: str, count: int = 5) -> list[dict]:
    return await _run(_search, query, count)


async def music_search(query: str) -> str | None:
    try:
        return await _run(_music_search, query)
    except Exception as e:
        log.debug("YouTube Music search failed for %r: %s", query, e)
        return None


async def extract_playlist(url: str) -> list[dict]:
    return await _run(_playlist, url)
