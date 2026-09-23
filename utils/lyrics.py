import asyncio
import logging
import os
import re

import aiohttp

log = logging.getLogger("bot.lyrics")

LRCLIB_URL = "https://lrclib.net/api/search"

# Noise commonly found in YouTube titles that hurts lyric matching
_TITLE_NOISE = re.compile(
    r"[\(\[][^)\]]*(official|video|audio|lyric|visuali[sz]er|remaster|hd|4k|mv|m/v|live|explicit)[^)\]]*[\)\]]"
    r"|\b(official (music )?video|lyrics?|hq|hd)\b",
    re.IGNORECASE,
)


def clean_title(title: str) -> str:
    title = _TITLE_NOISE.sub("", title)
    title = re.sub(r"\s+\(?(ft|feat)\.?\s.*$", "", title, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", title).strip(" -|")


class LyricsFetcher:
    """LRCLIB first (free, no key needed), Genius as a fallback when a token is configured."""

    def __init__(self):
        self.genius = None
        token = os.getenv("GENIUS_API_TOKEN")
        if token:
            import lyricsgenius

            self.genius = lyricsgenius.Genius(token, verbose=False, remove_section_headers=True, timeout=10, retries=1)

    async def fetch_lyrics(self, session: aiohttp.ClientSession, title: str) -> str | None:
        query = clean_title(title)
        try:
            async with session.get(
                LRCLIB_URL, params={"q": query}, timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status == 200:
                    for result in await resp.json():
                        if result.get("plainLyrics"):
                            return result["plainLyrics"]
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.debug("LRCLIB lookup failed for %r: %s", query, e)

        if self.genius:
            try:
                song = await asyncio.to_thread(self.genius.search_song, query)
                if song:
                    return song.lyrics
            except Exception as e:
                log.debug("Genius lookup failed for %r: %s", query, e)
        return None

    @staticmethod
    def split_lyrics(lyrics: str, limit: int = 4096) -> list[str]:
        chunks = []
        while len(lyrics) > limit:
            split_at = lyrics.rfind("\n", 0, limit)
            if split_at == -1:
                split_at = limit
            chunks.append(lyrics[:split_at])
            lyrics = lyrics[split_at:].lstrip("\n")
        if lyrics:
            chunks.append(lyrics)
        return chunks
