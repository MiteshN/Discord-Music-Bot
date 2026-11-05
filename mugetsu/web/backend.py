"""What the dashboard talks to. BotBackend is the real bot; mugetsu.web.demo has a stand-in for UI work."""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING, Protocol

import discord

from mugetsu.media.ffmpeg import effect_catalog
from mugetsu.player.events import EventBus
from mugetsu.player.manager import Requester
from mugetsu.player.models import PlayerError
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


ACTIONS = frozenset({
    "pause", "skip", "previous", "stop", "seek", "volume", "loop", "effect",
    "shuffle", "clear", "remove", "move", "skipto", "add", "247",
})


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
        raise KeyError(action)

    async def _add(self, guild: discord.Guild, member: discord.Member, query: str, *, top: bool) -> str:
        if not query.strip():
            raise PlayerError("Type something to play.")
        in_voice = guild.get_member(member.id)  # only voice-cached members carry their voice state
        if in_voice and in_voice.voice:
            await self.players.join(in_voice)
        elif not guild.voice_client:
            raise PlayerError("Join a voice channel in this server first, then try again.")
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
        song = player.current if player else None
        if song is None:
            return None
        found = await self.players.lyrics_for(song)
        base = {"song_id": song.id, "title": song.title}
        if found is None:
            return {**base, "plain": "", "synced": [], "source": ""}
        return {**base, **found.to_dict()}
