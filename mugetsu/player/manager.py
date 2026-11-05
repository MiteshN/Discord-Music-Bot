"""Owns every guild's player plus the shared services they use (cache, Spotify, lyrics, settings)."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

import aiohttp
import discord

from mugetsu.media import youtube
from mugetsu.media.cache import CacheManager
from mugetsu.media.ffmpeg import AudioInput, build_source, is_opus
from mugetsu.media.lyrics import Lyrics, LyricsFetcher
from mugetsu.media.spotify import SpotifyResolver
from mugetsu.player.events import EventBus, StateNotifier
from mugetsu.player.models import PlayerError, Song
from mugetsu.player.player import GuildPlayer
from mugetsu.player.settings import GuildSettings
from mugetsu.util import short_error

if TYPE_CHECKING:
    from mugetsu.config import Config

log = logging.getLogger("mugetsu.manager")

URL_RE = re.compile(r"^https?://", re.IGNORECASE)
YOUTUBE_PLAYLIST_RE = re.compile(r"(youtube\.com/.*[?&]list=|youtu\.be/.*[?&]list=)([\w-]+)")
INACTIVITY_INTERVAL = 30
SEARCH_TTL = 300


@dataclass(frozen=True)
class Requester:
    name: str
    id: int
    avatar: str = ""

    @classmethod
    def of(cls, member: discord.abc.User) -> Requester:
        return cls(member.display_name, member.id, member.display_avatar.with_size(64).url)

    def fields(self) -> dict:
        return {"requester": self.name, "requester_id": self.id, "requester_avatar": self.avatar}


class PlayerHooks:
    """How the player reaches Discord chat. The UI layer replaces these no-op defaults."""

    async def notice(self, player: GuildPlayer, text: str):
        pass

    async def track_started(self, player: GuildPlayer, song: Song, *, announce: bool):
        pass

    async def track_cleared(self, player: GuildPlayer):
        pass


class PlayerManager:
    def __init__(self, bot: discord.Client, config: Config):
        self.bot = bot
        self.config = config
        self.settings = GuildSettings(config.cache_dir)
        self.cache = CacheManager(config.cache_dir, config.cache_limit_mb, config.max_cache_duration)
        self.spotify = SpotifyResolver(config.spotify_client_id, config.spotify_client_secret)
        self.lyrics = LyricsFetcher(config.genius_token)
        self.http: aiohttp.ClientSession | None = None
        self.events = EventBus()
        self.notify = StateNotifier(self.events, self.snapshot)
        self.hooks = PlayerHooks()
        self.make_source = build_source  # swapped out in tests
        self._players: dict[int, GuildPlayer] = {}
        self._inactivity_task: asyncio.Task | None = None
        self._search_cache: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self._search_slot = asyncio.Semaphore(1)  # keep a worker free for playback

    async def start(self):
        await self.settings.initialize()
        await self.cache.initialize()
        self.http = aiohttp.ClientSession()
        self._inactivity_task = asyncio.create_task(self._inactivity_loop())

    async def close(self):
        if self._inactivity_task:
            self._inactivity_task.cancel()
        for guild_id in list(self._players):
            try:
                await self.destroy(guild_id)
            except Exception:
                log.exception("[Guild %d] Error while shutting down the player", guild_id)
        await self.cache.close()
        await self.settings.close()
        if self.http:
            await self.http.close()
        youtube.shutdown()

    # --- Players ---

    def get(self, guild_id: int) -> GuildPlayer:
        player = self._players.get(guild_id)
        if player is None:
            player = GuildPlayer(self, guild_id, self.settings.get(guild_id))
            self._players[guild_id] = player
        return player

    def peek(self, guild_id: int) -> GuildPlayer | None:
        return self._players.get(guild_id)

    def snapshot(self, guild_id: int) -> dict:
        player = self._players.get(guild_id) or GuildPlayer(self, guild_id, self.settings.get(guild_id))
        return player.snapshot()

    async def destroy(self, guild_id: int, *, disconnect: bool = True):
        """The single path for leaving a guild: reset state and optionally disconnect."""
        player = self._players.pop(guild_id, None)
        if player:
            await player.close(disconnect=disconnect)
        elif disconnect:
            guild = self.bot.get_guild(guild_id)
            if guild and guild.voice_client:
                await guild.voice_client.disconnect(force=True)
        self.notify(guild_id)

    # --- Permissions ---

    def dj_role(self, guild: discord.Guild) -> discord.Role | None:
        return discord.utils.get(guild.roles, name=self.config.dj_role)

    def is_dj(self, member: discord.Member) -> bool:
        role = self.dj_role(member.guild)
        return role is None or member.guild_permissions.administrator or role in member.roles

    def can_force_skip(self, member: discord.Member, player: GuildPlayer) -> bool:
        role = self.dj_role(member.guild)
        return (
            member.guild_permissions.administrator
            or (role is not None and role in member.roles)
            or (player.current is not None and player.current.requester_id == member.id)
        )

    def require_dj(self, member: discord.Member | None):
        if member is not None and not self.is_dj(member):
            raise PlayerError(f"You need the {self.config.dj_role} role to do that.")

    # --- Voice ---

    async def join(self, member: discord.Member) -> discord.VoiceClient:
        if not member.voice or not member.voice.channel:
            raise PlayerError("Join a voice channel first.")
        target = member.voice.channel
        guild = member.guild
        vc = guild.voice_client
        player = self.get(guild.id)
        if vc and vc.is_connected():
            if vc.channel != target:
                if player.current and player.listeners():
                    raise PlayerError(f"I'm already playing in {vc.channel.mention}.")
                await vc.move_to(target)
                self.notify(guild.id)
            return vc
        perms = target.permissions_for(guild.me)
        if not (perms.connect and perms.speak):
            raise PlayerError(f"I need permission to connect and speak in {target.mention}.")
        try:
            vc = await target.connect(self_deaf=True, timeout=20)
        except (TimeoutError, discord.ClientException) as e:
            raise PlayerError(f"Couldn't connect to {target.mention}: {short_error(e)}") from e
        player.idle_since = time.monotonic()
        player.alone_since = None
        self.notify(guild.id)
        return vc

    async def _inactivity_loop(self):
        await self.bot.wait_until_ready()
        while True:
            await asyncio.sleep(INACTIVITY_INTERVAL)
            try:
                await self.check_inactivity()
            except Exception:
                log.exception("Inactivity check failed")

    async def check_inactivity(self):
        now = time.monotonic()
        for vc in list(self.bot.voice_clients):
            guild = vc.guild
            player = self.get(guild.id)
            if player.twenty_four_seven:
                continue
            if player.listeners():
                player.alone_since = None
            else:
                player.alone_since = player.alone_since or now
                if now - player.alone_since > self.config.alone_timeout:
                    log.info("[Guild %d] Leaving: nobody listening", guild.id)
                    await self.hooks.notice(player, "👋 Left the voice channel since everyone left.")
                    await self.destroy(guild.id)
                    continue
            if player.current is None and player.idle_since and now - player.idle_since > self.config.idle_timeout:
                log.info("[Guild %d] Leaving: idle for %d min", guild.id, self.config.idle_timeout // 60)
                await self.destroy(guild.id)

    # --- Resolving tracks ---

    async def _extract(self, song: Song) -> youtube.Track:
        query = song.query
        if song.search_music:
            query = await youtube.music_search(song.query) or f"ytsearch1:{song.query}"
        return await youtube.extract_track(query)

    @staticmethod
    def apply_track(song: Song, track: youtube.Track):
        song.track = track
        song.url = track.webpage_url
        song.duration = track.duration or song.duration
        if not song.search_music:  # keep Spotify's cleaner title and album art
            song.title = track.title
            song.thumbnail = track.thumbnail or song.thumbnail

    async def resolve_input(self, song: Song) -> AudioInput:
        """Where to read audio from: the local cache if possible, otherwise a live stream."""
        checked_key = None
        if song.url:
            checked_key = CacheManager.extract_cache_key(song.url)
            entry = await self.cache.lookup(checked_key)
            if entry:
                song.title = song.title if song.search_music else (entry.title or song.title)
                song.duration = entry.duration or song.duration
                song.thumbnail = song.thumbnail or entry.thumbnail
                return AudioInput(entry.path, is_local=True, is_opus=is_opus(entry.acodec, entry.path))

        track = song.track if song.track and song.track.fresh else await self._extract(song)
        self.apply_track(song, track)
        key = CacheManager.extract_cache_key(track.webpage_url)
        if key != checked_key:
            entry = await self.cache.lookup(key)
            if entry:
                return AudioInput(entry.path, is_local=True, is_opus=is_opus(entry.acodec, entry.path))
        if self.cache.cacheable(track.duration, track.is_live):
            self.cache.schedule_download(
                key, track.webpage_url, title=song.title, duration=track.duration, thumbnail=song.thumbnail
            )
        return AudioInput(track.stream_url, is_local=False, is_opus=track.acodec == "opus", user_agent=track.user_agent)

    async def prefetch(self, song: Song) -> bool:
        """Resolve and start caching a queued song ahead of time. Returns True if its metadata changed."""
        if song.url and await self.cache.contains(CacheManager.extract_cache_key(song.url)):
            return False
        changed = False
        if not (song.track and song.track.fresh):
            self.apply_track(song, await self._extract(song))
            changed = True
        track = song.track
        key = CacheManager.extract_cache_key(track.webpage_url)
        if self.cache.cacheable(track.duration, track.is_live) and not await self.cache.contains(key):
            self.cache.schedule_download(key, track.webpage_url, title=song.title,
                                         duration=track.duration, thumbnail=song.thumbnail)
        return changed

    async def resolve_query(self, query: str, requester: Requester) -> tuple[list[Song], str]:
        """Turn user input into songs. Returns (songs, collection label or "")."""
        who = requester.fields()
        query = query.strip().strip("<>")
        if not query:
            raise PlayerError("Type something to play.")

        if SpotifyResolver.is_spotify_url(query):
            if not self.spotify.enabled:
                raise PlayerError("Spotify isn't set up on this bot.")
            try:
                name, tracks = await asyncio.to_thread(self.spotify.resolve, query)
            except Exception as e:
                raise PlayerError(f"Couldn't load that Spotify link: {short_error(e)}") from e
            if not tracks:
                raise PlayerError("That Spotify link has no playable tracks.")
            songs = [
                Song(title=t["title"], query=t["title"], duration=t["duration"], thumbnail=t["thumbnail"],
                     artist=t["artist"], track_name=t["name"], origin_url=t.get("url", ""), search_music=True, **who)
                for t in tracks
            ]
            return songs, name if len(songs) > 1 else ""

        playlist = YOUTUBE_PLAYLIST_RE.search(query)
        # Mixes (list=RD…) are endless auto-generated radios: just play the linked video
        if playlist and not (playlist.group(2).startswith("RD") and "v=" in query):
            try:
                entries = await youtube.extract_playlist(query)
            except Exception as e:
                raise PlayerError(f"Couldn't load that playlist: {short_error(e)}") from e
            if not entries:
                raise PlayerError("That playlist is empty or private.")
            songs = [
                Song(title=e["title"], query=e["url"], url=e["url"], duration=e["duration"],
                     thumbnail=e["thumbnail"], **who)
                for e in entries
            ]
            return songs, "YouTube playlist"

        # Single track: resolve now so the queue shows real metadata and errors surface immediately
        is_url = bool(URL_RE.match(query))
        if is_url:
            entry = await self.cache.lookup(CacheManager.extract_cache_key(query))
            if entry:
                return [Song(title=entry.title or query, query=query, url=query, duration=entry.duration,
                             thumbnail=entry.thumbnail, **who)], ""
        try:
            track = await youtube.extract_track(query if is_url else f"ytsearch1:{query}")
        except LookupError as e:
            raise PlayerError(str(e)) from e
        except Exception as e:
            raise PlayerError(f"Couldn't load that: {short_error(e)}") from e
        song = Song(title=track.title, query=query, **who)
        self.apply_track(song, track)
        return [song], ""

    # --- Dashboard helpers ---

    async def search(self, query: str) -> dict:
        """Spotify songs and albums plus YouTube videos, cached briefly."""
        key = query.strip().lower()
        hit = self._search_cache.get(key)
        if hit and time.monotonic() - hit[0] < SEARCH_TTL:
            return hit[1]

        async def spotify():
            if not self.spotify.enabled:
                return {"songs": [], "albums": []}
            # Don't let a slow Spotify API hold up the YouTube results
            return await asyncio.wait_for(asyncio.to_thread(self.spotify.search, query, 5, 2), timeout=4)

        async def videos():
            async with self._search_slot:
                return await youtube.search(query, count=6)

        found_videos, found = await asyncio.gather(videos(), spotify(), return_exceptions=True)
        failed = False
        for name, result in (("YouTube", found_videos), ("Spotify", found)):
            if isinstance(result, BaseException):
                failed = True
                log.warning("%s search failed for %r: %r", name, query, result)
        found = found if isinstance(found, dict) else {"songs": [], "albums": []}
        result = {
            "songs": found["songs"],
            "albums": found["albums"],
            "videos": found_videos if isinstance(found_videos, list) else [],
        }
        if not failed:
            self._search_cache[key] = (time.monotonic(), result)
            while len(self._search_cache) > 200:
                self._search_cache.popitem(last=False)
        return result

    async def lyrics_for(self, song: Song) -> Lyrics | None:
        return await self.lyrics.fetch(
            self.http, song.title, artist=song.artist, track=song.track_name, duration=song.duration
        )
