from __future__ import annotations

from discord import app_commands
from discord.ext import commands

from mugetsu.cogs.common import MusicCog, require_listener_if_connected


class Effects(MusicCog):
    """Audio effects, applied by FFmpeg."""

    async def _apply(self, ctx: commands.Context, key: str):
        require_listener_if_connected(ctx)
        await ctx.send(await self.player(ctx).set_filter(key, ctx.author))

    @commands.hybrid_command(name="nightcore", description="Nightcore effect (faster, higher pitch)")
    async def nightcore(self, ctx: commands.Context):
        await self._apply(ctx, "nightcore")

    @commands.hybrid_command(name="vaporwave", description="Vaporwave effect (slower, lower pitch)")
    async def vaporwave(self, ctx: commands.Context):
        await self._apply(ctx, "vaporwave")

    @commands.hybrid_command(name="bassboost", description="Boost bass frequencies")
    async def bassboost(self, ctx: commands.Context):
        await self._apply(ctx, "bassboost")

    @commands.hybrid_command(name="tremolo", description="Tremolo effect (volume wobble)")
    async def tremolo(self, ctx: commands.Context):
        await self._apply(ctx, "tremolo")

    @commands.hybrid_command(name="vibrato", description="Vibrato effect (pitch wobble)")
    async def vibrato(self, ctx: commands.Context):
        await self._apply(ctx, "vibrato")

    @commands.hybrid_command(name="8d", description="8D audio effect (rotating stereo)")
    async def eightd(self, ctx: commands.Context):
        await self._apply(ctx, "8d")

    @commands.hybrid_command(name="speed", description="Change playback speed (0.5-2.0)")
    @app_commands.describe(rate="Playback speed, e.g. 1.25")
    async def speed(self, ctx: commands.Context, rate: app_commands.Range[float, 0.5, 2.0]):
        await self._apply(ctx, f"speed:{rate:g}")

    @commands.hybrid_command(name="cleareffect", aliases=["clearfilter", "noeffect"], description="Remove audio effects")
    async def cleareffect(self, ctx: commands.Context):
        await self._apply(ctx, "clear")


async def setup(bot):
    await bot.add_cog(Effects(bot))
