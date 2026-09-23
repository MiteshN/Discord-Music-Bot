import asyncio
import random
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

from utils.audio import AudioFilter, AudioInput
from utils.youtube import Track


class LoopMode(Enum):
    OFF = "off"
    TRACK = "track"
    QUEUE = "queue"


@dataclass
class Song:
    title: str
    query: str  # what to hand yt-dlp: a URL or search text
    requester: str
    requester_id: int = 0
    url: str = ""  # canonical page URL, once known
    duration: int = 0
    thumbnail: str = ""
    search_music: bool = False  # match on YouTube Music (used for Spotify tracks)
    track: Track | None = None  # resolved stream info, if already extracted

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "duration": self.duration,
            "thumbnail": self.thumbnail,
            "requester": self.requester,
        }


@dataclass
class GuildQueue:
    queue: deque[Song] = field(default_factory=deque)
    history: deque[Song] = field(default_factory=lambda: deque(maxlen=50))
    current: Song | None = None
    volume: float = 1.0
    loop_mode: LoopMode = LoopMode.OFF
    skip_votes: set[int] = field(default_factory=set)
    twenty_four_seven: bool = False
    audio_filter: AudioFilter | None = None
    text_channel_id: int | None = None

    # Playback bookkeeping
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    play_id: int = 0  # bumped on every play/stop so stale "track ended" callbacks are ignored
    audio_input: AudioInput | None = None
    np_view: object | None = None  # NowPlayingView attached to the current now-playing message
    idle_since: float | None = field(default_factory=time.monotonic)
    alone_since: float | None = None
    _pos_base: float = 0.0
    _pos_anchor: float | None = None  # monotonic time playback (re)started; None while paused

    # --- Position tracking (accounts for pauses and speed-changing filters) ---

    @property
    def rate(self) -> float:
        return self.audio_filter.rate if self.audio_filter else 1.0

    @property
    def position(self) -> float:
        if self._pos_anchor is None:
            return self._pos_base
        return self._pos_base + (time.monotonic() - self._pos_anchor) * self.rate

    def mark_playing(self, position: float = 0.0):
        self._pos_base = position
        self._pos_anchor = time.monotonic()
        self.idle_since = None

    def mark_paused(self):
        self._pos_base = self.position
        self._pos_anchor = None

    def mark_resumed(self):
        if self._pos_anchor is None:
            self._pos_anchor = time.monotonic()

    def mark_idle(self):
        self.current = None
        self.audio_input = None
        self._pos_base = 0.0
        self._pos_anchor = None
        self.idle_since = time.monotonic()

    # --- Queue operations ---

    def add(self, songs: list[Song], *, top: bool = False):
        if top:
            self.queue.extendleft(reversed(songs))
        else:
            self.queue.extend(songs)

    def advance(self, *, skipping: bool = False, failed: bool = False) -> Song | None:
        """Move to the next song according to the loop mode and return it."""
        prev = self.current
        if prev and not failed:
            if self.loop_mode is LoopMode.TRACK and not skipping:
                return prev
            self.history.append(prev)
            if self.loop_mode is LoopMode.QUEUE:
                self.queue.append(prev)
        self.current = self.queue.popleft() if self.queue else None
        self.skip_votes.clear()
        return self.current

    def rewind(self) -> Song | None:
        """Step back to the previously played song."""
        if not self.history:
            return None
        prev = self.history.pop()
        if self.current:
            if self.loop_mode is LoopMode.QUEUE and self.queue and self.queue[-1] is prev:
                self.queue.pop()  # it was re-appended when it finished
            self.queue.appendleft(self.current)
        self.current = prev
        self.skip_votes.clear()
        return prev

    def remove(self, index: int) -> Song | None:
        if 0 <= index < len(self.queue):
            song = self.queue[index]
            del self.queue[index]
            return song
        return None

    def move(self, from_idx: int, to_idx: int) -> bool:
        if not (0 <= from_idx < len(self.queue) and 0 <= to_idx < len(self.queue)):
            return False
        song = self.queue[from_idx]
        del self.queue[from_idx]
        self.queue.insert(to_idx, song)
        return True

    def shuffle(self):
        items = list(self.queue)
        random.shuffle(items)
        self.queue = deque(items)


class QueueManager:
    def __init__(self, settings):
        self._settings = settings
        self._queues: dict[int, GuildQueue] = {}

    def get(self, guild_id: int) -> GuildQueue:
        gq = self._queues.get(guild_id)
        if gq is None:
            saved = self._settings.get(guild_id)
            gq = GuildQueue(volume=saved["volume"], twenty_four_seven=saved["twenty_four_seven"])
            self._queues[guild_id] = gq
        return gq

    def peek(self, guild_id: int) -> GuildQueue | None:
        return self._queues.get(guild_id)

    def remove(self, guild_id: int):
        self._queues.pop(guild_id, None)
