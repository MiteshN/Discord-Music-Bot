from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from mugetsu.config import Config
from mugetsu.player.manager import PlayerManager
from mugetsu.player.models import PlayerError
from mugetsu.ui.announcer import Announcer

log = logging.getLogger("mugetsu")

EXTENSIONS = ("mugetsu.cogs.playback", "mugetsu.cogs.queue", "mugetsu.cogs.effects", "mugetsu.cogs.general")


class MugetsuBot(commands.Bot):
    def __init__(self, config: Config):
        intents = discord.Intents.default()
        intents.message_content = True  # for !prefix commands
        super().__init__(
            command_prefix=commands.when_mentioned_or(config.command_prefix),
            intents=intents,
            help_command=None,
            activity=discord.Activity(type=discord.ActivityType.listening, name="/play"),
        )
        self.config = config
        self.players = PlayerManager(self, config)
        self.announcer = Announcer(self)
        self.players.hooks = self.announcer
        self._web_task: asyncio.Task | None = None
        self._web_shutdown = asyncio.Event()
        self._closing = False

    async def setup_hook(self):
        await self.players.start()
        for extension in EXTENSIONS:
            await self.load_extension(extension)
        # Sync once per start (not on every reconnect like on_ready would)
        try:
            synced = await self.tree.sync()
            log.info("Synced %d slash commands", len(synced))
        except discord.HTTPException as e:
            log.error("Failed to sync slash commands: %s", e)
        if self.config.dashboard_enabled:
            self._web_task = asyncio.create_task(self._run_dashboard())
        else:
            log.info("Dashboard off: set DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET to enable it")

    async def on_ready(self):
        log.info("Signed in as %s (ID %s), in %d servers", self.user, self.user.id, len(self.guilds))

    async def on_command_error(self, ctx: commands.Context, error: Exception):
        if isinstance(error, commands.CommandNotFound):
            return
        while isinstance(error, (commands.CommandInvokeError, commands.HybridCommandError,
                                 app_commands.CommandInvokeError)):
            error = error.original
        if isinstance(error, PlayerError):
            message = str(error)
        elif isinstance(error, commands.MissingRequiredArgument):
            usage = f"{ctx.clean_prefix}{ctx.command.qualified_name} {ctx.command.signature}"
            message = f"Missing `{error.param.name}`. Usage: `{usage}`"
        elif isinstance(error, (commands.BadArgument, commands.BadLiteralArgument, app_commands.TransformerError)):
            message = f"Invalid argument: {error}"
        elif isinstance(error, commands.NoPrivateMessage):
            message = "Music commands only work in servers."
        elif isinstance(error, commands.CheckFailure):
            message = "You can't use that here."
        else:
            log.error("Error in command %s", ctx.command, exc_info=error)
            message = "Something went wrong running that command."
        try:
            await ctx.send(f"⚠️ {message}", ephemeral=True)
        except discord.HTTPException:
            pass

    async def _run_dashboard(self):
        from hypercorn.asyncio import serve
        from hypercorn.config import Config as HypercornConfig

        from mugetsu.web.app import create_app
        from mugetsu.web.backend import BotBackend

        hc = HypercornConfig()
        host = self.config.dashboard_host
        hc.bind = [f"[{host}]:{self.config.dashboard_port}" if ":" in host else f"{host}:{self.config.dashboard_port}"]
        hc.accesslog = None
        log.info("Dashboard listening on port %d (%s)", self.config.dashboard_port, self.config.dashboard_url)
        try:
            await serve(create_app(BotBackend(self), self.config), hc, shutdown_trigger=self._web_shutdown.wait)
        except Exception:
            log.exception("Dashboard crashed")

    async def close(self):
        if self._closing:
            return
        self._closing = True
        self._web_shutdown.set()
        if self._web_task:
            try:
                await asyncio.wait_for(self._web_task, timeout=5)
            except (TimeoutError, asyncio.CancelledError):
                pass
        try:
            await self.players.close()  # leaves voice channels cleanly while the gateway is still up
        except Exception:
            log.exception("Error while shutting down players")
        await super().close()
