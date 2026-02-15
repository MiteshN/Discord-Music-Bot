import random
import time
from dataclasses import dataclass, field
from collections import defaultdict
from enum import Enum


class LoopMode(Enum):
    OFF = "off"
    TRACK = "track"
    QUEUE = "queue"


@dataclass
class Song:
    title: str
    url: str
    search_query: str
    requester: str
    duration: int = 0
    thumbnail: str = ""


@dataclass
class GuildQueue:
    queue: list[Song] = field(default_factory=list)
    current: Song | None = None
    volume: float = 0.5
    loop_mode: LoopMode = LoopMode.OFF
    start_time: float = 0.0
    skip_votes: set = field(default_factory=set)

    def add(self, song: Song):
        self.queue.append(song)

    def next(self) -> Song | None:
        if self.loop_mode == LoopMode.TRACK and self.current:
            return self.current
        if self.loop_mode == LoopMode.QUEUE and self.current:
            self.queue.append(self.current)
        if self.queue:
            self.current = self.queue.pop(0)
            self.skip_votes.clear()
            return self.current
        self.current = None
        return None

    def remove(self, index: int) -> Song | None:
        if 0 <= index < len(self.queue):
            return self.queue.pop(index)
        return None

    def shuffle(self):
        random.shuffle(self.queue)

    def clear(self):
        self.queue.clear()
        self.current = None
        self.skip_votes.clear()


class QueueManager:
    def __init__(self):
        self._queues: dict[int, GuildQueue] = defaultdict(GuildQueue)

    def get(self, guild_id: int) -> GuildQueue:
        return self._queues[guild_id]

    def remove(self, guild_id: int):
        self._queues.pop(guild_id, None)
