"""In-process event bus connecting Music cog state changes to WebSocket clients."""

import asyncio
import logging
from collections import defaultdict
from typing import Any

log = logging.getLogger("bot.dashboard.events")


class EventBus:
    """Simple pub/sub for guild-scoped events."""

    def __init__(self):
        self._subscribers: dict[int, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, guild_id: int) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=32)
        self._subscribers[guild_id].add(q)
        return q

    def unsubscribe(self, guild_id: int, q: asyncio.Queue):
        subs = self._subscribers.get(guild_id)
        if subs is not None:
            subs.discard(q)
            if not subs:
                del self._subscribers[guild_id]

    def publish(self, guild_id: int, event_type: str, data: dict[str, Any]):
        msg = {"type": event_type, "data": data}
        for q in self._subscribers.get(guild_id, ()):
            if q.full():
                # A slow client only ever needs the newest full state: drop its oldest message
                q.get_nowait()
            q.put_nowait(msg)

    def has_subscribers(self, guild_id: int) -> bool:
        return bool(self._subscribers.get(guild_id))
