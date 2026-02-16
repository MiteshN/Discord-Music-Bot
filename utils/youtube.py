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

YTDL_SEARCH_OPTIONS = {
    **YTDL_OPTIONS,
    "ignoreerrors": True,
    "extract_flat": True,
}

YTDL_PLAYLIST_OPTIONS = {
    **YTDL_OPTIONS,
    "noplaylist": False,
    "extract_flat": True,
}

FFMPEG_BEFORE_OPTIONS_STREAM = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -probesize 200000 -thread_queue_size 4096"
FFMPEG_BEFORE_OPTIONS_LOCAL = "-probesize 200000 -thread_queue_size 4096"
FFMPEG_OPTIONS = {
    "before_options": FFMPEG_BEFORE_OPTIONS_STREAM,
    "options": "-vn -bufsize 512k",
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)
ytdl_search = yt_dlp.YoutubeDL(YTDL_SEARCH_OPTIONS)
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
    async def create_source(cls, search: str, *, loop: asyncio.AbstractEventLoop = None, volume: float = 0.5, seek_to: int = 0, audio_filter: str = "", cache_manager=None):
        loop = loop or asyncio.get_event_loop()
        partial = functools.partial(ytdl.extract_info, search, download=False)
        data = await loop.run_in_executor(None, partial)

        if "entries" in data:
            data = data["entries"][0]

        # Determine audio source: cached local file or stream URL
        audio_path = data["url"]
        is_local = False

        if cache_manager and data.get("webpage_url"):
            from utils.cache import CacheManager
            cache_key = CacheManager.extract_cache_key(data["webpage_url"])
            cached = await cache_manager.get_cached_path(cache_key)
            if cached:
                audio_path = cached
                is_local = True
            else:
                downloaded = await cache_manager.download_and_cache(
                    cache_key,
                    data["webpage_url"],
                    data.get("duration"),
                    data.get("is_live", False),
                )
                if downloaded:
                    audio_path = downloaded
                    is_local = True

        before_options = FFMPEG_BEFORE_OPTIONS_LOCAL if is_local else FFMPEG_BEFORE_OPTIONS_STREAM
        if seek_to > 0:
            before_options = f"-ss {seek_to} {before_options}"

        options = FFMPEG_OPTIONS["options"]
        if audio_filter:
            options = f"{options} -af {audio_filter}"

        source = discord.FFmpegPCMAudio(
            audio_path,
            before_options=before_options,
            options=options,
        )
        return cls(source, data=data, volume=volume)

    @classmethod
    async def search_results(cls, query: str, count: int = 5, *, loop: asyncio.AbstractEventLoop = None):
        loop = loop or asyncio.get_event_loop()
        # Request extra to account for non-video results (channels, playlists)
        partial = functools.partial(ytdl_search.extract_info, f"ytsearch{count + 3}:{query}", download=False)
        data = await loop.run_in_executor(None, partial)
        entries = []
        for e in data.get("entries", []):
            if not e or not e.get("title"):
                continue
            # Skip channels and playlists — only keep videos
            if e.get("ie_key") == "YoutubeTab" or not e.get("duration"):
                continue
            e["webpage_url"] = e.get("url") or f"https://www.youtube.com/watch?v={e['id']}"
            e["duration"] = int(e.get("duration") or 0)
            entries.append(e)
        return entries[:count]

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
