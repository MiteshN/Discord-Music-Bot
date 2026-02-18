"""In-process event bus connecting Music cog state changes to WebSocket clients."""

import asyncio
import logging
from collections import defaultdict
from typing import Any

log = logging.getLogger("bot.dashboard.events")


class EventBus:
    """Simple pub/sub for guild-scoped events."""

    def __init__(self):
        # guild_id -> set of asyncio.Queue
        self._subscribers: dict[int, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, guild_id: int) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers[guild_id].add(q)
        log.debug("New subscriber for guild %d (total: %d)", guild_id, len(self._subscribers[guild_id]))
        return q

    def unsubscribe(self, guild_id: int, q: asyncio.Queue):
        self._subscribers[guild_id].discard(q)
        if not self._subscribers[guild_id]:
            del self._subscribers[guild_id]

    def publish(self, guild_id: int, event_type: str, data: dict[str, Any]):
        msg = {"type": event_type, "data": data}
        dead: list[asyncio.Queue] = []
        for q in self._subscribers.get(guild_id, set()):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers[guild_id].discard(q)

    def has_subscribers(self, guild_id: int) -> bool:
        return bool(self._subscribers.get(guild_id))
