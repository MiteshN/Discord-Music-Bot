"""Per-guild queue state: upcoming songs, history, loop mode, and the playback clock.

Pure and synchronous, so it can be tested without Discord.
"""

from __future__ import annotations

import random
import time
from collections import deque
from dataclasses import dataclass, field

from mugetsu.media.ffmpeg import AudioFilter
from mugetsu.player.models import LoopMode, Song

HISTORY_LIMIT = 50


@dataclass
class GuildQueue:
    queue: deque[Song] = field(default_factory=deque)
    history: deque[Song] = field(default_factory=lambda: deque(maxlen=HISTORY_LIMIT))
    current: Song | None = None
    loop_mode: LoopMode = LoopMode.OFF
    audio_filter: AudioFilter | None = None
    skip_votes: set[int] = field(default_factory=set)
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

    def mark_paused(self):
        self._pos_base = self.position
        self._pos_anchor = None

    def mark_resumed(self):
        if self._pos_anchor is None:
            self._pos_anchor = time.monotonic()

    def mark_idle(self):
        self.current = None
        self._pos_base = 0.0
        self._pos_anchor = None

    # --- Queue operations ---

    @property
    def duration(self) -> int:
        return sum(s.duration for s in self.queue)

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

    def index_of(self, song_id: int) -> int:
        for i, song in enumerate(self.queue):
            if song.id == song_id:
                return i
        return -1

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

    def remove_indices(self, indices: list[int]) -> list[Song]:
        """Remove the songs at these positions (bad ones are ignored). Returns what was removed."""
        wanted = {i for i in indices if 0 <= i < len(self.queue)}
        return self.remove_where(lambda i, _song: i in wanted)

    def remove_where(self, condition) -> list[Song]:
        """Remove every song for which condition(index, song) is true. Returns what was removed."""
        kept, removed = deque(), []
        for i, song in enumerate(self.queue):
            (removed if condition(i, song) else kept).append(song)
        self.queue = kept
        return removed

    def drop_before(self, index: int) -> list[Song]:
        """Take the songs ahead of ``index`` off the queue, so it becomes the next one."""
        if not 0 <= index < len(self.queue):
            raise IndexError(index)
        return [self.queue.popleft() for _ in range(index)]

    def shuffle(self):
        items = list(self.queue)
        random.shuffle(items)
        self.queue = deque(items)
