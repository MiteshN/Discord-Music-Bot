"""Per-guild persistent settings, held in memory and written through to SQLite."""

from __future__ import annotations

import os
from dataclasses import dataclass

import aiosqlite

DEFAULT_VOLUME = 1.0  # 100% lets Opus pass through untouched (best quality)


@dataclass
class SavedSettings:
    volume: float = DEFAULT_VOLUME
    twenty_four_seven: bool = False


class GuildSettings:
    def __init__(self, data_dir: str | os.PathLike = "cache"):
        self.data_dir = os.fspath(data_dir)
        self.db_path = os.path.join(self.data_dir, "settings.db")
        self._db: aiosqlite.Connection | None = None
        self._cache: dict[int, SavedSettings] = {}

    async def initialize(self):
        os.makedirs(self.data_dir, exist_ok=True)
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
                self._cache[guild_id] = SavedSettings(volume, bool(tfs))

    async def close(self):
        if self._db:
            await self._db.close()
            self._db = None

    def get(self, guild_id: int) -> SavedSettings:
        saved = self._cache.get(guild_id)
        return SavedSettings(saved.volume, saved.twenty_four_seven) if saved else SavedSettings()

    async def save(self, guild_id: int, *, volume: float, twenty_four_seven: bool):
        self._cache[guild_id] = SavedSettings(volume, twenty_four_seven)
        if not self._db:
            return
        await self._db.execute(
            "INSERT OR REPLACE INTO guild_settings (guild_id, volume, twenty_four_seven) VALUES (?, ?, ?)",
            (guild_id, volume, int(twenty_four_seven)),
        )
        await self._db.commit()
