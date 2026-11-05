from __future__ import annotations

from discord import app_commands
from discord.ext import commands

from mugetsu.cogs.common import MusicCog
from mugetsu.player.models import PlayerError
from mugetsu.ui import embeds


class Queue(MusicCog):
    """See and rearrange what's coming up."""

    @commands.hybrid_command(name="queue", aliases=["q"], description="Show the queue")
    @app_commands.describe(page="Page number")
    async def queue(self, ctx: commands.Context, page: int = 1):
        player = self.player(ctx)
        if not player.current and not player.q.queue:
            raise PlayerError("The queue is empty.")
        await ctx.send(embed=embeds.queue_page(player, page))

    @commands.hybrid_command(name="shuffle", description="Shuffle the queue")
    async def shuffle(self, ctx: commands.Context):
        await ctx.send(await self.player(ctx).shuffle(ctx.author))

    @commands.hybrid_command(name="remove", aliases=["rm"], description="Remove a song from the queue")
    @app_commands.describe(position="Position in the queue (see /queue)")
    async def remove(self, ctx: commands.Context, position: int):
        await ctx.send(await self.player(ctx).remove(position - 1, ctx.author))

    @commands.hybrid_command(name="move", description="Move a song to a different position in the queue")
    @app_commands.describe(from_position="Current position", to_position="New position")
    async def move(self, ctx: commands.Context, from_position: int, to_position: int):
        await ctx.send(await self.player(ctx).move(from_position - 1, to_position - 1, ctx.author))

    @commands.hybrid_command(name="clear", description="Clear the queue (keeps the current song playing)")
    async def clear(self, ctx: commands.Context):
        await ctx.send(await self.player(ctx).clear(ctx.author))


async def setup(bot):
    await bot.add_cog(Queue(bot))
