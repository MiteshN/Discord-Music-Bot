"""On-disk LRU cache of audio files.

Tracks are streamed on first play while a copy downloads in the background.
Later plays read the local file, so they start instantly and can't stutter
on network hiccups. Track metadata is cached alongside the file, so a cache
hit needs no network round-trip at all.
"""

import asyncio
import hashlib
import logging
import os
import re
import sys
import time
from dataclasses import dataclass

import aiosqlite

from utils.youtube import AUDIO_FORMAT

log = logging.getLogger("bot.cache")

YOUTUBE_ID_RE = re.compile(
    r"(?:youtube\.com/watch\?.*v=|youtu\.be/|youtube\.com/embed/|youtube\.com/shorts/)([A-Za-z0-9_-]{11})"
)
_DB_SUFFIXES = (".db", ".db-journal", ".db-wal", ".db-shm")
_DOWNLOAD_TIMEOUT = 600


@dataclass
class CacheEntry:
    path: str
    title: str
    duration: int
    thumbnail: str
    acodec: str


class CacheManager:
    def __init__(self, cache_dir: str = "./cache", max_size_mb: int = 2048, max_duration_sec: int = 1800):
        self.cache_dir = os.environ.get("CACHE_DIR", cache_dir)
        self.max_size_bytes = int(os.environ.get("CACHE_LIMIT_MB", max_size_mb)) * 1024 * 1024
        self.max_duration_sec = int(os.environ.get("MAX_CACHE_DURATION", max_duration_sec))
        self.db_path = os.path.join(self.cache_dir, "cache.db")
        self._db: aiosqlite.Connection | None = None
        self._inflight: dict[str, asyncio.Task] = {}
        self._download_slots = asyncio.Semaphore(2)
        self.hits = 0
        self.misses = 0

    @property
    def enabled(self) -> bool:
        return self.max_size_bytes > 0

    async def initialize(self):
        os.makedirs(self.cache_dir, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS cache_entries (
                cache_key TEXT PRIMARY KEY,
                file_path TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                last_accessed REAL NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        # Metadata columns added later; migrate older databases in place
        async with self._db.execute("PRAGMA table_info(cache_entries)") as cursor:
            columns = {row[1] for row in await cursor.fetchall()}
        for name, decl in (
            ("title", "TEXT DEFAULT ''"),
            ("duration", "INTEGER DEFAULT 0"),
            ("thumbnail", "TEXT DEFAULT ''"),
            ("acodec", "TEXT DEFAULT ''"),
        ):
            if name not in columns:
                await self._db.execute(f"ALTER TABLE cache_entries ADD COLUMN {name} {decl}")
        await self._db.commit()
        await self._cleanup()

    async def close(self):
        for task in list(self._inflight.values()):
            task.cancel()
        if self._inflight:
            await asyncio.gather(*self._inflight.values(), return_exceptions=True)
        if self._db:
            await self._db.close()
            self._db = None

    @staticmethod
    def extract_cache_key(url: str) -> str:
        m = YOUTUBE_ID_RE.search(url)
        if m:
            return m.group(1)
        return hashlib.sha256(url.encode()).hexdigest()[:16]

    async def lookup(self, cache_key: str) -> CacheEntry | None:
        if not self._db:
            return None
        async with self._db.execute(
            "SELECT file_path, title, duration, thumbnail, acodec FROM cache_entries WHERE cache_key = ?",
            (cache_key,),
        ) as cursor:
            row = await cursor.fetchone()
        if row and os.path.isfile(row[0]):
            await self._db.execute(
                "UPDATE cache_entries SET last_accessed = ? WHERE cache_key = ?", (time.time(), cache_key)
            )
            await self._db.commit()
            self.hits += 1
            return CacheEntry(*row)
        if row:  # record exists but the file is gone
            await self._db.execute("DELETE FROM cache_entries WHERE cache_key = ?", (cache_key,))
            await self._db.commit()
        self.misses += 1
        return None

    async def contains(self, cache_key: str) -> bool:
        if not self._db:
            return False
        async with self._db.execute("SELECT file_path FROM cache_entries WHERE cache_key = ?", (cache_key,)) as cursor:
            row = await cursor.fetchone()
        return bool(row and os.path.isfile(row[0])) or cache_key in self._inflight

    def cacheable(self, duration: int, is_live: bool) -> bool:
        return self.enabled and not is_live and 0 < duration <= self.max_duration_sec

    def schedule_download(self, cache_key: str, url: str, *, title: str, duration: int, thumbnail: str):
        """Download a track into the cache in the background (deduplicated)."""
        if not self._db or cache_key in self._inflight:
            return
        task = asyncio.create_task(self._download(cache_key, url, title, duration, thumbnail))
        self._inflight[cache_key] = task
        task.add_done_callback(lambda _: self._inflight.pop(cache_key, None))

    async def _download(self, cache_key: str, url: str, title: str, duration: int, thumbnail: str):
        async with self._download_slots:
            async with self._db.execute("SELECT 1 FROM cache_entries WHERE cache_key = ?", (cache_key,)) as cursor:
                if await cursor.fetchone():
                    return
            # Rough estimate: ~160kbps Opus = 20KB/s
            await self._evict_lru(duration * 20 * 1024)

            # A separate yt-dlp process: never touches the bot's GIL and can be killed cleanly
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "yt_dlp", url,
                "-f", AUDIO_FORMAT, "--no-playlist", "--no-part", "--no-mtime", "--quiet", "--no-warnings",
                "-o", os.path.join(self.cache_dir, f"{cache_key}.%(ext)s"),
                "--print", "after_move:filepath", "--print", "after_move:acodec", "--no-simulate",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_DOWNLOAD_TIMEOUT)
            except (asyncio.TimeoutError, asyncio.CancelledError) as e:
                proc.kill()
                await proc.wait()
                self._remove_partial(cache_key)
                if isinstance(e, asyncio.CancelledError):
                    raise
                log.warning("Cache download timed out for %s", cache_key)
                return
            if proc.returncode != 0:
                log.warning("Cache download failed for %s: %s", cache_key, stderr.decode(errors="replace").strip())
                self._remove_partial(cache_key)
                return

            lines = stdout.decode(errors="replace").strip().splitlines()
            file_path = lines[0] if lines else ""
            acodec = lines[1] if len(lines) > 1 else ""
            if not os.path.isfile(file_path):
                log.warning("Cache download for %s produced no file", cache_key)
                return

            size = os.path.getsize(file_path)
            now = time.time()
            await self._db.execute(
                "INSERT OR REPLACE INTO cache_entries "
                "(cache_key, file_path, size_bytes, last_accessed, created_at, title, duration, thumbnail, acodec) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (cache_key, file_path, size, now, now, title, duration, thumbnail, acodec),
            )
            await self._db.commit()
            log.info("Cached %s (%.1f MB): %s", cache_key, size / (1024 * 1024), title)

    def _remove_partial(self, cache_key: str):
        for f in os.listdir(self.cache_dir):
            if f.startswith(f"{cache_key}."):
                try:
                    os.remove(os.path.join(self.cache_dir, f))
                except OSError:
                    pass

    async def _evict_lru(self, needed_bytes: int):
        async with self._db.execute("SELECT COALESCE(SUM(size_bytes), 0) FROM cache_entries") as cursor:
            current_size = (await cursor.fetchone())[0]
        if current_size + needed_bytes <= self.max_size_bytes:
            return
        async with self._db.execute(
            "SELECT cache_key, file_path, size_bytes FROM cache_entries ORDER BY last_accessed ASC"
        ) as cursor:
            rows = await cursor.fetchall()
        for key, path, size in rows:
            if current_size + needed_bytes <= self.max_size_bytes:
                break
            try:
                os.remove(path)
            except OSError:
                pass
            await self._db.execute("DELETE FROM cache_entries WHERE cache_key = ?", (key,))
            current_size -= size
            log.info("Evicted %s (%.1f MB) to free space", key, size / (1024 * 1024))
        await self._db.commit()

    async def _cleanup(self):
        """Drop records whose files are missing and files with no record (e.g. interrupted downloads)."""
        async with self._db.execute("SELECT cache_key, file_path FROM cache_entries") as cursor:
            rows = await cursor.fetchall()
        known = set()
        for key, path in rows:
            if os.path.isfile(path):
                known.add(os.path.normcase(os.path.abspath(path)))
            else:
                await self._db.execute("DELETE FROM cache_entries WHERE cache_key = ?", (key,))
        await self._db.commit()

        for f in os.listdir(self.cache_dir):
            full = os.path.join(self.cache_dir, f)
            # Never touch databases: settings.db lives in this directory too
            if f.endswith(_DB_SUFFIXES) or not os.path.isfile(full):
                continue
            if os.path.normcase(os.path.abspath(full)) not in known:
                try:
                    os.remove(full)
                except OSError:
                    pass

    async def get_stats(self) -> dict:
        count, total = 0, 0
        if self._db:
            async with self._db.execute("SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM cache_entries") as cursor:
                count, total = await cursor.fetchone()
        return {
            "count": count,
            "total_size_mb": round(total / (1024 * 1024), 1),
            "max_size_mb": round(self.max_size_bytes / (1024 * 1024)),
            "hits": self.hits,
            "misses": self.misses,
        }

    async def clear_all(self):
        if not self._db:
            return
        async with self._db.execute("SELECT file_path FROM cache_entries") as cursor:
            rows = await cursor.fetchall()
        for (path,) in rows:
            try:
                os.remove(path)
            except OSError:
                pass
        await self._db.execute("DELETE FROM cache_entries")
        await self._db.commit()
        self.hits = 0
        self.misses = 0
