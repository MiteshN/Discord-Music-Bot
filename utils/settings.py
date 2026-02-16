import os

import aiosqlite


class GuildSettings:
    def __init__(self, cache_dir: str = "./cache"):
        self.cache_dir = os.environ.get("CACHE_DIR", cache_dir)
        self.db_path = os.path.join(self.cache_dir, "settings.db")
        self._db: aiosqlite.Connection | None = None

    async def initialize(self):
        os.makedirs(self.cache_dir, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER PRIMARY KEY,
                volume REAL DEFAULT 0.5,
                twenty_four_seven BOOLEAN DEFAULT 0
            )
        """)
        await self._db.commit()

    async def close(self):
        if self._db:
            await self._db.close()
            self._db = None

    async def load(self, guild_id: int) -> dict | None:
        if not self._db:
            return None
        async with self._db.execute(
            "SELECT volume, twenty_four_seven FROM guild_settings WHERE guild_id = ?",
            (guild_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row:
            return {"volume": row[0], "twenty_four_seven": bool(row[1])}
        return None

    async def save(self, guild_id: int, volume: float, twenty_four_seven: bool):
        if not self._db:
            return
        await self._db.execute(
            "INSERT OR REPLACE INTO guild_settings (guild_id, volume, twenty_four_seven) VALUES (?, ?, ?)",
            (guild_id, volume, int(twenty_four_seven)),
        )
        await self._db.commit()
