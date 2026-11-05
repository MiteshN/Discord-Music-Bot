"""What the dashboard talks to. BotBackend is the real bot; mugetsu.web.demo has a stand-in for UI work."""

from __future__ import annotations

import random
import re
import time
from typing import TYPE_CHECKING, Protocol

import discord

from mugetsu.media.ffmpeg import effect_catalog
from mugetsu.player.events import EventBus
from mugetsu.player.manager import Requester
from mugetsu.player.models import PlayerError, Song
from mugetsu.ui.views import send_song_dm
from mugetsu.util import plain

if TYPE_CHECKING:
    from mugetsu.bot import MugetsuBot

MEMBER_TTL = 300
_CHANNEL_MENTION = re.compile(r"<#(\d+)>")


class Forbidden(Exception):
    pass


class Backend(Protocol):
    events: EventBus

    @property
    def ready(self) -> bool: ...
    def info(self) -> dict: ...
    def guilds_for(self, guild_ids: set[str]) -> list[dict]: ...
    async def can_view(self, guild_id: int, user_id: int) -> bool: ...
    def state(self, guild_id: int) -> dict: ...
    async def act(self, guild_id: int, user_id: int, action: str, args: dict) -> str: ...
    async def search(self, guild_id: int, query: str) -> dict: ...
    async def lyrics(self, guild_id: int) -> dict | None: ...
    async def stats(self, guild_id: int, period: str) -> dict: ...
    async def playlists(self, user_id: int) -> list[dict]: ...
    async def playlist_action(self, user_id: int, action: str, args: dict) -> str: ...


ACTIONS = frozenset({
    "pause", "skip", "previous", "stop", "seek", "volume", "loop", "effect",
    "shuffle", "clear", "remove", "move", "skipto", "add", "247",
    "autoplay", "removedupes", "removeabsent", "removeuser", "save", "playrecent",
    "savequeue", "savecurrent", "loadplaylist",
})
PLAYLIST_ACTIONS = frozenset({"delete", "rename", "share", "copy", "removetrack"})


def playlist_dict(p) -> dict:
    return {
        "name": p.name,
        "share_code": p.share_code,
        "count": len(p.tracks),
        "duration": p.duration,
        "tracks": [
            {"title": t.get("title", ""), "artist": t.get("artist", ""), "duration": int(t.get("duration") or 0),
             "thumbnail": t.get("thumbnail", ""), "url": t.get("url") or t.get("origin_url") or ""}
            for t in p.tracks
        ],
    }


