from __future__ import annotations

from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from mugetsu.cogs.common import MusicCog
from mugetsu.player.models import PlayerError
from mugetsu.ui import embeds

COG_ORDER = ("Playback", "Queue", "Playlists", "Games", "Effects", "General")


def _fields(lines: list[str], limit: int = 1024) -> list[str]:
    chunks, current = [], ""
    for line in lines:
        if current and len(current) + len(line) + 1 > limit:
            chunks.append(current)
            current = ""
        current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


class General(MusicCog):
    """Settings, cache and help."""

    @commands.hybrid_command(name="247", description="Toggle 24/7 mode (stay in the voice channel)")
    async def twenty_four_seven(self, ctx: commands.Context):
        player = self.player(ctx)
        await ctx.send(await player.set_247(not player.twenty_four_seven, ctx.author))

    @commands.hybrid_command(name="stats", aliases=["wrapped"], description="This server's top songs, requesters and listening time")
    @app_commands.describe(period="week, month or all time")
    async def stats(self, ctx: commands.Context, period: Literal["week", "month", "all"] = "week"):
        data = await self.players.stats(ctx.guild.id, period)
        embed = embeds.stats(data, ctx.guild.name)
        if self.bot.config.public_dashboard_url:
            embed.set_footer(text=f"More on the dashboard: {self.bot.config.public_dashboard_url}")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="cachestats", description="Show audio cache statistics")
    async def cachestats(self, ctx: commands.Context):
        await ctx.send(embed=embeds.cache_stats(await self.players.cache.get_stats()))

    @commands.hybrid_command(name="clearcache", description="Clear the audio cache")
    async def clearcache(self, ctx: commands.Context):
        self.players.require_dj(ctx.author)
        await self.players.cache.clear_all()
        await ctx.send("🧹 Audio cache cleared.")

    @commands.hybrid_command(name="dashboard", aliases=["web"], description="Get the link to the web dashboard")
    async def dashboard(self, ctx: commands.Context):
        url = self.bot.config.public_dashboard_url
        if not url:
            raise PlayerError("The web dashboard isn't enabled on this bot.")
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Open dashboard", emoji="🎛️", url=url))
        await ctx.send("Control the music from your browser:", view=view, ephemeral=True)

    @commands.hybrid_command(name="help", aliases=["commands"], description="List every command")
    async def help(self, ctx: commands.Context):
        prefix = "/" if ctx.interaction else ctx.clean_prefix
        embed = discord.Embed(title="Mugetsu commands", color=embeds.ACCENT)
        embed.description = (
            f"Use them as slash commands or with the `{self.bot.config.command_prefix}` prefix. "
            "Playback controls work for anyone in my voice channel."
        )
        for name in COG_ORDER:
            cog = self.bot.get_cog(name)
            if cog is None:
                continue
            lines = []
            for c in cog.get_commands():
                if c.hidden:
                    continue
                if isinstance(c, commands.Group):  # list subcommands, e.g. /playlist save
                    lines += [f"`{prefix}{c.name} {sub.name}` {sub.description}" for sub in c.commands]
                    if getattr(c, "fallback", None):
                        lines.insert(len(lines) - len(c.commands), f"`{prefix}{c.name} {c.fallback}` {c.description}")
                else:
                    lines.append(f"`{prefix}{c.name}` {c.description}")
            for i, chunk in enumerate(_fields(lines)):
                embed.add_field(name=name if i == 0 else f"{name} (cont.)", value=chunk, inline=False)
        if self.bot.config.public_dashboard_url:
            embed.add_field(name="Dashboard", value=self.bot.config.public_dashboard_url, inline=False)
        role = self.bot.config.dj_role
        embed.set_footer(text=f"If a role named {role} exists, only {role}s and admins can stop, clear, skip to, "
                              "shuffle, remove, move, change the volume and toggle 24/7.")
        await ctx.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(General(bot))
