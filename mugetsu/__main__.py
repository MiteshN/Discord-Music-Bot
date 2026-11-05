"""Entry point: ``python -m mugetsu``."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys


def setup_logging(level: str):
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("discord.gateway").setLevel(logging.WARNING)
    logging.getLogger("hypercorn.error").setLevel(logging.WARNING)


async def run(config) -> int:
    import discord

    from mugetsu.bot import MugetsuBot

    log = logging.getLogger("mugetsu")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass  # Windows: Ctrl+C still arrives as KeyboardInterrupt

    async with MugetsuBot(config) as bot:
        bot_task = asyncio.create_task(bot.start(config.token))
        stop_task = asyncio.create_task(stop.wait())
        done, _ = await asyncio.wait({bot_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        if stop_task in done:
            log.info("Shutting down…")
            await bot.close()
        else:
            stop_task.cancel()
        try:
            await bot_task
        except discord.LoginFailure:
            log.error("Discord rejected DISCORD_BOT_TOKEN. Check it in the Developer Portal (Bot > Reset Token).")
            return 1
        except discord.PrivilegedIntentsRequired:
            log.error("Enable the Message Content intent for this bot in the Developer Portal (Bot tab).")
            return 1
    return 0


def main() -> int:
    from dotenv import load_dotenv

    from mugetsu.config import Config

    load_dotenv()
    config = Config.from_env()
    setup_logging(config.log_level)
    if not config.token:
        logging.getLogger("mugetsu").error("DISCORD_BOT_TOKEN is not set (see .env.example)")
        return 1
    try:
        return asyncio.run(run(config))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
