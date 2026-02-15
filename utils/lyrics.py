import os
import asyncio
import functools
import lyricsgenius


class LyricsFetcher:
    def __init__(self):
        token = os.getenv("GENIUS_API_TOKEN")
        if token:
            self.genius = lyricsgenius.Genius(token, verbose=False, remove_section_headers=True)
        else:
            self.genius = None

    async def fetch_lyrics(self, title: str) -> str | None:
        if not self.genius:
            return None
        loop = asyncio.get_event_loop()
        partial = functools.partial(self.genius.search_song, title)
        song = await loop.run_in_executor(None, partial)
        if song:
            return song.lyrics
        return None

    @staticmethod
    def split_lyrics(lyrics: str, limit: int = 4096) -> list[str]:
        if len(lyrics) <= limit:
            return [lyrics]
        chunks = []
        while lyrics:
            if len(lyrics) <= limit:
                chunks.append(lyrics)
                break
            split_at = lyrics.rfind("\n", 0, limit)
            if split_at == -1:
                split_at = limit
            chunks.append(lyrics[:split_at])
            lyrics = lyrics[split_at:].lstrip("\n")
        return chunks
