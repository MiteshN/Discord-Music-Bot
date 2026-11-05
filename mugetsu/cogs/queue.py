from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from mugetsu.cogs.common import MusicCog
from mugetsu.cogs.playback import no_peeking
from mugetsu.player.models import PlayerError
from mugetsu.ui import embeds
from mugetsu.util import parse_positions


class Queue(MusicCog):
    """See and rearrange what's coming up."""

    @commands.hybrid_command(name="queue", aliases=["q"], description="Show the queue")
    @app_commands.describe(page="Page number")
    async def queue(self, ctx: commands.Context, page: int = 1):
        player = self.player(ctx)
        no_peeking(player)
        if not player.current and not player.q.queue:
            raise PlayerError("The queue is empty.")
        await ctx.send(embed=embeds.queue_page(player, page))

    @commands.hybrid_command(name="shuffle", description="Shuffle the queue")
    async def shuffle(self, ctx: commands.Context):
        await ctx.send(await self.player(ctx).shuffle(ctx.author))

    @commands.hybrid_command(name="remove", aliases=["rm"], description="Remove songs from the queue (e.g. 3, 3-7, or 1 4 9)")
    @app_commands.describe(positions="Positions in the queue (see /queue), like 3 or 3-7 or 1 4 9")
    async def remove(self, ctx: commands.Context, *, positions: str):
        try:
            indices = parse_positions(positions)
        except ValueError:
            raise PlayerError("Give positions like `3`, `3-7` or `1 4 9`.") from None
        player = self.player(ctx)
        if len(indices) == 1:
            await ctx.send(await player.remove(indices[0], ctx.author))
        else:
            await ctx.send(await player.remove_positions(indices, ctx.author))

    @commands.hybrid_command(name="removedupes", aliases=["dedupe", "removeduplicates"], description="Remove duplicate songs from the queue")
    async def removedupes(self, ctx: commands.Context):
        await ctx.send(await self.player(ctx).remove_duplicates(ctx.author))

    @commands.hybrid_command(name="removeuser", aliases=["rmuser"], description="Remove every song someone queued")
    @app_commands.describe(member="Whose songs to remove (leave empty for your own)")
    async def removeuser(self, ctx: commands.Context, member: discord.Member | None = None):
        member = member or ctx.author
        await ctx.send(await self.player(ctx).remove_requester(member.id, member.display_name, ctx.author))

    @commands.hybrid_command(name="removeabsent", aliases=["rmabsent"], description="Remove songs queued by people who left the voice channel")
    async def removeabsent(self, ctx: commands.Context):
        await ctx.send(await self.player(ctx).remove_absent(ctx.author))

    @commands.hybrid_command(name="move", description="Move a song to a different position in the queue")
    @app_commands.describe(from_position="Current position", to_position="New position")
    async def move(self, ctx: commands.Context, from_position: int, to_position: int):
        await ctx.send(await self.player(ctx).move(from_position - 1, to_position - 1, ctx.author))

    @commands.hybrid_command(name="clear", description="Clear the queue (keeps the current song playing)")
    async def clear(self, ctx: commands.Context):
        await ctx.send(await self.player(ctx).clear(ctx.author))


async def setup(bot):
    await bot.add_cog(Queue(bot))
