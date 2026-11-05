from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from enum import Enum

from mugetsu.media.youtube import Track

_ids = itertools.count(1)


class LoopMode(Enum):
    OFF = "off"
    TRACK = "track"
    QUEUE = "queue"


class PlayerError(Exception):
    """A user-facing error. The message is shown as-is."""


_SOURCES = (
    (re.compile(r"(youtube\.com|youtu\.be)"), "youtube"),
    (re.compile(r"soundcloud\.com"), "soundcloud"),
    (re.compile(r"spotify\.com"), "spotify"),
    (re.compile(r"bandcamp\.com"), "bandcamp"),
)


@dataclass(eq=False)
class Song:
    title: str
    query: str  # what to hand yt-dlp: a URL or search text
    requester: str
    requester_id: int = 0
    requester_avatar: str = ""
    url: str = ""  # canonical page URL, once known
    duration: int = 0
    thumbnail: str = ""
    artist: str = ""  # known for Spotify tracks; helps lyrics matching
    track_name: str = ""
    search_music: bool = False  # match on YouTube Music (used for Spotify tracks)
    origin_url: str = ""  # e.g. the Spotify track link this came from
    track: Track | None = None  # resolved stream info, if already extracted
    id: int = field(default_factory=lambda: next(_ids))

    @property
    def is_live(self) -> bool:
        return bool(self.track and self.track.is_live)

    @property
    def source(self) -> str:
        if self.search_music:
            return "spotify"
        for pattern, name in _SOURCES:
            if pattern.search(self.url or self.query):
                return name
        return "web" if self.url.startswith("http") else "youtube"

    def copy(self) -> Song:
        """A fresh queue entry for the same track (new id, stream re-resolved when needed)."""
        return Song(
            title=self.title, query=self.url or self.query, requester=self.requester,
            requester_id=self.requester_id, requester_avatar=self.requester_avatar, url=self.url,
            duration=self.duration, thumbnail=self.thumbnail, artist=self.artist, track_name=self.track_name,
            origin_url=self.origin_url,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url or self.origin_url,
            "duration": self.duration,
            "thumbnail": self.thumbnail,
            "artist": self.artist,
            "requester": self.requester,
            "requester_id": str(self.requester_id),
            "requester_avatar": self.requester_avatar,
            "source": self.source,
            "live": self.is_live,
        }
