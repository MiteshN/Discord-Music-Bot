"""WebSocket handler for real-time dashboard updates."""

import asyncio
import json
import logging
import time

from quart import Blueprint, websocket, session

from dashboard.events import EventBus

log = logging.getLogger("bot.dashboard.ws")

ws_bp = Blueprint("ws", __name__)


def _get_player_state(bot, guild_id: int) -> dict:
    """Build a full player state snapshot."""
    music_cog = bot.cogs.get("Music")
    if not music_cog:
        return {}

    gq = music_cog.queue_manager.get(guild_id)
    guild = bot.get_guild(guild_id)
    vc = guild.voice_client if guild else None

    current = None
    if gq.current:
        current = {
            "title": gq.current.title,
            "url": gq.current.url,
            "duration": gq.current.duration,
            "thumbnail": gq.current.thumbnail,
            "requester": gq.current.requester,
        }

    elapsed = 0
    if gq.start_time and gq.current:
        elapsed = time.time() - gq.start_time

    is_paused = vc.is_paused() if vc else False
    is_playing = vc.is_playing() if vc else False

    queue = [
        {
            "title": s.title,
            "url": s.url,
            "duration": s.duration,
            "thumbnail": s.thumbnail,
            "requester": s.requester,
        }
        for s in gq.queue
    ]

    return {
        "current": current,
        "elapsed": elapsed,
        "paused": is_paused,
        "playing": is_playing,
        "volume": int(gq.volume * 100),
        "loop": gq.loop_mode.value,
        "filter": gq.audio_filter_name,
        "queue": queue,
        "in_voice": vc is not None and vc.is_connected(),
        "timestamp": time.time(),
    }


@ws_bp.websocket("/ws/<int:guild_id>")
async def ws_handler(guild_id: int):
    # Auth check via session cookie
    if "user" not in session:
        await websocket.close(4001, "Not authenticated")
        return

    from quart import current_app
    bot = current_app.config["BOT"]
    event_bus: EventBus = current_app.config["EVENT_BUS"]

    # Verify user has access to this guild
    user_guild_ids = {int(gid) for gid in session.get("guild_ids", [])}
    bot_guild_ids = {g.id for g in bot.guilds}
    if guild_id not in user_guild_ids or guild_id not in bot_guild_ids:
        await websocket.close(4003, "No access to this guild")
        return

    # Send initial full state
    state = _get_player_state(bot, guild_id)
    await websocket.send_json({"type": "full_state", "data": state})

    # Subscribe to events
    q = event_bus.subscribe(guild_id)
    try:
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=5.0)
                await websocket.send_json(msg)
            except asyncio.TimeoutError:
                # Send heartbeat with current position
                state = _get_player_state(bot, guild_id)
                await websocket.send_json({"type": "heartbeat", "data": {
                    "elapsed": state["elapsed"],
                    "paused": state["paused"],
                    "playing": state["playing"],
                    "timestamp": state["timestamp"],
                }})
    except asyncio.CancelledError:
        pass
    finally:
        event_bus.unsubscribe(guild_id, q)
