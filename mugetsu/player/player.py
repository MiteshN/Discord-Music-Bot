"""The playback engine for one guild, and every action that can be taken on it.

Discord commands, Now Playing buttons and the web dashboard all call the same
methods here, so they share one set of rules (DJ role, vote skip, limits).
Each action returns a short message for the user or raises PlayerError.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
from typing import TYPE_CHECKING

import discord

from mugetsu.media.ffmpeg import AudioInput, get_filter
from mugetsu.player.models import LoopMode, PlayerError, Song
from mugetsu.player.queue import GuildQueue
from mugetsu.player.settings import SavedSettings
from mugetsu.util import format_duration, plain, short_error

if TYPE_CHECKING:
    from mugetsu.player.manager import PlayerManager

log = logging.getLogger("mugetsu.player")

STATE_QUEUE_LIMIT = 200  # queue entries sent to the dashboard per update
STATE_HISTORY_LIMIT = 20
PREFETCH_DELAY = 3  # let the current track settle before resolving the next


def esc(text: str) -> str:
    return discord.utils.escape_markdown(text)


def _bitrate(vc: discord.VoiceClient) -> int:
    """Encode at the channel's bitrate (boosted servers allow more), never below 128k."""
    return max(128, min(vc.channel.bitrate // 1000, 384))


class GuildPlayer:
    def __init__(self, manager: PlayerManager, guild_id: int, saved: SavedSettings):
        self.manager = manager
        self.guild_id = guild_id
        self.q = GuildQueue()
        self.volume = saved.volume
        self.twenty_four_seven = saved.twenty_four_seven
        self.text_channel_id: int | None = None

        self.lock = asyncio.Lock()
        self.play_id = 0  # bumped on every play/stop so stale "track ended" callbacks are ignored
        self.audio_input: AudioInput | None = None
        self.idle_since: float | None = time.monotonic()
        self.alone_since: float | None = None
        self.closed = False
        self._prefetch_task: asyncio.Task | None = None

    # --- Discord handles ---

    @property
    def guild(self) -> discord.Guild | None:
        return self.manager.bot.get_guild(self.guild_id)

    @property
    def voice(self) -> discord.VoiceClient | None:
        guild = self.guild
        return guild.voice_client if guild else None  # type: ignore[return-value]

    @property
    def is_connected(self) -> bool:
        vc = self.voice
        return vc is not None and vc.is_connected()

    @property
    def current(self) -> Song | None:
        return self.q.current

    def listeners(self) -> list[discord.Member]:
        vc = self.voice
        if not vc or not vc.is_connected() or not vc.channel:
            return []
        return [m for m in vc.channel.members if not m.bot]

    def notify(self):
        self.manager.notify(self.guild_id)

    def _done(self, message: str, actor: discord.Member | None) -> str:
        """Tell dashboard viewers what happened, then hand the message back to the caller."""
        if actor is not None:
            self.manager.notify.activity(self.guild_id, plain(message), actor.display_name, actor.id)
        return message

    def _playing_vc(self) -> discord.VoiceClient:
        vc = self.voice
        if not vc or not (vc.is_playing() or vc.is_paused()):
            raise PlayerError("Nothing is playing.")
        return vc

    def _connected_vc(self) -> discord.VoiceClient:
        vc = self.voice
        if not vc or not vc.is_connected():
            raise PlayerError("I'm not in a voice channel.")
        return vc

    # --- Playback engine. Everything below runs with self.lock held. ---

    async def _start_locked(self, song: Song, position: float = 0) -> bool:
        try:
            inp = await self.manager.resolve_input(song)
        except Exception as e:
            log.warning("[Guild %d] Couldn't resolve %r: %s", self.guild_id, song.title, e)
            await self.manager.hooks.notice(self, f"⚠️ Couldn't play **{esc(song.title)}**: {short_error(e)}")
            return False

        vc = self.voice
        if self.closed or not vc or not vc.is_connected() or self.q.current is not song:
            return False  # torn down or superseded while resolving

        try:
            source = self.manager.make_source(
                inp, volume=self.volume, audio_filter=self.q.audio_filter, position=position, bitrate=_bitrate(vc)
            )
        except discord.ClientException as e:
            log.error("[Guild %d] FFmpeg failed to start: %s", self.guild_id, e)
            await self.manager.hooks.notice(self, f"⚠️ Audio engine error: {short_error(e)}")
            return False

        self.audio_input = inp
        self._play_source(vc, source)
        self.q.mark_playing(position)
        self.idle_since = None
        log.info(
            "[Guild %d] Playing %s (%s, %s, %s)", self.guild_id, song.title, format_duration(song.duration),
            "cache" if inp.is_local else "stream", "passthrough" if getattr(source, "passthrough", False) else "transcode",
        )
        return True

    def _play_source(self, vc: discord.VoiceClient, source: discord.AudioSource):
        self.play_id += 1
        token = self.play_id
        loop = asyncio.get_running_loop()
        stderr = getattr(source, "stderr_tail", None)

        def after(error):
            if error:
                log.error("[Guild %d] Player error: %r", self.guild_id, error, exc_info=error)
            if not loop.is_closed():
                asyncio.run_coroutine_threadsafe(self._on_track_end(token, error, stderr), loop)

        if vc.is_playing() or vc.is_paused():
            vc.stop()
        vc.play(source, after=after)

    async def _on_track_end(self, token: int, error: BaseException | None = None, stderr=None):
        try:
            await self._handle_track_end(token, error, stderr)
        finally:
            if stderr is not None:
                stderr.close()  # FFmpeg is done with it

    async def _handle_track_end(self, token: int, error: BaseException | None, stderr):
        if self.closed:
            return
        async with self.lock:
            if self.play_id != token or self.closed:
                return  # superseded by a skip/seek/filter change
            song = self.q.current
            # A track that dies within 2s never really played: don't loop it forever
            failed = song is not None and self.q.position < 2 and song.duration > 5
            if failed:
                song.track = None  # force a fresh extraction if it's retried later
                why = short_error(error) if error else await self._ffmpeg_reason(stderr)
                reason = f" ({why})" if why else ""
                await self.manager.hooks.notice(
                    self, f"⚠️ Playback of **{esc(song.title)}** failed{reason}, skipping."
                )
            await self._play_from(self.q.advance(failed=failed))

    async def _ffmpeg_reason(self, stderr) -> str:
        """Why FFmpeg gave up, from its own output (e.g. an HTTP 403 from YouTube)."""
        if stderr is None:
            return ""
        for _ in range(10):  # discord.py's stderr reader thread may still be catching up
            if stderr.text():
                break
            await asyncio.sleep(0.05)
        text = stderr.text()
        if text:
            log.warning("[Guild %d] FFmpeg output:\n%s", self.guild_id, text)
        return stderr.reason()

    async def _play_from(self, song: Song | None, *, announce: bool = True) -> Song | None:
        while song:
            if await self._start_locked(song):
                await self.manager.hooks.track_started(self, song, announce=announce)
                self.schedule_prefetch()
                self.notify()
                await self._set_status(song)
                return song
            if self.closed or not self.voice:
                return None
            song = self.q.advance(failed=True)

        self._mark_idle()
        await self.manager.hooks.track_cleared(self)
        await self._set_status(None)
        self.notify()
        return None

    async def _restart_locked(self, position: float):
        """Restart the current track at a position, e.g. after a seek, volume or effect change."""
        vc = self.voice
        if not self.q.current or not vc or not (vc.is_playing() or vc.is_paused()):
            return
        inp = self.audio_input
        try:
            if inp is None or not inp.is_local:
                # Picks up the cached file if its background download has finished,
                # otherwise reuses the resolved stream (no yt-dlp call while it's fresh)
                inp = await self.manager.resolve_input(self.q.current)
            source = self.manager.make_source(
                inp, volume=self.volume, audio_filter=self.q.audio_filter, position=position, bitrate=_bitrate(vc)
            )
        except Exception as e:
            log.warning("[Guild %d] Couldn't restart the track: %s", self.guild_id, e)
            raise PlayerError(f"Couldn't apply that to the current track: {short_error(e)}") from e
        was_paused = vc.is_paused()  # checked after the await so a pause made meanwhile sticks
        self.audio_input = inp
        self._play_source(vc, source)
        self.q.mark_playing(position)
        if was_paused:
            vc.pause()
            self.q.mark_paused()
        self.notify()

    def _mark_idle(self):
        self.q.mark_idle()
        self.audio_input = None
        self.idle_since = time.monotonic()

    def schedule_prefetch(self):
        if self._prefetch_task:
            self._prefetch_task.cancel()
        self._prefetch_task = asyncio.create_task(self._prefetch())

    async def _prefetch(self):
        """Resolve (and cache) the next song while this one plays, so it starts instantly."""
        await asyncio.sleep(PREFETCH_DELAY)
        if self.closed or not self.q.queue or self.q.loop_mode is LoopMode.TRACK:
            return
        song = self.q.queue[0]
        try:
            if await self.manager.prefetch(song):
                self.notify()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.debug("[Guild %d] Prefetch failed for %r: %s", self.guild_id, song.title, e)

    async def _set_status(self, song: Song | None):
        vc = self.voice
        if not vc or not vc.channel:
            return
        status = f"🎵 {song.title}"[:500] if song else None
        try:
            await vc.channel.edit(status=status)
        except (discord.HTTPException, AttributeError, TypeError):
            pass

    async def close(self, *, disconnect: bool = True):
        """Stop everything. Only PlayerManager.destroy calls this."""
        if self.closed:
            return
        self.closed = True
        self.play_id += 1  # ignore the callback from stopping playback
        if self._prefetch_task:
            self._prefetch_task.cancel()
        await self.manager.hooks.track_cleared(self)
        vc = self.voice
        if vc:
            await self._set_status(None)
            if disconnect:
                vc.stop()
                await vc.disconnect(force=True)

    # --- Actions ---

    async def enqueue(self, songs: list[Song], *, top: bool = False, channel_id: int | None = None,
                      announce: bool = True, actor: discord.Member | None = None) -> Song | None:
        """Add songs and start playback if idle. Returns the song that started playing, if any."""
        if channel_id:
            self.text_channel_id = channel_id
        self.q.add(songs, top=top)
        if actor is not None:
            what = f"**{songs[0].title}**" if len(songs) == 1 else f"**{len(songs)}** tracks"
            self._done(f"➕ Added {what}{' to play next' if top else ''}", actor)
        started = None
        async with self.lock:
            if self.q.current is None and self.is_connected:
                started = await self._play_from(self.q.advance(), announce=announce)
        if not started:
            self.notify()
            if len(self.q.queue) == len(songs) or top:
                self.schedule_prefetch()
        return started

    async def toggle_pause(self, actor: discord.Member | None = None) -> str:
        vc = self._playing_vc()
        if vc.is_paused():
            vc.resume()
            self.q.mark_resumed()
            message = "▶️ Resumed."
        else:
            vc.pause()
            self.q.mark_paused()
            message = "⏸️ Paused."
        self.notify()
        return self._done(message, actor)

    async def pause(self, actor: discord.Member | None = None) -> str:
        if not self._playing_vc().is_playing():
            raise PlayerError("Already paused.")
        return await self.toggle_pause(actor)

    async def resume(self, actor: discord.Member | None = None) -> str:
        if not self._playing_vc().is_paused():
            raise PlayerError("Nothing is paused.")
        return await self.toggle_pause(actor)

    async def skip(self, actor: discord.Member | None = None) -> str:
        vc = self._playing_vc()
        # DJs, the song's requester, and small audiences skip instantly; everyone else votes
        if actor is not None and not self.manager.can_force_skip(actor, self):
            listeners = {m.id for m in self.listeners()}
            if len(listeners) > 2:
                if actor.id not in listeners:
                    raise PlayerError("Join the voice channel to vote to skip.")
                self.q.skip_votes.add(actor.id)
                self.q.skip_votes &= listeners
                needed = len(listeners) // 2 + 1
                if len(self.q.skip_votes) < needed:
                    self.notify()
                    return self._done(f"🗳️ Vote to skip: **{len(self.q.skip_votes)}/{needed}**", actor)
        skipped = self.q.current
        async with self.lock:
            self.play_id += 1
            vc.stop()
            await self._play_from(self.q.advance(skipping=True))
        message = f"⏭️ Skipped **{esc(skipped.title)}**." if skipped else "⏭️ Skipped."
        return self._done(message, actor)

    async def skip_to(self, index: int, actor: discord.Member | None = None) -> str:
        self.manager.require_dj(actor)
        vc = self._connected_vc()
        async with self.lock:
            if not 0 <= index < len(self.q.queue):
                raise PlayerError("There's no song at that position.")
            skipped = self.q.drop_before(index)
            self.play_id += 1
            if vc.is_playing() or vc.is_paused():
                vc.stop()
            song = await self._play_from(self.q.advance(skipping=True))
            if self.q.loop_mode is LoopMode.QUEUE:
                self.q.queue.extend(skipped)  # looping: skipped songs come around again
        if song is None:
            return self._done("⏭️ Nothing left to play.", actor)
        return self._done(f"⏭️ Jumped to **{esc(song.title)}**.", actor)

    async def previous(self, actor: discord.Member | None = None) -> str:
        vc = self._connected_vc()
        async with self.lock:
            song = self.q.rewind()
            if not song:
                raise PlayerError("There's no previous track.")
            self.play_id += 1
            vc.stop()
            await self._play_from(song)
        return self._done(f"⏮️ Back to **{esc(song.title)}**.", actor)

    async def stop(self, actor: discord.Member | None = None) -> str:
        self.manager.require_dj(actor)
        self._connected_vc()
        message = self._done("⏹️ Stopped and disconnected.", actor)
        await self.manager.destroy(self.guild_id)
        return message

    async def seek(self, seconds: float, actor: discord.Member | None = None) -> str:
        self._playing_vc()
        song = self.q.current
        if not song or song.duration <= 0 or song.is_live:
            raise PlayerError("This track can't be seeked.")
        seconds = int(seconds)
        if not 0 <= seconds < song.duration:
            raise PlayerError(f"Position must be between 0:00 and {format_duration(song.duration)}.")
        async with self.lock:
            await self._restart_locked(seconds)
        return self._done(f"⏩ Seeked to **{format_duration(seconds)}**.", actor)

    async def set_volume(self, volume: int, actor: discord.Member | None = None) -> str:
        self.manager.require_dj(actor)
        if not 0 <= volume <= 100:
            raise PlayerError("Volume must be between 0 and 100.")
        async with self.lock:
            position = self.q.position
            self.volume = volume / 100
            await self._restart_locked(position)
        await self.manager.settings.save(self.guild_id, volume=self.volume, twenty_four_seven=self.twenty_four_seven)
        self.notify()
        return self._done(f"🔊 Volume set to **{volume}%**.", actor)

    async def set_loop(self, mode: str | None, actor: discord.Member | None = None) -> str:
        if mode is None:
            cycle = [LoopMode.OFF, LoopMode.TRACK, LoopMode.QUEUE]
            self.q.loop_mode = cycle[(cycle.index(self.q.loop_mode) + 1) % len(cycle)]
        else:
            try:
                self.q.loop_mode = LoopMode(mode)
            except ValueError:
                raise PlayerError("Loop mode must be `off`, `track`, or `queue`.") from None
        self.notify()
        icons = {LoopMode.OFF: "➡️", LoopMode.TRACK: "🔂", LoopMode.QUEUE: "🔁"}
        return self._done(f"{icons[self.q.loop_mode]} Loop: **{self.q.loop_mode.value}**.", actor)

    async def set_filter(self, key: str, actor: discord.Member | None = None) -> str:
        try:
            audio_filter = get_filter(key)
        except ValueError as e:
            raise PlayerError(str(e)) from None
        async with self.lock:
            position = self.q.position  # measured at the old playback rate
            self.q.audio_filter = audio_filter
            await self._restart_locked(position)
        self.notify()
        message = f"🎚️ Effect: **{audio_filter.label}**." if audio_filter else "🎚️ Effects cleared."
        return self._done(message, actor)

    async def shuffle(self, actor: discord.Member | None = None) -> str:
        self.manager.require_dj(actor)
        if len(self.q.queue) < 2:
            raise PlayerError("Not enough songs in the queue to shuffle.")
        self.q.shuffle()
        self.schedule_prefetch()
        self.notify()
        return self._done(f"🔀 Shuffled **{len(self.q.queue)}** tracks.", actor)

    async def remove(self, index: int, actor: discord.Member | None = None) -> str:
        self.manager.require_dj(actor)
        removed = self.q.remove(index)
        if not removed:
            raise PlayerError("There's no song at that position.")
        if index == 0:
            self.schedule_prefetch()
        self.notify()
        return self._done(f"🗑️ Removed **{esc(removed.title)}**.", actor)

    async def move(self, from_idx: int, to_idx: int, actor: discord.Member | None = None) -> str:
        self.manager.require_dj(actor)
        song = self.q.queue[from_idx] if 0 <= from_idx < len(self.q.queue) else None
        if song is None or not self.q.move(from_idx, to_idx):
            raise PlayerError("Invalid positions.")
        if 0 in (from_idx, to_idx):
            self.schedule_prefetch()
        self.notify()
        return self._done(f"↕️ Moved **{esc(song.title)}** to position **{to_idx + 1}**.", actor)

    async def clear(self, actor: discord.Member | None = None) -> str:
        self.manager.require_dj(actor)
        count = len(self.q.queue)
        self.q.queue.clear()
        self.notify()
        return self._done(f"🧹 Cleared **{count}** tracks from the queue.", actor)

    async def set_247(self, enabled: bool, actor: discord.Member | None = None) -> str:
        self.manager.require_dj(actor)
        self.twenty_four_seven = enabled
        await self.manager.settings.save(self.guild_id, volume=self.volume, twenty_four_seven=enabled)
        self.notify()
        if enabled:
            return self._done("🌙 24/7 mode **on**: I'll stay in voice.", actor)
        return self._done("24/7 mode **off**: I'll leave when idle.", actor)

    # --- Dashboard state ---

    def snapshot(self) -> dict:
        vc = self.voice
        in_voice = vc is not None and vc.is_connected()
        q = self.q
        listeners = self.listeners() if in_voice else []
        voice = None
        if in_voice:
            voice = {
                "channel": vc.channel.name,
                "listeners": [
                    {"id": str(m.id), "name": m.display_name, "avatar": m.display_avatar.with_size(64).url}
                    for m in listeners[:25]
                ],
            }
        return {
            "current": q.current.to_dict() if q.current else None,
            "position": round(q.position, 2) if q.current else 0,
            "rate": q.rate,
            "paused": bool(in_voice and vc.is_paused()),
            "volume": round(self.volume * 100),
            "loop": q.loop_mode.value,
            "effect": {"key": q.audio_filter.key, "label": q.audio_filter.label} if q.audio_filter else None,
            "queue": [s.to_dict() for s in itertools.islice(q.queue, STATE_QUEUE_LIMIT)],
            "queue_length": len(q.queue),
            "queue_duration": q.duration,
            "history": [s.to_dict() for s in itertools.islice(reversed(q.history), STATE_HISTORY_LIMIT)],
            "twenty_four_seven": self.twenty_four_seven,
            "voice": voice,
            "skip_votes": len(q.skip_votes),
            "skip_needed": len(listeners) // 2 + 1 if len(listeners) > 2 else 0,
            "timestamp": time.time(),
        }
