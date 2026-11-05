"""Per-guild persistent settings, held in memory and written through to SQLite."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, replace

import aiosqlite

DEFAULT_VOLUME = 1.0  # 100% lets Opus pass through untouched (best quality)


@dataclass(frozen=True)
class SavedSettings:
    volume: float = DEFAULT_VOLUME
    twenty_four_seven: bool = False
    autoplay: bool = False


# Columns added after the table first shipped, migrated in place: name -> SQL declaration
_ADDED_COLUMNS = {"autoplay": "BOOLEAN DEFAULT 0"}


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
        async with self._db.execute("PRAGMA table_info(guild_settings)") as cursor:
            columns = {row[1] for row in await cursor.fetchall()}
        for name, decl in _ADDED_COLUMNS.items():
            if name not in columns:
                await self._db.execute(f"ALTER TABLE guild_settings ADD COLUMN {name} {decl}")
        await self._db.commit()
        async with self._db.execute("SELECT guild_id, volume, twenty_four_seven, autoplay FROM guild_settings") as cur:
            for guild_id, volume, tfs, autoplay in await cur.fetchall():
                self._cache[guild_id] = SavedSettings(volume, bool(tfs), bool(autoplay))

    async def close(self):
        if self._db:
            await self._db.close()
            self._db = None

    def get(self, guild_id: int) -> SavedSettings:
        return self._cache.get(guild_id, SavedSettings())

    async def save(self, guild_id: int, **changes):
        """Update some settings (volume=, twenty_four_seven=, autoplay=) and keep the rest."""
        saved = replace(self.get(guild_id), **changes)
        self._cache[guild_id] = saved
        if not self._db:
            return
        values = asdict(saved)
        await self._db.execute(
            "INSERT OR REPLACE INTO guild_settings (guild_id, volume, twenty_four_seven, autoplay) VALUES (?, ?, ?, ?)",
            (guild_id, values["volume"], int(values["twenty_four_seven"]), int(values["autoplay"])),
        )
        await self._db.commit()
