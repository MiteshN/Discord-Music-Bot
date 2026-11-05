from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from mugetsu.cogs.common import MusicCog
from mugetsu.game import GuessTheSong, build_pool
from mugetsu.player.models import PlayerError
from mugetsu.ui import embeds


class Games(MusicCog):
    """Games to play together in voice."""

    @commands.hybrid_group(name="guessthesong", aliases=["gts"], fallback="play",
                           description="Play guess the song: race to name the title or artist")
    @app_commands.describe(
        source="A genre, decade (e.g. 80s rock, pop 2018) or a Spotify/YouTube playlist link. Empty for recent hits",
        rounds="How many rounds (3-30)",
        seconds="How long each clip plays (10-60)",
    )
    async def guessthesong(self, ctx: commands.Context, source: str = "",
                           rounds: app_commands.Range[int, 3, 30] = 10,
                           seconds: app_commands.Range[int, 10, 60] = 25):
        player = self.player(ctx)
        if player.game is not None:
            raise PlayerError("A game is already running here.")
        if player.current or player.q.queue:
            raise PlayerError("Music is playing. Stop it or clear the queue first, then start the game.")
        await ctx.defer()
        await self.players.join(ctx.author)
        player.text_channel_id = ctx.channel.id
        async with ctx.typing():
            pool = await build_pool(self.players.spotify, source, rounds)
        game = GuessTheSong(player, ctx.channel, ctx.author, pool, rounds=min(rounds, len(pool)), clip_seconds=seconds)
        game.start()
        await ctx.send("🎮 Starting guess the song" + (f" with **{discord.utils.escape_markdown(source)}**" if source else "")
                       + f". Get ready, {ctx.author.voice.channel.mention}!")

    @guessthesong.command(name="stop", description="End the current game")
    async def stop(self, ctx: commands.Context):
        player = self.players.peek(ctx.guild.id)
        game = player.game if player else None
        if game is None:
            raise PlayerError("No game is running.")
        if not game.can_stop(ctx.author):
            raise PlayerError("Only whoever started the game (or a DJ) can stop it.")
        game.abort()
        await ctx.send("🛑 Stopping the game…")

    @guessthesong.command(name="leaderboard", description="All-time guess the song scores for this server")
    async def leaderboard(self, ctx: commands.Context):
        rows = await self.players.store.game_leaderboard(ctx.guild.id)
        await ctx.send(embed=embeds.game_leaderboard(rows, ctx.guild.name))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot:
            return
        player = self.players.peek(message.guild.id)
        if player is not None and player.game is not None:
            await player.game.on_message(message)


async def setup(bot):
    await bot.add_cog(Games(bot))
