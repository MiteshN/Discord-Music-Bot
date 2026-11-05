"""Posts and retires the now-playing message, and relays player notices to the text channel."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from mugetsu.player.manager import PlayerHooks
from mugetsu.player.models import PlayerError, Song
from mugetsu.ui import embeds
from mugetsu.ui.views import NowPlayingView

if TYPE_CHECKING:
    from mugetsu.bot import MugetsuBot
    from mugetsu.player.player import GuildPlayer

log = logging.getLogger("mugetsu.announcer")


class Announcer(PlayerHooks):
    def __init__(self, bot: MugetsuBot):
        self.bot = bot
        self._views: dict[int, NowPlayingView] = {}

    def text_channel(self, player: GuildPlayer):
        guild = player.guild
        if guild is None:
            return None
        channel = guild.get_channel_or_thread(player.text_channel_id) if player.text_channel_id else None
        if channel is None and player.voice:
            channel = player.voice.channel  # voice channels have a built-in text chat
        return channel

    async def notice(self, player: GuildPlayer, text: str):
        channel = self.text_channel(player)
        if channel:
            try:
                await channel.send(text)
            except discord.HTTPException:
                pass

    async def track_started(self, player: GuildPlayer, song: Song, *, announce: bool):
        if announce:
            await self.announce(player)

    async def track_cleared(self, player: GuildPlayer):
        await self.retire(player.guild_id)

    async def announce(self, player: GuildPlayer, send=None):
        await self.retire(player.guild_id)
        if player.current is None:
            return
        if send is None:
            channel = self.text_channel(player)
            if channel is None:
                return
            send = channel.send
        view = NowPlayingView(self.bot, player.guild_id)
        try:
            message = await send(embed=embeds.now_playing(player), view=view)
        except discord.HTTPException as e:
            log.warning("[Guild %d] Couldn't send now-playing message: %s", player.guild_id, e)
            view.stop()
            return
        # Keep a partial message: interaction followups can't be edited after 15 min via their token
        view.message = message.channel.get_partial_message(message.id)
        self._views[player.guild_id] = view

    async def retire(self, guild_id: int):
        """Remove the buttons from the previous now-playing message."""
        view = self._views.pop(guild_id, None)
        if view is None:
            return
        view.stop()
        if view.message:
            try:
                await view.message.edit(view=None)
            except discord.HTTPException:
                pass

    async def enqueue_and_reply(self, player: GuildPlayer, songs: list[Song], label: str, *,
                                channel_id: int, send, top: bool = False, actor: discord.Member | None = None):
        """Queue songs from a command, replying with the now-playing card or an "added" summary."""
        started = await player.enqueue(songs, top=top, channel_id=channel_id, announce=False, actor=actor)
        if started and len(songs) == 1:
            await self.announce(player, send=send)
            return
        if player.current is None:
            raise PlayerError("Couldn't start playback.")
        await send(embed=embeds.added(player, songs, label, top))
        if started:
            await self.announce(player)
