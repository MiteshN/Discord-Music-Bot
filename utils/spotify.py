import os
import re
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

SPOTIFY_URL_RE = re.compile(
    r"https?://open\.spotify\.com/(track|playlist|album)/([a-zA-Z0-9]+)"
)


class SpotifyResolver:
    def __init__(self):
        client_id = os.getenv("SPOTIFY_CLIENT_ID")
        client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
        if client_id and client_secret:
            self.sp = spotipy.Spotify(
                auth_manager=SpotifyClientCredentials(
                    client_id=client_id,
                    client_secret=client_secret,
                )
            )
        else:
            self.sp = None

    @staticmethod
    def is_spotify_url(url: str) -> bool:
        return bool(SPOTIFY_URL_RE.match(url))

    @staticmethod
    def parse_url(url: str) -> tuple[str, str] | None:
        match = SPOTIFY_URL_RE.match(url)
        if match:
            return match.group(1), match.group(2)
        return None

    def resolve_track(self, url: str) -> str | None:
        if not self.sp:
            return None
        track = self.sp.track(url)
        artists = ", ".join(a["name"] for a in track["artists"])
        return f"{artists} - {track['name']}"

    def resolve_playlist(self, url: str) -> list[str]:
        if not self.sp:
            return []
        results = []
        playlist = self.sp.playlist_tracks(url)
        for item in playlist["items"]:
            track = item.get("track")
            if track:
                artists = ", ".join(a["name"] for a in track["artists"])
                results.append(f"{artists} - {track['name']}")
        return results

    def resolve_album(self, url: str) -> list[str]:
        if not self.sp:
            return []
        results = []
        album = self.sp.album_tracks(url)
        for track in album["items"]:
            artists = ", ".join(a["name"] for a in track["artists"])
            results.append(f"{artists} - {track['name']}")
        return results

    def resolve(self, url: str) -> list[str]:
        parsed = self.parse_url(url)
        if not parsed:
            return []
        kind, _ = parsed
        if kind == "track":
            result = self.resolve_track(url)
            return [result] if result else []
        elif kind == "playlist":
            return self.resolve_playlist(url)
        elif kind == "album":
            return self.resolve_album(url)
        return []
