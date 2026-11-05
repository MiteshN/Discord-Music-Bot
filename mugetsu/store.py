"""The bot's own data: play history, saved playlists, resumable sessions and game scores.

One SQLite file next to the audio cache (so it lives in the same Docker volume).
"""

from __future__ import annotations

import json
import os
import secrets
import time
from dataclasses import dataclass, field

import aiosqlite

SCHEMA_VERSION = 1
MAX_PLAYLISTS = 50
MAX_PLAYLIST_TRACKS = 1000
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I lookalikes

_SCHEMA = """
CREATE TABLE IF NOT EXISTS plays (
    id INTEGER PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    started_at REAL NOT NULL,
    seconds REAL NOT NULL DEFAULT 0,
    title TEXT NOT NULL,
    artist TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    thumbnail TEXT NOT NULL DEFAULT '',
    duration INTEGER NOT NULL DEFAULT 0,
    record TEXT NOT NULL,
    requester_id INTEGER NOT NULL DEFAULT 0,
    requester_name TEXT NOT NULL DEFAULT '',
    requester_avatar TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS plays_guild_time ON plays (guild_id, started_at);
CREATE INDEX IF NOT EXISTS plays_requester ON plays (guild_id, requester_id, started_at);

CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY,
    owner_id INTEGER NOT NULL,
    name TEXT NOT NULL COLLATE NOCASE,
    share_code TEXT UNIQUE,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE (owner_id, name)
);
CREATE TABLE IF NOT EXISTS playlist_tracks (
    playlist_id INTEGER NOT NULL REFERENCES playlists (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    record TEXT NOT NULL,
    PRIMARY KEY (playlist_id, position)
);

CREATE TABLE IF NOT EXISTS sessions (
    guild_id INTEGER PRIMARY KEY,
    saved_at REAL NOT NULL,
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS game_scores (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    points INTEGER NOT NULL DEFAULT 0,
    games INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);
"""


@dataclass
class Playlist:
    id: int
    owner_id: int
    name: str
    share_code: str | None
    tracks: list[dict] = field(default_factory=list)

    @property
    def duration(self) -> int:
        return sum(int(t.get("duration") or 0) for t in self.tracks)


