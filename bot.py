import logging
import os
import asyncio
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

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    log.info("Logged in as %s (ID: %s)", bot.user, bot.user.id)
    try:
        synced = await bot.tree.sync()
        log.info("Synced %d slash commands", len(synced))
    except Exception as e:
        log.error("Failed to sync commands: %s", e)


async def start_dashboard():
    """Start the Quart dashboard alongside the bot if OAuth2 credentials are configured."""
    client_id = os.getenv("DISCORD_CLIENT_ID")
    client_secret = os.getenv("DISCORD_CLIENT_SECRET")
    if not client_id or not client_secret:
        log.info("Dashboard disabled: DISCORD_CLIENT_ID / DISCORD_CLIENT_SECRET not set")
        return

    from dashboard import create_app
    from hypercorn.asyncio import serve
    from hypercorn.config import Config

    app = create_app(bot)

    config = Config()
    port = int(os.getenv("DASHBOARD_PORT", "8080"))
    config.bind = [f"0.0.0.0:{port}"]
    config.accesslog = "-"

    log.info("Starting dashboard on port %d", port)
    await serve(app, config, shutdown_trigger=lambda: asyncio.Future())


async def main():
    async with bot:
        await bot.load_extension("cogs.music")
        # Start dashboard as a background task (non-blocking)
        asyncio.create_task(start_dashboard())
        await bot.start(os.getenv("DISCORD_BOT_TOKEN"))


if __name__ == "__main__":
    asyncio.run(main())
