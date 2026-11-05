"""WebSocket for live dashboard updates: full state on change, position heartbeats in between."""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlsplit

from quart import Blueprint, current_app, session, websocket

log = logging.getLogger("mugetsu.web.ws")

ws_bp = Blueprint("ws", __name__)

HEARTBEAT_INTERVAL = 10


def _origin_allowed() -> bool:
    origin = websocket.headers.get("Origin")
    if not origin or current_app.config.get("DEMO_USER"):
        return True
    host = urlsplit(origin).netloc
    allowed = {websocket.host, urlsplit(current_app.config["MUGETSU"].dashboard_url).netloc}
    return host in allowed


@ws_bp.websocket("/ws/guilds/<int:guild_id>")
async def guild_socket(guild_id: int):
    if not _origin_allowed():
        await websocket.close(1008, "Origin not allowed")  # before accept: the handshake is refused
        return
    # Accept first so the browser sees our close code (a refused handshake only shows up as 1006)
    await websocket.accept()
    if "user" not in session:
        await websocket.close(4001, "Not signed in")
        return
    backend = current_app.config["BACKEND"]
    if not await backend.can_view(guild_id, int(session["user"]["id"])):
        await websocket.close(4003, "No access to this server")
        return

    q = backend.events.subscribe(guild_id)
    try:
        await websocket.send_json({"type": "state", "data": backend.state(guild_id)})
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=HEARTBEAT_INTERVAL)
            except asyncio.TimeoutError:
                # Keep the connection alive and correct any clock drift in the progress bar
                state = backend.state(guild_id)
                msg = {"type": "position", "data": {k: state[k] for k in ("position", "rate", "paused", "timestamp")}}
            await websocket.send_json(msg)
    except asyncio.CancelledError:
        raise
    finally:
        backend.events.unsubscribe(guild_id, q)