class Store:
    def __init__(self, data_dir: str | os.PathLike = "cache"):
        self.path = os.path.join(os.fspath(data_dir), "mugetsu.db")
        self._db: aiosqlite.Connection | None = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Store is not open")
        return self._db

    async def initialize(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.executescript(_SCHEMA)
        await self._db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        await self._db.commit()

    async def close(self):
        if self._db:
            await self._db.close()
            self._db = None

    # --- Play history ---

    async def log_play(self, guild_id: int, record: dict) -> int:
        cursor = await self.db.execute(
            "INSERT INTO plays (guild_id, started_at, title, artist, url, thumbnail, duration, record, "
            "requester_id, requester_name, requester_avatar) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                guild_id, time.time(), record.get("title", ""), record.get("artist", ""),
                record.get("url") or record.get("origin_url") or "", record.get("thumbnail", ""),
                int(record.get("duration") or 0), json.dumps(record), int(record.get("requester_id") or 0),
                record.get("requester", ""), record.get("requester_avatar", ""),
            ),
        )
        await self.db.commit()
        return cursor.lastrowid

    async def finish_play(self, play_id: int, seconds: float):
        await self.db.execute("UPDATE plays SET seconds = ? WHERE id = ?", (max(0.0, seconds), play_id))
        await self.db.commit()

    async def stats(self, guild_id: int, since: float | None = None, limit: int = 10) -> dict:
        where, args = "guild_id = ?", [guild_id]
        if since is not None:
            where += " AND started_at >= ?"
            args.append(since)
        async with self.db.execute(
            f"SELECT COUNT(*), COALESCE(SUM(seconds), 0), COUNT(DISTINCT requester_id), MIN(started_at) "
            f"FROM plays WHERE {where}", args,
        ) as cur:
            plays, seconds, listeners, first = await cur.fetchone()
        # A song counts once per play; group on url when known, else on the title
        async with self.db.execute(
            f"SELECT title, artist, url, thumbnail, COUNT(*) AS n, SUM(seconds) FROM plays WHERE {where} "
            f"GROUP BY CASE WHEN url != '' THEN url ELSE lower(title) END ORDER BY n DESC, MAX(started_at) DESC "
            f"LIMIT ?", [*args, limit],
        ) as cur:
            songs = [
                {"title": t, "artist": a, "url": u, "thumbnail": th, "plays": n, "seconds": round(s or 0)}
                for t, a, u, th, n, s in await cur.fetchall()
            ]
        async with self.db.execute(
            f"SELECT requester_id, requester_name, requester_avatar, COUNT(*) AS n, SUM(seconds) FROM plays "
            f"WHERE {where} AND requester_id != 0 GROUP BY requester_id ORDER BY n DESC LIMIT ?", [*args, limit],
        ) as cur:
            people = [
                {"id": str(i), "name": name, "avatar": av, "plays": n, "seconds": round(s or 0)}
                for i, name, av, n, s in await cur.fetchall()
            ]
        async with self.db.execute(
            f"SELECT artist, COUNT(*) AS n FROM plays WHERE {where} AND artist != '' "
            f"GROUP BY lower(artist) ORDER BY n DESC LIMIT ?", [*args, limit],
        ) as cur:
            artists = [{"name": a, "plays": n} for a, n in await cur.fetchall()]
        return {
            "plays": plays, "seconds": round(seconds), "requesters": listeners, "since": first,
            "top_songs": songs, "top_requesters": people, "top_artists": artists,
        }

    async def recent_requests(self, guild_id: int, user_id: int, limit: int = 20) -> list[dict]:
        """A member's most recently requested songs, newest first, without repeats."""
        async with self.db.execute(
            "SELECT record, url, title FROM plays WHERE guild_id = ? AND requester_id = ? "
            "ORDER BY started_at DESC LIMIT 500", (guild_id, user_id),
        ) as cur:
            rows = await cur.fetchall()
        seen, out = set(), []
        for record, url, title in rows:
            key = url or title.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(json.loads(record))
            if len(out) >= limit:
                break
        return out

    # --- Saved playlists (owned by a person, usable in any server) ---

    async def playlists(self, owner_id: int) -> list[Playlist]:
        async with self.db.execute(
            "SELECT id, owner_id, name, share_code FROM playlists WHERE owner_id = ? ORDER BY updated_at DESC",
            (owner_id,),
        ) as cur:
            lists = [Playlist(*row) for row in await cur.fetchall()]
        for p in lists:
            p.tracks = await self._tracks(p.id)
        return lists

    async def _tracks(self, playlist_id: int) -> list[dict]:
        async with self.db.execute(
            "SELECT record FROM playlist_tracks WHERE playlist_id = ? ORDER BY position", (playlist_id,)
        ) as cur:
            return [json.loads(r) for (r,) in await cur.fetchall()]

    async def playlist(self, owner_id: int, name: str) -> Playlist | None:
        async with self.db.execute(
            "SELECT id, owner_id, name, share_code FROM playlists WHERE owner_id = ? AND name = ?",
            (owner_id, name.strip()),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        p = Playlist(*row)
        p.tracks = await self._tracks(p.id)
        return p

    async def playlist_by_code(self, code: str) -> Playlist | None:
        async with self.db.execute(
            "SELECT id, owner_id, name, share_code FROM playlists WHERE share_code = ?", (code.strip().upper(),)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        p = Playlist(*row)
        p.tracks = await self._tracks(p.id)
        return p

    async def _get_or_create(self, owner_id: int, name: str) -> int:
        name = name.strip()[:100]
        async with self.db.execute(
            "SELECT id FROM playlists WHERE owner_id = ? AND name = ?", (owner_id, name)
        ) as cur:
            row = await cur.fetchone()
        if row:
            return row[0]
        async with self.db.execute("SELECT COUNT(*) FROM playlists WHERE owner_id = ?", (owner_id,)) as cur:
            if (await cur.fetchone())[0] >= MAX_PLAYLISTS:
                raise ValueError(f"You can have up to {MAX_PLAYLISTS} playlists.")
        now = time.time()
        cursor = await self.db.execute(
            "INSERT INTO playlists (owner_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (owner_id, name, now, now),
        )
        return cursor.lastrowid

    async def save_playlist(self, owner_id: int, name: str, records: list[dict]) -> int:
        """Create or overwrite a playlist with these tracks. Returns how many were saved."""
        records = records[:MAX_PLAYLIST_TRACKS]
        pid = await self._get_or_create(owner_id, name)
        await self.db.execute("DELETE FROM playlist_tracks WHERE playlist_id = ?", (pid,))
        await self.db.executemany(
            "INSERT INTO playlist_tracks (playlist_id, position, record) VALUES (?, ?, ?)",
            [(pid, i, json.dumps(r)) for i, r in enumerate(records)],
        )
        await self._touch(pid)
        return len(records)

    async def add_tracks(self, owner_id: int, name: str, records: list[dict]) -> int:
        """Append tracks (creating the playlist if needed). Returns the new track count."""
        pid = await self._get_or_create(owner_id, name)
        async with self.db.execute(
            "SELECT COUNT(*), COALESCE(MAX(position), -1) FROM playlist_tracks WHERE playlist_id = ?", (pid,)
        ) as cur:
            count, last = await cur.fetchone()
        room = MAX_PLAYLIST_TRACKS - count
        if room <= 0:
            raise ValueError(f"A playlist can hold up to {MAX_PLAYLIST_TRACKS} tracks.")
        records = records[:room]
        await self.db.executemany(
            "INSERT INTO playlist_tracks (playlist_id, position, record) VALUES (?, ?, ?)",
            [(pid, last + 1 + i, json.dumps(r)) for i, r in enumerate(records)],
        )
        await self._touch(pid)
        return count + len(records)

    async def remove_track(self, owner_id: int, name: str, index: int) -> dict | None:
        p = await self.playlist(owner_id, name)
        if p is None or not 0 <= index < len(p.tracks):
            return None
        removed = p.tracks.pop(index)
        await self.save_playlist(owner_id, p.name, p.tracks)
        return removed

    async def delete_playlist(self, owner_id: int, name: str) -> bool:
        cursor = await self.db.execute("DELETE FROM playlists WHERE owner_id = ? AND name = ?", (owner_id, name.strip()))
        await self.db.commit()
        return cursor.rowcount > 0

    async def rename_playlist(self, owner_id: int, old: str, new: str) -> bool:
        new = new.strip()[:100]
        if not new:
            raise ValueError("Give the playlist a name.")
        if await self.playlist(owner_id, new):
            raise ValueError(f"You already have a playlist called “{new}”.")
        cursor = await self.db.execute(
            "UPDATE playlists SET name = ?, updated_at = ? WHERE owner_id = ? AND name = ?",
            (new, time.time(), owner_id, old.strip()),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def share_code(self, owner_id: int, name: str) -> str | None:
        p = await self.playlist(owner_id, name)
        if p is None:
            return None
        if p.share_code:
            return p.share_code
        while True:
            code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
            try:
                await self.db.execute("UPDATE playlists SET share_code = ? WHERE id = ?", (code, p.id))
                await self.db.commit()
                return code
            except aiosqlite.IntegrityError:
                continue  # astronomically unlikely clash: try another

    async def _touch(self, playlist_id: int):
        await self.db.execute("UPDATE playlists SET updated_at = ? WHERE id = ?", (time.time(), playlist_id))
        await self.db.commit()

    # --- Sessions to resume after a restart ---

    async def save_session(self, guild_id: int, data: dict):
        await self.db.execute(
            "INSERT OR REPLACE INTO sessions (guild_id, saved_at, data) VALUES (?, ?, ?)",
            (guild_id, time.time(), json.dumps(data)),
        )
        await self.db.commit()

    async def clear_session(self, guild_id: int):
        await self.db.execute("DELETE FROM sessions WHERE guild_id = ?", (guild_id,))
        await self.db.commit()

    async def sessions(self, max_age: float) -> list[tuple[int, dict]]:
        """Saved sessions young enough to resume. Older ones are dropped."""
        cutoff = time.time() - max_age
        await self.db.execute("DELETE FROM sessions WHERE saved_at < ?", (cutoff,))
        await self.db.commit()
        async with self.db.execute("SELECT guild_id, data FROM sessions") as cur:
            return [(gid, json.loads(data)) for gid, data in await cur.fetchall()]

    # --- Guess the song ---

    async def add_game_result(self, guild_id: int, scores: dict[int, tuple[str, int]], winner_id: int | None):
        for user_id, (name, points) in scores.items():
            await self.db.execute(
                "INSERT INTO game_scores (guild_id, user_id, name, points, games, wins) VALUES (?, ?, ?, ?, 1, ?) "
                "ON CONFLICT (guild_id, user_id) DO UPDATE SET name = excluded.name, "
                "points = points + excluded.points, games = games + 1, wins = wins + excluded.wins",
                (guild_id, user_id, name, points, int(user_id == winner_id)),
            )
        await self.db.commit()

    async def game_leaderboard(self, guild_id: int, limit: int = 10) -> list[dict]:
        async with self.db.execute(
            "SELECT user_id, name, points, games, wins FROM game_scores WHERE guild_id = ? "
            "ORDER BY points DESC, wins DESC LIMIT ?", (guild_id, limit),
        ) as cur:
            return [
                {"id": str(u), "name": n, "points": p, "games": g, "wins": w}
                for u, n, p, g, w in await cur.fetchall()
            ]
