import os

import aiosqlite

DEFAULT_VOLUME = 1.0  # 100% lets Opus pass through untouched (best quality)


class GuildSettings:
    """Per-guild persistent settings, held in memory and written through to SQLite."""

    def __init__(self, cache_dir: str = "./cache"):
        self.cache_dir = os.environ.get("CACHE_DIR", cache_dir)
        self.db_path = os.path.join(self.cache_dir, "settings.db")
        self._db: aiosqlite.Connection | None = None
        self._cache: dict[int, dict] = {}

    async def initialize(self):
        os.makedirs(self.cache_dir, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER PRIMARY KEY,
                volume REAL DEFAULT 1.0,
                twenty_four_seven BOOLEAN DEFAULT 0
            )
        """)
        await self._db.commit()
        async with self._db.execute("SELECT guild_id, volume, twenty_four_seven FROM guild_settings") as cursor:
            for guild_id, volume, tfs in await cursor.fetchall():
                self._cache[guild_id] = {"volume": volume, "twenty_four_seven": bool(tfs)}

    async def close(self):
        if self._db:
            await self._db.close()
            self._db = None

    def get(self, guild_id: int) -> dict:
        return self._cache.get(guild_id, {"volume": DEFAULT_VOLUME, "twenty_four_seven": False})

    async def save(self, guild_id: int, volume: float, twenty_four_seven: bool):
        self._cache[guild_id] = {"volume": volume, "twenty_four_seven": twenty_four_seven}
        if not self._db:
            return
        await self._db.execute(
            "INSERT OR REPLACE INTO guild_settings (guild_id, volume, twenty_four_seven) VALUES (?, ?, ?)",
            (guild_id, volume, int(twenty_four_seven)),
        )
        await self._db.commit()
