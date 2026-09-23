import os
import re

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

SPOTIFY_URL_RE = re.compile(
    r"https?://open\.spotify\.com/(?:intl-[a-z-]+/)?(track|playlist|album)/([a-zA-Z0-9]+)"
)

# Hard cap so one huge playlist can't flood the queue
MAX_TRACKS = 500


def _track_info(track: dict, thumbnail: str | None = None) -> dict:
    artists = ", ".join(a["name"] for a in track.get("artists", []))
    if thumbnail is None:
        images = (track.get("album") or {}).get("images") or []
        thumbnail = images[0]["url"] if images else ""
    return {
        "title": f"{artists} - {track['name']}",
        "artist": artists,
        "name": track["name"],
        "duration": (track.get("duration_ms") or 0) // 1000,
        "thumbnail": thumbnail,
    }


class SpotifyResolver:
    """Resolves Spotify links to track metadata. Audio is then matched on YouTube Music."""

    def __init__(self):
        client_id = os.getenv("SPOTIFY_CLIENT_ID")
        client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
        if client_id and client_secret:
            self.sp = spotipy.Spotify(
                auth_manager=SpotifyClientCredentials(client_id=client_id, client_secret=client_secret),
                requests_timeout=10,
                retries=2,
            )
        else:
            self.sp = None

    @staticmethod
    def is_spotify_url(url: str) -> bool:
        return bool(SPOTIFY_URL_RE.match(url))

    def _paginate(self, page: dict) -> list[dict]:
        items = list(page["items"])
        while page.get("next") and len(items) < MAX_TRACKS:
            page = self.sp.next(page)
            items.extend(page["items"])
        return items[:MAX_TRACKS]

    def resolve(self, url: str) -> tuple[str, list[dict]]:
        """Return (collection name, tracks). Blocking; run in a thread."""
        match = SPOTIFY_URL_RE.match(url)
        if not match or not self.sp:
            return "", []
        kind, spotify_id = match.groups()
        if kind == "track":
            track = self.sp.track(spotify_id)
            return track["name"], [_track_info(track)]
        if kind == "playlist":
            playlist = self.sp.playlist(spotify_id, fields="name")
            items = self._paginate(self.sp.playlist_items(spotify_id, additional_types=("track",)))
            tracks = [_track_info(i["track"]) for i in items if i.get("track") and i["track"].get("name")]
            return playlist["name"], tracks
        album = self.sp.album(spotify_id)
        thumbnail = album["images"][0]["url"] if album.get("images") else ""
        items = self._paginate(album["tracks"])
        return album["name"], [_track_info(t, thumbnail) for t in items]
