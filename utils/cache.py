import asyncio
import hashlib
import logging
import os
import re
import time

import aiosqlite
import yt_dlp

log = logging.getLogger("bot.cache")

YOUTUBE_ID_RE = re.compile(
    r"(?:youtube\.com/watch\?.*v=|youtu\.be/|youtube\.com/embed/|youtube\.com/shorts/)([A-Za-z0-9_-]{11})"
)

YTDL_DOWNLOAD_OPTIONS = {
    "format": "bestaudio[acodec=opus]/bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
}


class CacheManager:
    def __init__(
        self,
        cache_dir: str = "./cache",
        max_size_mb: int = 2048,
        max_duration_sec: int = 1800,
    ):
        self.cache_dir = os.environ.get("CACHE_DIR", cache_dir)
        self.max_size_bytes = int(os.environ.get("CACHE_LIMIT_MB", max_size_mb)) * 1024 * 1024
        self.max_duration_sec = int(os.environ.get("MAX_CACHE_DURATION", max_duration_sec))
        self.db_path = os.path.join(self.cache_dir, "cache.db")
        self._db: aiosqlite.Connection | None = None
        self._key_locks: dict[str, asyncio.Lock] = {}
        self._locks_lock = asyncio.Lock()
        self.hits = 0
        self.misses = 0

    async def initialize(self):
        os.makedirs(self.cache_dir, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS cache_entries (
                cache_key TEXT PRIMARY KEY,
                file_path TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                last_accessed REAL NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        await self._db.commit()
        await self._cleanup()

    async def close(self):
        if self._db:
            await self._db.close()
            self._db = None

    async def _get_lock(self, key: str) -> asyncio.Lock:
        async with self._locks_lock:
            if key not in self._key_locks:
                self._key_locks[key] = asyncio.Lock()
            return self._key_locks[key]

    @staticmethod
    def extract_cache_key(url: str) -> str:
        m = YOUTUBE_ID_RE.search(url)
        if m:
            return m.group(1)
        return hashlib.sha256(url.encode()).hexdigest()[:16]

    async def get_cached_path(self, cache_key: str) -> str | None:
        if not self._db:
            return None
        async with self._db.execute(
            "SELECT file_path FROM cache_entries WHERE cache_key = ?", (cache_key,)
        ) as cursor:
            row = await cursor.fetchone()
        if row and os.path.isfile(row[0]):
            await self._db.execute(
                "UPDATE cache_entries SET last_accessed = ? WHERE cache_key = ?",
                (time.time(), cache_key),
            )
            await self._db.commit()
            self.hits += 1
            log.debug("Cache hit: %s -> %s", cache_key, row[0])
            return row[0]
        # DB record exists but file is gone — clean up
        if row:
            await self._db.execute("DELETE FROM cache_entries WHERE cache_key = ?", (cache_key,))
            await self._db.commit()
        self.misses += 1
        return None

    async def download_and_cache(
        self, cache_key: str, url: str, duration: int | None, is_live: bool
    ) -> str | None:
        if is_live or (duration is not None and duration == 0):
            return None
        if duration is not None and duration > self.max_duration_sec:
            return None

        lock = await self._get_lock(cache_key)
        async with lock:
            # Check again in case another coroutine just finished downloading
            existing = await self.get_cached_path(cache_key)
            if existing:
                return existing

            # Estimate size needed and evict if necessary
            # Rough estimate: 128kbps * duration = 16KB/s
            estimated_bytes = (duration or 300) * 16 * 1024
            await self._evict_lru(estimated_bytes)

            outtmpl = os.path.join(self.cache_dir, f"{cache_key}.%(ext)s")
            opts = {**YTDL_DOWNLOAD_OPTIONS, "outtmpl": outtmpl}

            loop = asyncio.get_event_loop()
            try:
                info = await loop.run_in_executor(None, self._download_sync, opts, url)
            except Exception as e:
                log.error("Download failed for %s: %s", cache_key, e)
                return None

            if not info:
                return None

            # Find the downloaded file
            ext = info.get("ext", "opus")
            file_path = os.path.join(self.cache_dir, f"{cache_key}.{ext}")
            if not os.path.isfile(file_path):
                # yt-dlp may have used a different extension, scan for it
                for f in os.listdir(self.cache_dir):
                    if f.startswith(f"{cache_key}.") and f != "cache.db":
                        file_path = os.path.join(self.cache_dir, f)
                        break
                else:
                    return None

            size_bytes = os.path.getsize(file_path)
            now = time.time()
            await self._db.execute(
                "INSERT OR REPLACE INTO cache_entries (cache_key, file_path, size_bytes, last_accessed, created_at) VALUES (?, ?, ?, ?, ?)",
                (cache_key, file_path, size_bytes, now, now),
            )
            await self._db.commit()
            log.info("Cached %s (%.1f MB) -> %s", cache_key, size_bytes / (1024 * 1024), file_path)
            return file_path

    @staticmethod
    def _download_sync(opts: dict, url: str) -> dict | None:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=True)

    async def _evict_lru(self, needed_bytes: int):
        if not self._db:
            return
        async with self._db.execute("SELECT COALESCE(SUM(size_bytes), 0) FROM cache_entries") as cursor:
            row = await cursor.fetchone()
            current_size = row[0]

        while current_size + needed_bytes > self.max_size_bytes:
            async with self._db.execute(
                "SELECT cache_key, file_path, size_bytes FROM cache_entries ORDER BY last_accessed ASC LIMIT 1"
            ) as cursor:
                oldest = await cursor.fetchone()
            if not oldest:
                break
            key, path, size = oldest
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except OSError:
                pass
            await self._db.execute("DELETE FROM cache_entries WHERE cache_key = ?", (key,))
            await self._db.commit()
            current_size -= size
            log.info("Evicted %s (%.1f MB) to free space", key, size / (1024 * 1024))

    async def _cleanup(self):
        if not self._db:
            return
        # Remove DB records whose files are missing
        async with self._db.execute("SELECT cache_key, file_path FROM cache_entries") as cursor:
            rows = await cursor.fetchall()
        for key, path in rows:
            if not os.path.isfile(path):
                await self._db.execute("DELETE FROM cache_entries WHERE cache_key = ?", (key,))

        # Remove orphan files (no DB record)
        db_files = {path for _, path in rows}
        if os.path.isdir(self.cache_dir):
            for f in os.listdir(self.cache_dir):
                full = os.path.join(self.cache_dir, f)
                if full not in db_files and f not in ("cache.db", "cache.db-journal", "cache.db-wal"):
                    try:
                        os.remove(full)
                    except OSError:
                        pass
        await self._db.commit()

    async def get_stats(self) -> dict:
        if not self._db:
            return {"count": 0, "total_size_mb": 0, "hits": self.hits, "misses": self.misses}
        async with self._db.execute("SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM cache_entries") as cursor:
            row = await cursor.fetchone()
        return {
            "count": row[0],
            "total_size_mb": round(row[1] / (1024 * 1024), 1),
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
                if os.path.isfile(path):
                    os.remove(path)
            except OSError:
                pass
        await self._db.execute("DELETE FROM cache_entries")
        await self._db.commit()
        self.hits = 0
        self.misses = 0
