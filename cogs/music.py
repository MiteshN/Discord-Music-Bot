import asyncio
import itertools
import logging
import os
import re
import time
from typing import Literal

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils import youtube
from utils.audio import AudioInput, build_source, get_filter
from utils.cache import CacheManager
from utils.lyrics import LyricsFetcher
from utils.queue_manager import GuildQueue, LoopMode, QueueManager, Song
from utils.settings import GuildSettings
from utils.spotify import SpotifyResolver

log = logging.getLogger("bot.music")

URL_RE = re.compile(r"^https?://", re.IGNORECASE)
YOUTUBE_PLAYLIST_RE = re.compile(r"(youtube\.com/.*[?&]list=|youtu\.be/.*[?&]list=)([\w-]+)")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "")

ACCENT = discord.Color(0x8B5CF6)
IDLE_TIMEOUT = 600  # leave after 10 min with nothing playing
ALONE_TIMEOUT = 180  # leave after 3 min with nobody listening
QUEUE_PAGE_SIZE = 10
STATE_QUEUE_LIMIT = 200  # queue entries sent to the dashboard per update


class PlayerError(Exception):
    """A user-facing error. The message is shown as-is."""


def format_duration(seconds: float) -> str:
    seconds = max(int(seconds), 0)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def parse_timestamp(ts: str) -> int:
    parts = [int(p) for p in ts.strip().split(":")]
    if not 1 <= len(parts) <= 3 or any(p < 0 for p in parts) or any(p >= 60 for p in parts[1:]):
        raise ValueError(ts)
    seconds = 0
    for p in parts:
        seconds = seconds * 60 + p
    return seconds


def song_length(song: Song) -> str:
    if song.track and song.track.is_live:
        return "🔴 Live"
    return format_duration(song.duration) if song.duration else "?"


def progress_bar(position: float, duration: int, length: int = 16) -> str:
    if duration <= 0:
        return f"🔴 Live · `{format_duration(position)}`"
    filled = min(int(length * position / duration), length)
    return f"`{format_duration(position)}` {'▰' * filled}{'▱' * (length - filled)} `{format_duration(duration)}`"


def md_link(song: Song, limit: int = 80) -> str:
    title = discord.utils.escape_markdown(song.title).replace("[", "(").replace("]", ")")
    if len(title) > limit:
        title = title[: limit - 1] + "…"
    return f"[{title}]({song.url})" if song.url else f"**{title}**"


def short_error(e: Exception) -> str:
    msg = str(e).replace("ERROR: ", "").strip() or type(e).__name__
    return msg[:200]


# --- Views ---


class NowPlayingView(discord.ui.View):
    def __init__(self, cog: "Music", guild_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        self.message: discord.PartialMessage | None = None
        if DASHBOARD_URL:
            self.add_item(discord.ui.Button(label="Dashboard", emoji="🎛️", url=DASHBOARD_URL, row=1))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        vc = interaction.guild.voice_client
        voice = interaction.user.voice
        if vc and voice and voice.channel == vc.channel:
            return True
        await interaction.response.send_message("Join my voice channel to use these controls.", ephemeral=True)
        return False

    async def _run(self, interaction: discord.Interaction, action):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            message = await action
        except PlayerError as e:
            message = str(e)
        await interaction.followup.send(message, ephemeral=True)

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary, row=0)
    async def previous_button(self, interaction: discord.Interaction, _):
        await self._run(interaction, self.cog.previous(interaction.guild))

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.primary, row=0)
    async def pause_button(self, interaction: discord.Interaction, _):
        await self._run(interaction, self.cog.toggle_pause(interaction.guild))

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, row=0)
    async def skip_button(self, interaction: discord.Interaction, _):
        await self._run(interaction, self.cog.skip(interaction.guild, interaction.user))

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, row=0)
    async def stop_button(self, interaction: discord.Interaction, _):
        await self._run(interaction, self.cog.stop_player(interaction.guild, interaction.user))

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, row=1)
    async def loop_button(self, interaction: discord.Interaction, _):
        await self._run(interaction, self.cog.set_loop(interaction.guild, None))

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary, row=1)
    async def shuffle_button(self, interaction: discord.Interaction, _):
        await self._run(interaction, self.cog.shuffle(interaction.guild, interaction.user))


class SearchSelectView(discord.ui.View):
    def __init__(self, cog: "Music", author: discord.Member, results: list[dict]):
        super().__init__(timeout=60)
        self.cog = cog
        self.author = author
        self.results = results
        self.message: discord.Message | None = None
        self.select = discord.ui.Select(
            placeholder="Pick a track…",
            options=[
                discord.SelectOption(
                    label=r["title"][:100],
                    description=format_duration(r["duration"]),
                    value=str(i),
                    emoji=["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"][i] if i < 5 else None,
                )
                for i, r in enumerate(results)
            ],
        )
        self.select.callback = self._on_select
        self.add_item(self.select)

    async def _on_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("This isn't your search.", ephemeral=True)
            return
        await interaction.response.defer()
        self.stop()
        chosen = self.results[int(self.select.values[0])]
        song = Song(
            title=chosen["title"],
            query=chosen["url"],
            url=chosen["url"],
            requester=interaction.user.display_name,
            requester_id=interaction.user.id,
            duration=chosen["duration"],
            thumbnail=chosen["thumbnail"],
        )
        try:
            await self.cog.join(interaction.user)
            await self.cog.enqueue_and_reply(
                interaction.guild, [song], "", channel_id=interaction.channel_id,
                send=lambda **kw: interaction.followup.send(wait=True, **kw),
            )
        except PlayerError as e:
            await interaction.followup.send(str(e), ephemeral=True)
        await interaction.edit_original_response(view=None)

    async def on_timeout(self):
        if self.message:
            self.select.disabled = True
            self.select.placeholder = "Search timed out"
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