class BotBackend:
    def __init__(self, bot: MugetsuBot):
        self.bot = bot
        self.players = bot.players
        self.events = bot.players.events
        self._members: dict[tuple[int, int], tuple[float, discord.Member | None]] = {}

    @property
    def ready(self) -> bool:
        return self.bot.is_ready()

    def info(self) -> dict:
        me = self.bot.user
        return {
            "name": me.display_name if me else "Mugetsu",
            "avatar": me.display_avatar.with_size(128).url if me else "",
            "effects": effect_catalog(),
            "spotify": self.players.spotify.enabled,
            "dj_role": self.bot.config.dj_role,
        }

    def guilds_for(self, guild_ids: set[str]) -> list[dict]:
        result = []
        for guild in self.bot.guilds:
            if str(guild.id) not in guild_ids:
                continue
            player = self.players.peek(guild.id)
            result.append({
                "id": str(guild.id),
                "name": guild.name,
                "icon": guild.icon.with_size(128).url if guild.icon else None,
                "playing": bool(player and player.current and player.is_connected),
            })
        return sorted(result, key=lambda g: g["name"].lower())

    async def member(self, guild_id: int, user_id: int) -> discord.Member | None:
        """The user as a member of the guild, or None if they aren't in it (anymore)."""
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return None
        member = guild.get_member(user_id)  # cached for anyone in a voice channel
        if member is not None:
            return member
        key = (guild_id, user_id)
        cached = self._members.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        try:
            member = await guild.fetch_member(user_id)
        except discord.NotFound:
            member = None
        except discord.HTTPException:
            return cached[1] if cached else None
        self._members[key] = (time.monotonic() + MEMBER_TTL, member)
        if len(self._members) > 5000:
            self._members.clear()
        return member

    async def can_view(self, guild_id: int, user_id: int) -> bool:
        return await self.member(guild_id, user_id) is not None

    def state(self, guild_id: int) -> dict:
        return self.players.snapshot(guild_id)

    def _clean(self, guild: discord.Guild, message: str) -> str:
        def channel_name(m: re.Match) -> str:
            channel = guild.get_channel(int(m.group(1)))
            return f"#{channel.name}" if channel else "the voice channel"

        return plain(_CHANNEL_MENTION.sub(channel_name, message))

    async def act(self, guild_id: int, user_id: int, action: str, args: dict) -> str:
        if action not in ACTIONS:
            raise KeyError(action)
        member = await self.member(guild_id, user_id)
        if member is None:
            raise Forbidden("You aren't a member of that server.")
        guild = member.guild
        try:
            return self._clean(guild, await self._dispatch(guild, member, action, args))
        except PlayerError as e:
            raise PlayerError(self._clean(guild, str(e))) from None

    async def _dispatch(self, guild: discord.Guild, member: discord.Member, action: str, args: dict) -> str:
        player = self.players.get(guild.id)

        def index(song_id) -> int:
            i = player.q.index_of(int(song_id))
            if i < 0:
                raise PlayerError("That song isn't in the queue anymore.")
            return i

        match action:
            case "pause":
                return await player.toggle_pause(member)
            case "skip":
                return await player.skip(member)
            case "previous":
                return await player.previous(member)
            case "stop":
                return await player.stop(member)
            case "seek":
                return await player.seek(float(args["position"]), member)
            case "volume":
                return await player.set_volume(int(args["volume"]), member)
            case "loop":
                return await player.set_loop(args.get("mode"), member)
            case "effect":
                return await player.set_filter(str(args.get("key", "")), member)
            case "shuffle":
                return await player.shuffle(member)
            case "clear":
                return await player.clear(member)
            case "remove":
                return await player.remove(index(args["id"]), member)
            case "move":
                return await player.move(index(args["id"]), int(args["to"]), member)
            case "skipto":
                return await player.skip_to(index(args["id"]), member)
            case "247":
                return await player.set_247(bool(args["enabled"]), member)
            case "add":
                return await self._add(guild, member, str(args.get("query", "")), top=bool(args.get("top")))
            case "autoplay":
                return await player.set_autoplay(bool(args["enabled"]), member)
            case "removedupes":
                return await player.remove_duplicates(member)
            case "removeabsent":
                return await player.remove_absent(member)
            case "removeuser":
                user_id = int(args["user_id"])
                target = guild.get_member(user_id)
                name = target.display_name if target else str(args.get("name") or "That person")
                return await player.remove_requester(user_id, name, member)
            case "save":
                if player.game is not None:
                    raise PlayerError("No peeking during guess the song! 🙈")
                return await send_song_dm(member, player.current, guild.name)
            case "playrecent":
                songs = await self.players.recent_songs(guild.id, member, int(args.get("count", 10)))
                if not songs:
                    raise PlayerError("You haven't requested anything here yet.")
                return await self._enqueue(guild, member, songs, "your recent songs")
            case "savequeue" | "savecurrent":
                if player.game is not None:
                    raise PlayerError("No saving the answers during guess the song! 🙈")
                name = str(args.get("name", "")).strip()
                if not name:
                    raise PlayerError("Give the playlist a name.")
                if action == "savecurrent":
                    if player.current is None:
                        raise PlayerError("Nothing is playing.")
                    count = await self._store_call(self.players.store.add_tracks, member.id, name,
                                                   [player.current.to_record()])
                    return f"Added {player.current.title} to {name} ({count} songs)"
                songs = ([player.current] if player.current else []) + list(player.q.queue)
                if not songs:
                    raise PlayerError("There's nothing playing or queued to save.")
                count = await self._store_call(self.players.store.save_playlist, member.id, name,
                                               [s.to_record() for s in songs])
                return f"Saved {count} songs to {name}"
            case "loadplaylist":
                name = str(args.get("name", "")).strip()
                store = self.players.store
                playlist = await store.playlist(member.id, name) or await store.playlist_by_code(name)
                if playlist is None or not playlist.tracks:
                    raise PlayerError("That playlist doesn't exist or is empty.")
                who = Requester.of(member).fields()
                songs = [Song.from_record(t, who) for t in playlist.tracks]
                if args.get("shuffle"):
                    random.shuffle(songs)
                return await self._enqueue(guild, member, songs, playlist.name)
        raise KeyError(action)

    @staticmethod
    async def _store_call(fn, *args):
        try:
            return await fn(*args)
        except ValueError as e:
            raise PlayerError(str(e)) from None

    async def _join_or_require_voice(self, guild: discord.Guild, member: discord.Member):
        in_voice = guild.get_member(member.id)  # only voice-cached members carry their voice state
        if in_voice and in_voice.voice:
            await self.players.join(in_voice)
        elif not guild.voice_client:
            raise PlayerError("Join a voice channel in this server first, then try again.")

    async def _enqueue(self, guild: discord.Guild, member: discord.Member, songs: list[Song], label: str) -> str:
        await self._join_or_require_voice(guild, member)
        started = await self.players.get(guild.id).enqueue(songs, actor=member)
        if started and len(songs) == 1:
            return f"Now playing {songs[0].title}"
        return f"Added {len(songs)} songs from {label}"

    async def _add(self, guild: discord.Guild, member: discord.Member, query: str, *, top: bool) -> str:
        if not query.strip():
            raise PlayerError("Type something to play.")
        await self._join_or_require_voice(guild, member)
        songs, label = await self.players.resolve_query(query, Requester.of(member))
        player = self.players.get(guild.id)
        started = await player.enqueue(songs, top=top, actor=member)
        if started and len(songs) == 1:
            return f"Now playing {songs[0].title}"
        if len(songs) > 1:
            return f"Added {len(songs)} tracks" + (f" from {label}" if label else "")
        return f"Added {songs[0].title}" + (" to play next" if top else "")

    async def search(self, guild_id: int, query: str) -> dict:
        return await self.players.search(query)

    async def lyrics(self, guild_id: int) -> dict | None:
        player = self.players.peek(guild_id)
        song = player.current if player and player.game is None else None  # no peeking during a game
        if song is None:
            return None
        found = await self.players.lyrics_for(song)
        base = {"song_id": song.id, "title": song.title}
        if found is None:
            return {**base, "plain": "", "synced": [], "source": ""}
        return {**base, **found.to_dict()}

    async def stats(self, guild_id: int, period: str) -> dict:
        return await self.players.stats(guild_id, period)

    async def playlists(self, user_id: int) -> list[dict]:
        return [playlist_dict(p) for p in await self.players.store.playlists(user_id)]

    async def playlist_action(self, user_id: int, action: str, args: dict) -> str:
        if action not in PLAYLIST_ACTIONS:
            raise KeyError(action)
        store = self.players.store
        name = str(args.get("name", "")).strip()
        match action:
            case "delete":
                if not await store.delete_playlist(user_id, name):
                    raise PlayerError("That playlist doesn't exist.")
                return f"Deleted {name}"
            case "rename":
                new_name = str(args.get("new_name", "")).strip()
                if not await self._store_call(store.rename_playlist, user_id, name, new_name):
                    raise PlayerError("That playlist doesn't exist.")
                return f"Renamed to {new_name}"
            case "share":
                code = await store.share_code(user_id, name)
                if code is None:
                    raise PlayerError("That playlist doesn't exist.")
                return code
            case "copy":
                shared = await store.playlist_by_code(str(args.get("code", "")))
                if shared is None:
                    raise PlayerError("No playlist has that share code.")
                new_name = name or shared.name
                if await store.playlist(user_id, new_name):
                    raise PlayerError(f"You already have a playlist called {new_name}.")
                count = await self._store_call(store.save_playlist, user_id, new_name, shared.tracks)
                return f"Copied {count} songs into {new_name}"
            case "removetrack":
                removed = await store.remove_track(user_id, name, int(args["index"]))
                if removed is None:
                    raise PlayerError("That song isn't in the playlist anymore.")
                return f"Removed {removed.get('title', 'the song')}"
        raise KeyError(action)
