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


_YOUTUBE_ID = re.compile(r"(?:v=|youtu\.be/|/shorts/)([A-Za-z0-9_-]{11})")


def song_key(url: str, title: str) -> str:
    """What makes two queue entries "the same song" (for duplicates and autoplay)."""
    m = _YOUTUBE_ID.search(url or "")
    return m.group(1) if m else (url or title.strip().lower())


_SOURCES = (
    (re.compile(r"(youtube\.com|youtu\.be)"), "youtube"),
    (re.compile(r"soundcloud\.com"), "soundcloud"),
    (re.compile(r"spotify\.com"), "spotify"),
    (re.compile(r"bandcamp\.com"), "bandcamp"),
)


RECORD_FIELDS = (
    "title", "query", "url", "duration", "thumbnail", "artist", "track_name",
    "search_music", "origin_url", "stream_url",
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
    stream_url: str = ""  # a direct audio stream (internet radio) that needs no yt-dlp
    track: Track | None = None  # resolved stream info, if already extracted
    id: int = field(default_factory=lambda: next(_ids))

    @property
    def key(self) -> str:
        return song_key(self.url or self.origin_url, self.title)

    @property
    def is_live(self) -> bool:
        return bool(self.stream_url) or bool(self.track and self.track.is_live)

    @property
    def source(self) -> str:
        if self.stream_url:
            return "radio"
        if self.search_music:
            return "spotify"
        for pattern, name in _SOURCES:
            if pattern.search(self.url or self.query):
                return name
        return "web" if self.url.startswith("http") else "youtube"

    def copy(self) -> Song:
        """A fresh queue entry for the same track (new id, stream re-resolved when needed)."""
        return Song.from_record(self.to_record())

    def to_record(self) -> dict:
        """Everything needed to queue this song again later (playlists, history, restarts)."""
        record = {name: getattr(self, name) for name in RECORD_FIELDS}
        record.update(requester=self.requester, requester_id=self.requester_id, requester_avatar=self.requester_avatar)
        return record

    @classmethod
    def from_record(cls, record: dict, requester: dict | None = None) -> Song:
        """Rebuild a song from to_record(); `requester` (Requester.fields()) replaces who asked for it."""
        fields = {name: record[name] for name in RECORD_FIELDS if name in record}
        fields["title"] = str(fields.get("title") or record.get("query") or "Unknown")
        fields["query"] = str(fields.get("query") or fields.get("url") or fields["title"])
        fields["duration"] = int(fields.get("duration") or 0)
        who = requester or {
            "requester": record.get("requester") or "Someone",
            "requester_id": int(record.get("requester_id") or 0),
            "requester_avatar": record.get("requester_avatar") or "",
        }
        return cls(**fields, **who)

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
