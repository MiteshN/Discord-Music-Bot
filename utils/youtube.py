import asyncio
import functools
import discord
import yt_dlp

YTDL_OPTIONS = {
    "format": "bestaudio[acodec=opus]/bestaudio/best",
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    "extract_flat": False,
}

YTDL_PLAYLIST_OPTIONS = {
    **YTDL_OPTIONS,
    "noplaylist": False,
    "extract_flat": True,
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -probesize 200000",
    "options": "-vn -bufsize 512k",
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)
ytdl_playlist = yt_dlp.YoutubeDL(YTDL_PLAYLIST_OPTIONS)


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title", "Unknown")
        self.url = data.get("url")
        self.webpage_url = data.get("webpage_url", "")
        self.duration = data.get("duration") or 0
        self.thumbnail = data.get("thumbnail", "")

    @classmethod
    async def create_source(cls, search: str, *, loop: asyncio.AbstractEventLoop = None, volume: float = 0.5, seek_to: int = 0, end_at: int = 0):
        loop = loop or asyncio.get_event_loop()
        partial = functools.partial(ytdl.extract_info, search, download=False)
        data = await loop.run_in_executor(None, partial)

        if "entries" in data:
            data = data["entries"][0]

        before_options = FFMPEG_OPTIONS["before_options"]
        if seek_to > 0:
            before_options = f"-ss {seek_to} {before_options}"
        if end_at > 0:
            before_options = f"{before_options} -to {end_at}"

        source = discord.FFmpegPCMAudio(
            data["url"],
            before_options=before_options,
            options=FFMPEG_OPTIONS["options"],
        )
        return cls(source, data=data, volume=volume)

    @classmethod
    async def search_results(cls, query: str, count: int = 5, *, loop: asyncio.AbstractEventLoop = None):
        loop = loop or asyncio.get_event_loop()
        partial = functools.partial(ytdl.extract_info, f"ytsearch{count}:{query}", download=False)
        data = await loop.run_in_executor(None, partial)
        return data.get("entries", [])

    @classmethod
    async def extract_playlist(cls, url: str, *, loop: asyncio.AbstractEventLoop = None):
        loop = loop or asyncio.get_event_loop()
        partial = functools.partial(ytdl_playlist.extract_info, url, download=False)
        data = await loop.run_in_executor(None, partial)
        if "entries" in data:
            return [
                {
                    "title": entry.get("title", "Unknown"),
                    "url": entry.get("url") or entry.get("webpage_url", ""),
                }
                for entry in data["entries"]
                if entry
            ]
        return []
