"""WebSocket handler for real-time dashboard updates."""

import asyncio
import logging

from quart import Blueprint, current_app, session, websocket

from dashboard.api import user_can_access

log = logging.getLogger("bot.dashboard.ws")

ws_bp = Blueprint("ws", __name__)

HEARTBEAT_INTERVAL = 10


@ws_bp.websocket("/ws/<int:guild_id>")
async def ws_handler(guild_id: int):
    if "user" not in session:
        await websocket.close(4001, "Not authenticated")
        return
    if not user_can_access(guild_id):
        await websocket.close(4003, "No access to this guild")
        return

    bot = current_app.config["BOT"]
    event_bus = current_app.config["EVENT_BUS"]
    cog = bot.cogs.get("Music")
    if cog is None:
        await websocket.close(1011, "Music unavailable")
        return

    q = event_bus.subscribe(guild_id)
    try:
        await websocket.send_json({"type": "state", "data": cog.player_state(guild_id)})
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=HEARTBEAT_INTERVAL)
            except asyncio.TimeoutError:
                # Keep the connection alive and correct any clock drift in the progress bar
                state = cog.player_state(guild_id)
                msg = {"type": "position", "data": {k: state[k] for k in ("elapsed", "rate", "paused", "timestamp")}}
            await websocket.send_json(msg)
    except asyncio.CancelledError:
        pass
    finally:
        event_bus.unsubscribe(guild_id, q)