# --- Cog ---


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = GuildSettings()
        self.queues = QueueManager(self.settings)
        self.cache = CacheManager()
        self.spotify = SpotifyResolver()
        self.lyrics_fetcher = LyricsFetcher()
        self.http: aiohttp.ClientSession | None = None
        self._prefetch_tasks: dict[int, asyncio.Task] = {}
        self._pending_notify: set[int] = set()

    async def cog_load(self):
        await self.settings.initialize()
        await self.cache.initialize()
        self.http = aiohttp.ClientSession()
        self.inactivity_check.start()
        log.info("Music cog loaded")

    async def cog_unload(self):
        self.inactivity_check.cancel()
        for guild in [vc.guild for vc in self.bot.voice_clients]:
            await self._teardown(guild)
        for task in self._prefetch_tasks.values():
            task.cancel()
        await self.cache.close()
        await self.settings.close()
        if self.http:
            await self.http.close()
        youtube.shutdown()

    async def cog_check(self, ctx: commands.Context) -> bool:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        return True

    async def cog_command_error(self, ctx: commands.Context, error: Exception):
        while isinstance(error, (commands.CommandInvokeError, commands.HybridCommandError, app_commands.CommandInvokeError)):
            error = error.original
        if isinstance(error, PlayerError):
            message = str(error)
        elif isinstance(error, commands.MissingRequiredArgument):
            message = f"Missing `{error.param.name}`. Usage: `{ctx.clean_prefix}{ctx.command.qualified_name} {ctx.command.signature}`"
        elif isinstance(error, (commands.BadArgument, commands.BadLiteralArgument, app_commands.TransformerError)):
            message = f"Invalid argument: {error}"
        elif isinstance(error, commands.NoPrivateMessage):
            message = "Music commands only work in servers."
        elif isinstance(error, commands.CheckFailure):
            message = "You can't use that here."
        else:
            log.error("Error in command %s", ctx.command, exc_info=error)
            message = "Something went wrong running that command."
        try:
            await ctx.send(f"⚠️ {message}", ephemeral=True)
        except discord.HTTPException:
            pass

    # --- Dashboard state ---

    def player_state(self, guild_id: int) -> dict:
        gq = self.queues.peek(guild_id)
        guild = self.bot.get_guild(guild_id)
        vc = guild.voice_client if guild else None
        in_voice = vc is not None and vc.is_connected()
        if gq is None:
            saved = self.settings.get(guild_id)
            gq = GuildQueue(volume=saved["volume"], twenty_four_seven=saved["twenty_four_seven"])
        return {
            "current": gq.current.to_dict() if gq.current else None,
            "elapsed": gq.position if gq.current else 0,
            "rate": gq.rate,
            "paused": in_voice and vc.is_paused(),
            "playing": in_voice and vc.is_playing(),
            "volume": round(gq.volume * 100),
            "loop": gq.loop_mode.value,
            "filter": gq.audio_filter.label if gq.audio_filter else "",
            "filter_key": gq.audio_filter.key if gq.audio_filter else "",
            "queue": [s.to_dict() for s in itertools.islice(gq.queue, STATE_QUEUE_LIMIT)],
            "queue_length": len(gq.queue),
            "queue_duration": sum(s.duration for s in gq.queue),
            "has_previous": bool(gq.history),
            "twenty_four_seven": gq.twenty_four_seven,
            "in_voice": in_voice,
            "channel": vc.channel.name if in_voice else None,
            "timestamp": time.time(),
        }

    def _notify(self, guild_id: int):
        """Push fresh state to dashboard viewers. Bursts of changes are coalesced into one update."""
        bus = getattr(self.bot, "_dashboard_event_bus", None)
        if not bus or not bus.has_subscribers(guild_id) or guild_id in self._pending_notify:
            return
        self._pending_notify.add(guild_id)

        def flush():
            self._pending_notify.discard(guild_id)
            bus.publish(guild_id, "state", self.player_state(guild_id))

        asyncio.get_running_loop().call_later(0.05, flush)

    # --- Permissions / voice helpers ---

    @staticmethod
    def is_dj(member: discord.Member) -> bool:
        dj_role = discord.utils.get(member.guild.roles, name="DJ")
        return dj_role is None or member.guild_permissions.administrator or dj_role in member.roles

    @staticmethod
    def _can_force_skip(member: discord.Member, gq: GuildQueue) -> bool:
        dj_role = discord.utils.get(member.guild.roles, name="DJ")
        return (
            member.guild_permissions.administrator
            or (dj_role is not None and dj_role in member.roles)
            or (gq.current is not None and gq.current.requester_id == member.id)
        )

    def require_dj(self, member: discord.Member | None):
        if member is not None and not self.is_dj(member):
            raise PlayerError("You need the DJ role to do that.")

    @staticmethod
    def _listeners(vc: discord.VoiceClient) -> list[discord.Member]:
        return [m for m in vc.channel.members if not m.bot]

    def _require_listener(self, ctx: commands.Context) -> discord.VoiceClient:
        vc = ctx.voice_client
        if not vc or not vc.is_connected():
            raise PlayerError("I'm not in a voice channel.")
        if not ctx.author.voice or ctx.author.voice.channel != vc.channel:
            raise PlayerError(f"Join {vc.channel.mention} to control playback.")
        return vc

    def _playing_vc(self, guild: discord.Guild) -> discord.VoiceClient:
        vc = guild.voice_client
        if not vc or not (vc.is_playing() or vc.is_paused()):
            raise PlayerError("Nothing is playing.")
        return vc

    async def join(self, member: discord.Member) -> discord.VoiceClient:
        if not member.voice or not member.voice.channel:
            raise PlayerError("Join a voice channel first.")
        target = member.voice.channel
        vc = member.guild.voice_client
        gq = self.queues.get(member.guild.id)
        if vc and vc.is_connected():
            if vc.channel != target:
                if gq.current and self._listeners(vc):
                    raise PlayerError(f"I'm already playing in {vc.channel.mention}.")
                await vc.move_to(target)
            return vc
        perms = target.permissions_for(member.guild.me)
        if not (perms.connect and perms.speak):
            raise PlayerError(f"I need permission to connect and speak in {target.mention}.")
        try:
            vc = await target.connect(self_deaf=True, timeout=20)
        except (asyncio.TimeoutError, discord.ClientException) as e:
            raise PlayerError(f"Couldn't connect to {target.mention}: {short_error(e)}")
        gq.idle_since = time.monotonic()
        gq.alone_since = None
        return vc

    async def _set_status(self, guild: discord.Guild, song: Song | None):
        vc = guild.voice_client
        if not vc:
            return
        status = f"🎵 {song.title}"[:500] if song else None
        try:
            await vc.channel.edit(status=status)
        except (discord.HTTPException, AttributeError):
            pass

    def _text_channel(self, guild: discord.Guild, gq: GuildQueue):
        channel = guild.get_channel(gq.text_channel_id) if gq.text_channel_id else None
        if channel is None and guild.voice_client:
            channel = guild.voice_client.channel  # voice channels have a built-in text chat
        return channel

    async def _send(self, guild: discord.Guild, gq: GuildQueue, content: str):
        channel = self._text_channel(guild, gq)
        if channel:
            try:
                await channel.send(content)
            except discord.HTTPException:
                pass

    # --- Resolving tracks ---

    async def _extract(self, song: Song) -> youtube.Track:
        query = song.query
        if song.search_music:
            query = await youtube.music_search(song.query) or f"ytsearch1:{song.query}"
        return await youtube.extract_track(query)

    @staticmethod
    def _apply_track(song: Song, track: youtube.Track):
        song.track = track
        song.url = track.webpage_url
        song.duration = track.duration or song.duration
        if not song.search_music:  # keep Spotify's cleaner title and album art
            song.title = track.title
            song.thumbnail = track.thumbnail or song.thumbnail

    async def _resolve_input(self, song: Song) -> AudioInput:
        """Where to read audio from: the local cache if possible, otherwise a live stream."""
        checked_key = None
        if song.url:
            checked_key = CacheManager.extract_cache_key(song.url)
            entry = await self.cache.lookup(checked_key)
            if entry:
                song.title = song.title if song.search_music else (entry.title or song.title)
                song.duration = entry.duration or song.duration
                song.thumbnail = song.thumbnail or entry.thumbnail
                return AudioInput(entry.path, is_local=True, is_opus=_is_opus(entry.acodec, entry.path))

        track = song.track if song.track and song.track.fresh else await self._extract(song)
        self._apply_track(song, track)
        key = CacheManager.extract_cache_key(track.webpage_url)
        if key != checked_key:
            entry = await self.cache.lookup(key)
            if entry:
                return AudioInput(entry.path, is_local=True, is_opus=_is_opus(entry.acodec, entry.path))
        if self.cache.cacheable(track.duration, track.is_live):
            self.cache.schedule_download(
                key, track.webpage_url, title=song.title, duration=track.duration, thumbnail=song.thumbnail
            )
        return AudioInput(track.stream_url, is_local=False, is_opus=track.acodec == "opus", user_agent=track.user_agent)

    async def resolve_query(self, query: str, requester: str, requester_id: int) -> tuple[list[Song], str]:
        """Turn user input into songs. Returns (songs, collection label or "")."""
        requester = {"requester": requester, "requester_id": requester_id}
        query = query.strip().strip("<>")

        if SpotifyResolver.is_spotify_url(query):
            if not self.spotify.sp:
                raise PlayerError("Spotify isn't configured on this bot.")
            try:
                name, tracks = await asyncio.to_thread(self.spotify.resolve, query)
            except Exception as e:
                raise PlayerError(f"Couldn't load that Spotify link: {short_error(e)}")
            if not tracks:
                raise PlayerError("That Spotify link has no playable tracks.")
            songs = [
                Song(title=t["title"], query=t["title"], duration=t["duration"], thumbnail=t["thumbnail"],
                     search_music=True, **requester)
                for t in tracks
            ]
            return songs, name if len(songs) > 1 else ""

        playlist = YOUTUBE_PLAYLIST_RE.search(query)
        # Mixes (list=RD…) are endless auto-generated radios: just play the linked video
        if playlist and not (playlist.group(2).startswith("RD") and "v=" in query):
            try:
                entries = await youtube.extract_playlist(query)
            except Exception as e:
                raise PlayerError(f"Couldn't load that playlist: {short_error(e)}")
            if not entries:
                raise PlayerError("That playlist is empty or private.")
            songs = [
                Song(title=e["title"], query=e["url"], url=e["url"], duration=e["duration"],
                     thumbnail=e["thumbnail"], **requester)
                for e in entries
            ]
            return songs, "YouTube playlist"

        # Single track: resolve now so the queue shows real metadata and errors surface immediately
        if URL_RE.match(query):
            entry = await self.cache.lookup(CacheManager.extract_cache_key(query))
            if entry:
                return [Song(title=entry.title or query, query=query, url=query, duration=entry.duration,
                             thumbnail=entry.thumbnail, **requester)], ""
        try:
            track = await youtube.extract_track(query if URL_RE.match(query) else f"ytsearch1:{query}")
        except LookupError as e:
            raise PlayerError(str(e))
        except Exception as e:
            raise PlayerError(f"Couldn't load that: {short_error(e)}")
        song = Song(title=track.title, query=query, **requester)
        self._apply_track(song, track)
        return [song], ""

    # --- Playback engine ---
    # All of these run with gq.lock held.

    async def _start_locked(self, guild: discord.Guild, gq: GuildQueue, song: Song, position: float = 0) -> bool:
        try:
            inp = await self._resolve_input(song)
        except Exception as e:
            log.warning("[Guild %d] Couldn't resolve %r: %s", guild.id, song.title, e)
            await self._send(guild, gq, f"⚠️ Couldn't play **{discord.utils.escape_markdown(song.title)}**: {short_error(e)}")
            return False

        vc = guild.voice_client
        if not vc or not vc.is_connected() or self.queues.peek(guild.id) is not gq or gq.current is not song:
            return False  # torn down or superseded while resolving

        try:
            source = build_source(inp, volume=gq.volume, audio_filter=gq.audio_filter,
                                  position=position, bitrate=_bitrate(vc))
        except discord.ClientException as e:
            log.error("[Guild %d] FFmpeg failed to start: %s", guild.id, e)
            await self._send(guild, gq, f"⚠️ Audio engine error: {short_error(e)}")
            return False

        gq.audio_input = inp
        self._play_source(guild.id, gq, vc, source)
        gq.mark_playing(position)
        log.info("[Guild %d] Playing %s (%s, %s, %s)", guild.id, song.title, format_duration(song.duration),
                 "cache" if inp.is_local else "stream", "passthrough" if source.passthrough else "transcode")
        return True

    def _play_source(self, guild_id: int, gq: GuildQueue, vc: discord.VoiceClient, source):
        gq.play_id += 1
        token = gq.play_id
        loop = self.bot.loop

        def after(error):
            if error:
                log.error("[Guild %d] Player error: %s", guild_id, error)
            if not loop.is_closed():
                asyncio.run_coroutine_threadsafe(self._on_track_end(guild_id, token), loop)

        if vc.is_playing() or vc.is_paused():
            vc.stop()
        vc.play(source, after=after)

    async def _on_track_end(self, guild_id: int, token: int):
        gq = self.queues.peek(guild_id)
        guild = self.bot.get_guild(guild_id)
        if not gq or not guild:
            return
        async with gq.lock:
            if gq.play_id != token:
                return  # superseded by a skip/seek/filter change
            song = gq.current
            # A track that dies within 2s never really played: don't loop it forever
            failed = song is not None and gq.position < 2 and song.duration > 5
            if failed:
                song.track = None  # force a fresh extraction if it's retried later
                await self._send(guild, gq, f"⚠️ Playback of **{discord.utils.escape_markdown(song.title)}** failed, skipping.")
            await self._play_from(guild, gq, gq.advance(failed=failed))

    async def _play_from(self, guild: discord.Guild, gq: GuildQueue, song: Song | None, *, announce: bool = True):
        while song:
            if await self._start_locked(guild, gq, song):
                if announce:
                    await self._announce(guild, gq)
                self._schedule_prefetch(guild.id)
                self._notify(guild.id)
                await self._set_status(guild, song)
                return song
            if self.queues.peek(guild.id) is not gq or not guild.voice_client:
                return None
            song = gq.advance(failed=True)

        gq.mark_idle()
        await self._retire_now_playing(gq)
        await self._set_status(guild, None)
        self._notify(guild.id)
        return None

    def _schedule_prefetch(self, guild_id: int):
        old = self._prefetch_tasks.pop(guild_id, None)
        if old:
            old.cancel()
        self._prefetch_tasks[guild_id] = asyncio.create_task(self._prefetch(guild_id))

    async def _prefetch(self, guild_id: int):
        """Resolve (and cache) the next song while this one plays, so it starts instantly."""
        await asyncio.sleep(3)  # let the current track settle first
        gq = self.queues.peek(guild_id)
        if not gq or not gq.queue or gq.loop_mode is LoopMode.TRACK:
            return
        song = gq.queue[0]
        try:
            if song.url and await self.cache.contains(CacheManager.extract_cache_key(song.url)):
                return
            if not (song.track and song.track.fresh):
                self._apply_track(song, await self._extract(song))
                self._notify(guild_id)
            track = song.track
            key = CacheManager.extract_cache_key(track.webpage_url)
            if self.cache.cacheable(track.duration, track.is_live) and not await self.cache.contains(key):
                self.cache.schedule_download(key, track.webpage_url, title=song.title,
                                             duration=track.duration, thumbnail=song.thumbnail)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.debug("[Guild %d] Prefetch failed for %r: %s", guild_id, song.title, e)

    async def _restart_locked(self, guild: discord.Guild, gq: GuildQueue, position: float):
        """Restart the current track at a position, e.g. after a seek, volume or filter change."""
        vc = guild.voice_client
        if not gq.current or not vc or not (vc.is_playing() or vc.is_paused()):
            return
        inp = gq.audio_input
        if inp is None or not inp.is_local:
            # Picks up the cached file if its background download has finished,
            # otherwise reuses the resolved stream (no yt-dlp call while it's fresh)
            inp = await self._resolve_input(gq.current)
        source = build_source(inp, volume=gq.volume, audio_filter=gq.audio_filter,
                              position=position, bitrate=_bitrate(vc))
        was_paused = vc.is_paused()  # checked after the await so a pause made meanwhile sticks
        gq.audio_input = inp
        self._play_source(guild.id, gq, vc, source)
        gq.mark_playing(position)
        if was_paused:
            vc.pause()
            gq.mark_paused()
        self._notify(guild.id)

    async def _teardown(self, guild: discord.Guild, *, disconnect: bool = True):
        """The single path for leaving a guild: reset state and optionally disconnect."""
        task = self._prefetch_tasks.pop(guild.id, None)
        if task:
            task.cancel()
        gq = self.queues.peek(guild.id)
        if gq:
            gq.play_id += 1  # ignore the callback from stopping playback
            self.queues.remove(guild.id)
            await self._retire_now_playing(gq)
        vc = guild.voice_client
        if vc:
            await self._set_status(guild, None)
            if disconnect:
                vc.stop()
                await vc.disconnect(force=True)
        self._notify(guild.id)

    # --- Now-playing message ---

    def _now_playing_embed(self, gq: GuildQueue) -> discord.Embed:
        song = gq.current
        embed = discord.Embed(description=f"### {md_link(song, 200)}", color=ACCENT)
        embed.set_author(name="Now playing")
        if song.thumbnail:
            embed.set_thumbnail(url=song.thumbnail)
        embed.add_field(name="Duration", value=song_length(song))
        embed.add_field(name="Requested by", value=song.requester)
        if gq.queue:
            embed.add_field(name="Up next", value=md_link(gq.queue[0], 60), inline=False)
        footer = [f"Volume {round(gq.volume * 100)}%"]
        if gq.loop_mode is not LoopMode.OFF:
            footer.append(f"Loop: {gq.loop_mode.value}")
        if gq.audio_filter:
            footer.append(f"Effect: {gq.audio_filter.label}")
        if gq.queue:
            footer.append(f"{len(gq.queue)} in queue")
        embed.set_footer(text=" · ".join(footer))
        return embed

    async def _announce(self, guild: discord.Guild, gq: GuildQueue, send=None):
        await self._retire_now_playing(gq)
        if send is None:
            channel = self._text_channel(guild, gq)
            if channel is None:
                return
            send = channel.send
        view = NowPlayingView(self, guild.id)
        try:
            message = await send(embed=self._now_playing_embed(gq), view=view)
        except discord.HTTPException as e:
            log.warning("[Guild %d] Couldn't send now-playing message: %s", guild.id, e)
            view.stop()
            return
        # Keep a partial message: interaction followups can't be edited after 15 min via their token
        view.message = message.channel.get_partial_message(message.id)
        gq.np_view = view

    async def _retire_now_playing(self, gq: GuildQueue):
        """Remove the buttons from the previous now-playing message."""
        view, gq.np_view = gq.np_view, None
        if view is None:
            return
        view.stop()
        if view.message:
            try:
                await view.message.edit(view=None)
            except discord.HTTPException:
                pass

    # --- Actions shared by commands, buttons and the dashboard ---
    # Each returns a message for the user or raises PlayerError.

    async def enqueue(self, guild: discord.Guild, songs: list[Song], *, top: bool = False,
                      channel_id: int | None = None, announce: bool = True) -> Song | None:
        """Add songs and start playback if idle. Returns the song that started playing, if any."""
        gq = self.queues.get(guild.id)
        if channel_id:
            gq.text_channel_id = channel_id
        gq.add(songs, top=top)
        started = None
        async with gq.lock:
            if gq.current is None and guild.voice_client:
                started = await self._play_from(guild, gq, gq.advance(), announce=announce)
        if not started:
            self._notify(guild.id)
            if len(gq.queue) == len(songs) or top:
                self._schedule_prefetch(guild.id)
        return started

    async def enqueue_and_reply(self, guild: discord.Guild, songs: list[Song], label: str, *,
                                channel_id: int, send, top: bool = False):
        gq = self.queues.get(guild.id)
        started = await self.enqueue(guild, songs, top=top, channel_id=channel_id, announce=False)
        if started and len(songs) == 1:
            await self._announce(guild, gq, send=send)
            return
        if gq.current is None:
            raise PlayerError("Couldn't start playback.")
        await send(embed=self._added_embed(gq, songs, label, top))
        if started:
            await self._announce(guild, gq)

    def _added_embed(self, gq: GuildQueue, songs: list[Song], label: str, top: bool) -> discord.Embed:
        if len(songs) == 1:
            song = songs[0]
            position = 1 if top else len(gq.queue)
            embed = discord.Embed(description=f"Added {md_link(song)} to the queue", color=ACCENT)
            if song.thumbnail:
                embed.set_thumbnail(url=song.thumbnail)
            embed.add_field(name="Position", value=f"#{position}")
            embed.add_field(name="Duration", value=song_length(song))
            if gq.current and gq.current.duration:
                ahead = list(itertools.islice(gq.queue, position - 1))
                wait = max(gq.current.duration - gq.position, 0) + sum(s.duration for s in ahead)
                embed.add_field(name="Plays in", value=f"~{format_duration(wait)}")
            return embed
        total = sum(s.duration for s in songs)
        where = "the top of the queue" if top else "the queue"
        source = f" from **{discord.utils.escape_markdown(label)}**" if label else ""
        embed = discord.Embed(description=f"Added **{len(songs)}** tracks{source} to {where}", color=ACCENT)
        if total:
            embed.set_footer(text=f"Total length {format_duration(total)}")
        return embed

    async def toggle_pause(self, guild: discord.Guild) -> str:
        vc = self._playing_vc(guild)
        gq = self.queues.get(guild.id)
        if vc.is_paused():
            vc.resume()
            gq.mark_resumed()
            message = "▶️ Resumed."
        else:
            vc.pause()
            gq.mark_paused()
            message = "⏸️ Paused."
        self._notify(guild.id)
        return message

    async def pause(self, guild: discord.Guild) -> str:
        if not self._playing_vc(guild).is_playing():
            raise PlayerError("Already paused.")
        return await self.toggle_pause(guild)

    async def resume(self, guild: discord.Guild) -> str:
        if not self._playing_vc(guild).is_paused():
            raise PlayerError("Nothing is paused.")
        return await self.toggle_pause(guild)

    async def skip(self, guild: discord.Guild, member: discord.Member | None = None) -> str:
        vc = self._playing_vc(guild)
        gq = self.queues.get(guild.id)
        # DJs, the song's requester, and small audiences skip instantly; everyone else votes
        if member is not None and not self._can_force_skip(member, gq):
            listeners = {m.id for m in self._listeners(vc)}
            if len(listeners) > 2:
                gq.skip_votes.add(member.id)
                gq.skip_votes &= listeners
                needed = len(listeners) // 2 + 1
                if len(gq.skip_votes) < needed:
                    return f"🗳️ Vote to skip: **{len(gq.skip_votes)}/{needed}**"
        skipped = gq.current
        async with gq.lock:
            gq.play_id += 1
            vc.stop()
            await self._play_from(guild, gq, gq.advance(skipping=True))
        return f"⏭️ Skipped **{discord.utils.escape_markdown(skipped.title)}**." if skipped else "⏭️ Skipped."

    async def previous(self, guild: discord.Guild) -> str:
        gq = self.queues.get(guild.id)
        if not guild.voice_client:
            raise PlayerError("I'm not in a voice channel.")
        async with gq.lock:
            song = gq.rewind()
            if not song:
                raise PlayerError("There's no previous track.")
            gq.play_id += 1
            guild.voice_client.stop()
            await self._play_from(guild, gq, song)
        return f"⏮️ Back to **{discord.utils.escape_markdown(song.title)}**."

    async def stop_player(self, guild: discord.Guild, member: discord.Member | None = None) -> str:
        self.require_dj(member)
        if not guild.voice_client:
            raise PlayerError("I'm not in a voice channel.")
        await self._teardown(guild)
        return "⏹️ Stopped and disconnected."

    async def seek(self, guild: discord.Guild, seconds: int) -> str:
        self._playing_vc(guild)
        gq = self.queues.get(guild.id)
        if not gq.current or gq.current.duration <= 0:
            raise PlayerError("This track can't be seeked.")
        if not 0 <= seconds < gq.current.duration:
            raise PlayerError(f"Position must be between 0:00 and {format_duration(gq.current.duration)}.")
        async with gq.lock:
            await self._restart_locked(guild, gq, seconds)
        return f"⏩ Seeked to **{format_duration(seconds)}**."

    async def set_volume(self, guild: discord.Guild, volume: int, member: discord.Member | None = None) -> str:
        self.require_dj(member)
        if not 0 <= volume <= 100:
            raise PlayerError("Volume must be between 0 and 100.")
        gq = self.queues.get(guild.id)
        async with gq.lock:
            position = gq.position
            gq.volume = volume / 100
            await self._restart_locked(guild, gq, position)
        await self.settings.save(guild.id, gq.volume, gq.twenty_four_seven)
        self._notify(guild.id)
        return f"🔊 Volume set to **{volume}%**."

    async def set_loop(self, guild: discord.Guild, mode: str | None) -> str:
        gq = self.queues.get(guild.id)
        if mode is None:
            cycle = [LoopMode.OFF, LoopMode.TRACK, LoopMode.QUEUE]
            gq.loop_mode = cycle[(cycle.index(gq.loop_mode) + 1) % len(cycle)]
        else:
            try:
                gq.loop_mode = LoopMode(mode)
            except ValueError:
                raise PlayerError("Loop mode must be `off`, `track`, or `queue`.")
        self._notify(guild.id)
        icons = {LoopMode.OFF: "➡️", LoopMode.TRACK: "🔂", LoopMode.QUEUE: "🔁"}
        return f"{icons[gq.loop_mode]} Loop: **{gq.loop_mode.value}**."

    async def set_filter(self, guild: discord.Guild, key: str) -> str:
        try:
            audio_filter = None if key in ("", "clear", "none") else get_filter(key)
        except ValueError as e:
            raise PlayerError(str(e))
        if key not in ("", "clear", "none") and audio_filter is None:
            raise PlayerError(f"Unknown effect `{key}`.")
        gq = self.queues.get(guild.id)
        async with gq.lock:
            position = gq.position  # measured at the old playback rate
            gq.audio_filter = audio_filter
            await self._restart_locked(guild, gq, position)
        self._notify(guild.id)
        return f"🎚️ Effect: **{audio_filter.label}**." if audio_filter else "🎚️ Effects cleared."

    async def shuffle(self, guild: discord.Guild, member: discord.Member | None = None) -> str:
        self.require_dj(member)
        gq = self.queues.get(guild.id)
        if len(gq.queue) < 2:
            raise PlayerError("Not enough songs in the queue to shuffle.")
        gq.shuffle()
        self._schedule_prefetch(guild.id)
        self._notify(guild.id)
        return f"🔀 Shuffled **{len(gq.queue)}** tracks."

    async def remove(self, guild: discord.Guild, index: int, member: discord.Member | None = None) -> str:
        self.require_dj(member)
        gq = self.queues.get(guild.id)
        removed = gq.remove(index)
        if not removed:
            raise PlayerError("There's no song at that position.")
        if index == 0:
            self._schedule_prefetch(guild.id)
        self._notify(guild.id)
        return f"🗑️ Removed **{discord.utils.escape_markdown(removed.title)}**."

    async def move(self, guild: discord.Guild, from_idx: int, to_idx: int, member: discord.Member | None = None) -> str:
        self.require_dj(member)
        gq = self.queues.get(guild.id)
        if not gq.move(from_idx, to_idx):
            raise PlayerError("Invalid positions.")
        if 0 in (from_idx, to_idx):
            self._schedule_prefetch(guild.id)
        self._notify(guild.id)
        return f"↕️ Moved to position **{to_idx + 1}**."

    async def clear_queue(self, guild: discord.Guild, member: discord.Member | None = None) -> str:
        self.require_dj(member)
        gq = self.queues.get(guild.id)
        count = len(gq.queue)
        gq.queue.clear()
        self._notify(guild.id)
        return f"🧹 Cleared **{count}** tracks from the queue."

    async def set_247(self, guild: discord.Guild, enabled: bool, member: discord.Member | None = None) -> str:
        self.require_dj(member)
        gq = self.queues.get(guild.id)
        gq.twenty_four_seven = enabled
        await self.settings.save(guild.id, gq.volume, enabled)
        self._notify(guild.id)
        return "🌙 24/7 mode **on**: I'll stay in voice." if enabled else "24/7 mode **off**: I'll leave when idle."

    # --- Background tasks & events ---

    @tasks.loop(seconds=30)
    async def inactivity_check(self):
        now = time.monotonic()
        for vc in list(self.bot.voice_clients):
            guild = vc.guild
            gq = self.queues.get(guild.id)
            if gq.twenty_four_seven:
                continue
            if self._listeners(vc):
                gq.alone_since = None
            else:
                gq.alone_since = gq.alone_since or now
                if now - gq.alone_since > ALONE_TIMEOUT:
                    log.info("[Guild %d] Leaving: nobody listening", guild.id)
                    await self._send(guild, gq, "👋 Left the voice channel since everyone left.")
                    await self._teardown(guild)
                    continue
            if gq.current is None and gq.idle_since and now - gq.idle_since > IDLE_TIMEOUT:
                log.info("[Guild %d] Leaving: idle for %d min", guild.id, IDLE_TIMEOUT // 60)
                await self._teardown(guild)

    @inactivity_check.before_loop
    async def _before_inactivity_check(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        # Kicked or disconnected by someone else: drop the stale player state
        if member.id == self.bot.user.id and before.channel and after.channel is None:
            await self._teardown(member.guild, disconnect=False)

    # --- Autocomplete ---

    async def _youtube_suggestions(self, query: str) -> list[str]:
        async with self.http.get(
            "https://suggestqueries.google.com/complete/search",
            params={"client": "firefox", "ds": "yt", "q": query},
            timeout=aiohttp.ClientTimeout(total=2),
        ) as resp:
            data = await resp.json(content_type=None)
            return data[1] if len(data) > 1 else []

    async def _spotify_suggestions(self, query: str, limit: int = 4) -> list[app_commands.Choice[str]]:
        if not self.spotify.sp:
            return []
        results = await asyncio.to_thread(self.spotify.sp.search, query, type="track,album", limit=limit)
        choices = []
        for track in results.get("tracks", {}).get("items", [])[:limit]:
            artist = track["artists"][0]["name"] if track["artists"] else ""
            choices.append(app_commands.Choice(name=f"Spotify · {track['name']} — {artist}"[:100],
                                               value=f"https://open.spotify.com/track/{track['id']}"))
        for album in results.get("albums", {}).get("items", [])[: limit // 2]:
            artist = album["artists"][0]["name"] if album["artists"] else ""
            choices.append(app_commands.Choice(name=f"Spotify album · {album['name']} — {artist}"[:100],
                                               value=f"https://open.spotify.com/album/{album['id']}"))
        return choices

    async def play_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        if len(current) < 2 or URL_RE.match(current):
            return []
        yt_task = asyncio.create_task(self._youtube_suggestions(current))
        sp_task = asyncio.create_task(self._spotify_suggestions(current))
        # Discord gives up after 3s: answer with whichever sources made it in time
        done, pending = await asyncio.wait({yt_task, sp_task}, timeout=2)
        for task in pending:
            task.cancel()

        def result(task):
            if task not in done:
                return []
            if task.exception():
                log.debug("Autocomplete source failed: %r", task.exception())
                return []
            return task.result()

        sp = result(sp_task)
        choices = [app_commands.Choice(name=f"YouTube · {s}"[:100], value=s[:100])
                   for s in result(yt_task)[: 10 - len(sp)]]
        return (choices + sp)[:25]

    # --- Commands: playback ---

    async def _play_command(self, ctx: commands.Context, query: str, *, top: bool):
        await ctx.defer()
        await self.join(ctx.author)
        async with ctx.typing():
            songs, label = await self.resolve_query(query, ctx.author.display_name, ctx.author.id)
        await self.enqueue_and_reply(ctx.guild, songs, label, channel_id=ctx.channel.id, send=ctx.send, top=top)

    @commands.hybrid_command(name="play", aliases=["p"], description="Play a song or playlist from YouTube, Spotify, SoundCloud, or a search")
    @app_commands.describe(query="Song name or link")
    @app_commands.autocomplete(query=play_autocomplete)
    async def play(self, ctx: commands.Context, *, query: str):
        await self._play_command(ctx, query, top=False)

    @commands.hybrid_command(name="playtop", aliases=["pt"], description="Add a song to the top of the queue")
    @app_commands.describe(query="Song name or link")
    @app_commands.autocomplete(query=play_autocomplete)
    async def playtop(self, ctx: commands.Context, *, query: str):
        await self._play_command(ctx, query, top=True)

    @commands.hybrid_command(name="search", description="Search YouTube and pick a result")
    @app_commands.describe(query="What to search for")
    async def search(self, ctx: commands.Context, *, query: str):
        await ctx.defer()
        async with ctx.typing():
            results = await youtube.search(query, count=5)
        if not results:
            raise PlayerError(f"No results for `{query}`.")
        embed = discord.Embed(title=f"Results for “{query[:200]}”", color=ACCENT)
        embed.description = "\n".join(
            f"`{i}.` {discord.utils.escape_markdown(r['title'][:90])} · `{format_duration(r['duration'])}`"
            for i, r in enumerate(results, 1)
        )
        view = SearchSelectView(self, ctx.author, results)
        view.message = await ctx.send(embed=embed, view=view)

    @commands.hybrid_command(name="skip", aliases=["s", "next"], description="Skip the current track (vote if you're not a DJ)")
    async def skip_command(self, ctx: commands.Context):
        self._require_listener(ctx)
        await ctx.send(await self.skip(ctx.guild, ctx.author))

    @commands.hybrid_command(name="previous", aliases=["back", "prev"], description="Go back to the previous track")
    async def previous_command(self, ctx: commands.Context):
        self._require_listener(ctx)
        await ctx.send(await self.previous(ctx.guild))

    @commands.hybrid_command(name="pause", description="Pause playback")
    async def pause_command(self, ctx: commands.Context):
        self._require_listener(ctx)
        await ctx.send(await self.pause(ctx.guild))

    @commands.hybrid_command(name="resume", description="Resume playback")
    async def resume_command(self, ctx: commands.Context):
        self._require_listener(ctx)
        await ctx.send(await self.resume(ctx.guild))

    @commands.hybrid_command(name="stop", description="Stop playback, clear the queue and leave")
    async def stop_command(self, ctx: commands.Context):
        self._require_listener(ctx)
        await ctx.send(await self.stop_player(ctx.guild, ctx.author))

    @commands.hybrid_command(name="disconnect", aliases=["dc", "leave"], description="Leave the voice channel")
    async def disconnect_command(self, ctx: commands.Context):
        await ctx.send(await self.stop_player(ctx.guild, ctx.author))

    @commands.hybrid_command(name="seek", description="Jump to a position in the track (e.g. 1:30)")
    @app_commands.describe(timestamp="Position like 1:30, 1:02:03, or seconds")
    async def seek_command(self, ctx: commands.Context, timestamp: str):
        self._require_listener(ctx)
        try:
            seconds = parse_timestamp(timestamp)
        except ValueError:
            raise PlayerError("Invalid timestamp. Use a format like `1:30` or `90`.")
        await ctx.send(await self.seek(ctx.guild, seconds))

    @commands.hybrid_command(name="volume", aliases=["vol"], description="Show or set the volume (0-100)")
    @app_commands.describe(level="0-100. 100 gives the best audio quality")
    async def volume_command(self, ctx: commands.Context, level: app_commands.Range[int, 0, 100] | None = None):
        gq = self.queues.get(ctx.guild.id)
        if level is None:
            await ctx.send(f"🔊 Volume is **{round(gq.volume * 100)}%**.")
            return
        if ctx.voice_client:
            self._require_listener(ctx)
        await ctx.send(await self.set_volume(ctx.guild, level, ctx.author))

    @commands.hybrid_command(name="loop", description="Set loop mode (or cycle it)")
    @app_commands.describe(mode="off, track, or queue. Leave empty to cycle")
    async def loop_command(self, ctx: commands.Context, mode: Literal["off", "track", "queue"] | None = None):
        await ctx.send(await self.set_loop(ctx.guild, mode))

    # --- Commands: queue ---

    @commands.hybrid_command(name="queue", aliases=["q"], description="Show the queue")
    @app_commands.describe(page="Page number")
    async def queue_command(self, ctx: commands.Context, page: int = 1):
        gq = self.queues.get(ctx.guild.id)
        if not gq.current and not gq.queue:
            raise PlayerError("The queue is empty.")
        pages = max(1, -(-len(gq.queue) // QUEUE_PAGE_SIZE))
        page = min(max(page, 1), pages)
        start = (page - 1) * QUEUE_PAGE_SIZE

        lines = []
        if gq.current:
            state = "⏸️" if ctx.voice_client and ctx.voice_client.is_paused() else "▶️"
            lines += [f"{state} {md_link(gq.current)}",
                      progress_bar(gq.position, gq.current.duration) + f" · {gq.current.requester}", ""]
        if gq.queue:
            lines.append("**Up next**")
            for i, song in enumerate(itertools.islice(gq.queue, start, start + QUEUE_PAGE_SIZE), start + 1):
                lines.append(f"`{i}.` {md_link(song, 60)} · `{song_length(song)}`")
        else:
            lines.append("*Nothing queued.*")

        embed = discord.Embed(title="Queue", description="\n".join(lines), color=ACCENT)
        total = sum(s.duration for s in gq.queue)
        footer = [f"Page {page}/{pages}", f"{len(gq.queue)} tracks"]
        if total:
            footer.append(format_duration(total))
        footer.append(f"Loop: {gq.loop_mode.value}")
        embed.set_footer(text=" · ".join(footer))
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="nowplaying", aliases=["np"], description="Show the current track")
    async def nowplaying(self, ctx: commands.Context):
        gq = self.queues.get(ctx.guild.id)
        if not gq.current:
            raise PlayerError("Nothing is playing.")
        embed = self._now_playing_embed(gq)
        embed.add_field(name="Progress", value=progress_bar(gq.position, gq.current.duration), inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="shuffle", description="Shuffle the queue")
    async def shuffle_command(self, ctx: commands.Context):
        await ctx.send(await self.shuffle(ctx.guild, ctx.author))

    @commands.hybrid_command(name="remove", description="Remove a song from the queue")
    @app_commands.describe(position="Position in the queue (see /queue)")
    async def remove_command(self, ctx: commands.Context, position: int):
        await ctx.send(await self.remove(ctx.guild, position - 1, ctx.author))

    @commands.hybrid_command(name="move", description="Move a song to a different position in the queue")
    @app_commands.describe(from_position="Current position", to_position="New position")
    async def move_command(self, ctx: commands.Context, from_position: int, to_position: int):
        await ctx.send(await self.move(ctx.guild, from_position - 1, to_position - 1, ctx.author))

    @commands.hybrid_command(name="clear", description="Clear the queue (keeps the current song playing)")
    async def clear_command(self, ctx: commands.Context):
        await ctx.send(await self.clear_queue(ctx.guild, ctx.author))

    @commands.hybrid_command(name="lyrics", description="Show lyrics for the current track")
    async def lyrics(self, ctx: commands.Context):
        gq = self.queues.get(ctx.guild.id)
        if not gq.current:
            raise PlayerError("Nothing is playing.")
        await ctx.defer()
        title = gq.current.title
        async with ctx.typing():
            text = await self.lyrics_fetcher.fetch_lyrics(self.http, title)
        if not text:
            raise PlayerError(f"No lyrics found for **{discord.utils.escape_markdown(title)}**.")
        for i, chunk in enumerate(LyricsFetcher.split_lyrics(text)):
            heading = f"Lyrics · {title}"[:256] if i == 0 else "Lyrics (cont.)"
            await ctx.send(embed=discord.Embed(title=heading, description=chunk, color=ACCENT))

    # --- Commands: effects ---

    async def _filter_command(self, ctx: commands.Context, key: str):
        if ctx.voice_client:
            self._require_listener(ctx)
        await ctx.send(await self.set_filter(ctx.guild, key))

    @commands.hybrid_command(name="nightcore", description="Nightcore effect (faster, higher pitch)")
    async def nightcore(self, ctx: commands.Context):
        await self._filter_command(ctx, "nightcore")

    @commands.hybrid_command(name="vaporwave", description="Vaporwave effect (slower, lower pitch)")
    async def vaporwave(self, ctx: commands.Context):
        await self._filter_command(ctx, "vaporwave")

    @commands.hybrid_command(name="bassboost", description="Boost bass frequencies")
    async def bassboost(self, ctx: commands.Context):
        await self._filter_command(ctx, "bassboost")

    @commands.hybrid_command(name="tremolo", description="Tremolo effect (volume wobble)")
    async def tremolo(self, ctx: commands.Context):
        await self._filter_command(ctx, "tremolo")

    @commands.hybrid_command(name="vibrato", description="Vibrato effect (pitch wobble)")
    async def vibrato(self, ctx: commands.Context):
        await self._filter_command(ctx, "vibrato")

    @commands.hybrid_command(name="8d", description="8D audio effect (rotating stereo)")
    async def eightd(self, ctx: commands.Context):
        await self._filter_command(ctx, "8d")

    @commands.hybrid_command(name="speed", description="Change playback speed (0.5-2.0)")
    @app_commands.describe(rate="Playback speed, e.g. 1.25")
    async def speed(self, ctx: commands.Context, rate: app_commands.Range[float, 0.5, 2.0]):
        await self._filter_command(ctx, f"speed:{rate:g}")

    @commands.hybrid_command(name="cleareffect", aliases=["clearfilter"], description="Remove audio effects")
    async def cleareffect(self, ctx: commands.Context):
        await self._filter_command(ctx, "clear")

    # --- Commands: settings & cache ---

    @commands.hybrid_command(name="247", description="Toggle 24/7 mode (stay in the voice channel)")
    async def twenty_four_seven(self, ctx: commands.Context):
        gq = self.queues.get(ctx.guild.id)
        await ctx.send(await self.set_247(ctx.guild, not gq.twenty_four_seven, ctx.author))

    @commands.hybrid_command(name="cachestats", description="Show audio cache statistics")
    async def cachestats(self, ctx: commands.Context):
        stats = await self.cache.get_stats()
        total = stats["hits"] + stats["misses"]
        ratio = f"{stats['hits'] / total * 100:.0f}%" if total else "N/A"
        embed = discord.Embed(title="Audio cache", color=ACCENT)
        embed.add_field(name="Cached tracks", value=str(stats["count"]))
        embed.add_field(name="Size", value=f"{stats['total_size_mb']} / {stats['max_size_mb']} MB")
        embed.add_field(name="Hit rate", value=f"{ratio} ({stats['hits']} hits, {stats['misses']} misses)", inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="clearcache", description="Clear the audio cache")
    async def clearcache(self, ctx: commands.Context):
        self.require_dj(ctx.author)
        await self.cache.clear_all()
        await ctx.send("🧹 Audio cache cleared.")


def _is_opus(acodec: str, path: str) -> bool:
    if acodec:
        return acodec == "opus"
    return path.endswith((".opus", ".webm"))  # older cache entries without codec info


def _bitrate(vc: discord.VoiceClient) -> int:
    """Encode at the channel's bitrate (boosted servers allow more), never below 128k."""
    return max(128, min(vc.channel.bitrate // 1000, 384))


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
