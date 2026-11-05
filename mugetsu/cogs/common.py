from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from mugetsu.player.models import PlayerError

if TYPE_CHECKING:
    from mugetsu.bot import MugetsuBot
    from mugetsu.player.player import GuildPlayer


class MusicCog(commands.Cog):
    def __init__(self, bot: MugetsuBot):
        self.bot = bot

    @property
    def players(self):
        return self.bot.players

    @property
    def announcer(self):
        return self.bot.announcer

    def player(self, ctx: commands.Context) -> GuildPlayer:
        return self.bot.players.get(ctx.guild.id)

    async def cog_check(self, ctx: commands.Context) -> bool:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        return True


def require_listener(ctx: commands.Context) -> discord.VoiceClient:
    """Playback controls are only for people in the bot's voice channel."""
    vc = ctx.voice_client
    if not vc or not vc.is_connected():
        raise PlayerError("I'm not in a voice channel.")
    if not ctx.author.voice or ctx.author.voice.channel != vc.channel:
        raise PlayerError(f"Join {vc.channel.mention} to control playback.")
    return vc


def require_listener_if_connected(ctx: commands.Context):
    if ctx.voice_client:
        require_listener(ctx)
