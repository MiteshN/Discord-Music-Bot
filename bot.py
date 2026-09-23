import asyncio
import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("bot")


class MusicBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(
            command_prefix=commands.when_mentioned_or("!"),
            intents=intents,
            activity=discord.Activity(type=discord.ActivityType.listening, name="/play"),
        )
        self._dashboard_task: asyncio.Task | None = None
        self._dashboard_shutdown = asyncio.Event()

    async def setup_hook(self):
        await self.load_extension("cogs.music")
        # Sync once per start (not on every reconnect like on_ready would)
        try:
            synced = await self.tree.sync()
            log.info("Synced %d slash commands", len(synced))
        except discord.HTTPException as e:
            log.error("Failed to sync commands: %s", e)
        if os.getenv("DISCORD_CLIENT_ID") and os.getenv("DISCORD_CLIENT_SECRET"):
            self._dashboard_task = asyncio.create_task(self._run_dashboard())
        else:
            log.info("Dashboard disabled: DISCORD_CLIENT_ID / DISCORD_CLIENT_SECRET not set")

    async def on_ready(self):
        log.info("Logged in as %s (ID: %s) in %d servers", self.user, self.user.id, len(self.guilds))

    async def _run_dashboard(self):
        from hypercorn.asyncio import serve
        from hypercorn.config import Config

        from dashboard import create_app

        config = Config()
        port = int(os.getenv("DASHBOARD_PORT", "8080"))
        config.bind = [f"0.0.0.0:{port}"]
        config.accesslog = None
        log.info("Starting dashboard on port %d", port)
        try:
            await serve(create_app(self), config, shutdown_trigger=self._dashboard_shutdown.wait)
        except Exception:
            log.exception("Dashboard crashed")

    async def close(self):
        self._dashboard_shutdown.set()
        if self._dashboard_task:
            try:
                await asyncio.wait_for(self._dashboard_task, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
        await super().close()


async def main():
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise SystemExit("DISCORD_BOT_TOKEN is not set")
    async with MusicBot() as bot:
        await bot.start(token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
