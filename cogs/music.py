import asyncio
import time
import re
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.queue_manager import QueueManager, Song, LoopMode
from utils.youtube import YTDLSource
from utils.spotify import SpotifyResolver
from utils.lyrics import LyricsFetcher
from utils.sponsorblock import get_segments

YOUTUBE_PLAYLIST_RE = re.compile(r"(youtube\.com/.*[?&]list=|youtu\.be/.*[?&]list=)")
YOUTUBE_VIDEO_ID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/)([a-zA-Z0-9_-]{11})")


def format_duration(seconds: int) -> str:
    if seconds <= 0:
        return "Live"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def parse_timestamp(ts: str) -> int:
    parts = ts.split(":")
    parts = [int(p) for p in parts]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0]


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.queue_manager = QueueManager()
        self.spotify = SpotifyResolver()
        self.lyrics_fetcher = LyricsFetcher()
        self.auto_disconnect_task.start()

    def cog_unload(self):
        self.auto_disconnect_task.cancel()

    # --- Helpers ---

    async def _ensure_voice(self, ctx: commands.Context) -> discord.VoiceClient | None:
        if not ctx.author.voice:
            await ctx.send("You need to be in a voice channel.")
            return None
        channel = ctx.author.voice.channel
        if ctx.voice_client:
            if ctx.voice_client.channel != channel:
                await ctx.voice_client.move_to(channel)
            return ctx.voice_client
        vc = await channel.connect()
        await ctx.guild.change_voice_state(channel=channel, self_deaf=True)
        return vc

    def _check_dj(self, ctx: commands.Context) -> bool:
        dj_role = discord.utils.get(ctx.guild.roles, name="DJ")
        if not dj_role:
            return True
        if ctx.author.guild_permissions.administrator:
            return True
        return dj_role in ctx.author.roles

    @staticmethod
    def _extract_video_id(url: str) -> str | None:
        match = YOUTUBE_VIDEO_ID_RE.search(url)
        return match.group(1) if match else None

    @staticmethod
    def _apply_sponsorblock(song: Song, segments: list[tuple[float, float]]):
        """Trim intro/outro non-music segments by adjusting song offset and duration.

        Like muse bot: only trims segments at the very start (intro) and very end (outro).
        """
        if not segments:
            return

        intro = segments[0]
        outro = segments[-1]

        # Trim outro: if last segment ends within 2s of song end
        if outro[1] >= song.duration - 2:
            song.duration -= int(outro[1] - outro[0])
            song.sb_end = int(outro[0])

        # Trim intro: if first segment starts within 2s of beginning
        if intro[0] <= 2:
            song.sb_offset = int(intro[1])
            song.duration -= song.sb_offset
            # Adjust sb_end if both intro and outro were trimmed
            if not song.sb_end:
                song.sb_end = 0

    async def _play_song(self, ctx: commands.Context, song: Song):
        gq = self.queue_manager.get(ctx.guild.id)
        gq.current = song
        gq.skip_votes.clear()

        try:
            source = await YTDLSource.create_source(
                song.url or song.search_query,
                loop=self.bot.loop,
                volume=gq.volume,
            )
        except Exception as e:
            await ctx.send(f"Error playing **{song.title}**: {e}")
            self._play_next(ctx)
            return

        song.title = source.title
        song.duration = source.duration
        song.thumbnail = source.thumbnail
        song.url = source.webpage_url

        # SponsorBlock: fetch segments and compute intro/outro trim
        sb_trimmed = False
        if gq.sponsorblock and song.duration > 0:
            video_id = self._extract_video_id(song.url)
            if video_id:
                segments = await get_segments(video_id)
                if segments:
                    self._apply_sponsorblock(song, segments)
                    sb_trimmed = song.sb_offset > 0 or song.sb_end > 0

        # If SponsorBlock trimmed, recreate source with offset/end
        if sb_trimmed:
            try:
                source = await YTDLSource.create_source(
                    song.url or song.search_query,
                    loop=self.bot.loop,
                    volume=gq.volume,
                    seek_to=song.sb_offset,
                    end_at=song.sb_end if song.sb_end else 0,
                )
            except Exception:
                # Fall back to untrimmed playback
                sb_trimmed = False
                source = await YTDLSource.create_source(
                    song.url or song.search_query,
                    loop=self.bot.loop,
                    volume=gq.volume,
                )

        gq.start_time = time.time()

        def after_play(error):
            if error:
                print(f"Playback error: {error}")
            asyncio.run_coroutine_threadsafe(self._play_next_async(ctx), self.bot.loop)

        ctx.voice_client.play(source, after=after_play)

        embed = discord.Embed(
            title="Now Playing",
            description=f"[{song.title}]({song.url})",
            color=discord.Color.green(),
        )
        embed.add_field(name="Duration", value=format_duration(song.duration))
        embed.add_field(name="Requested by", value=song.requester)
        if song.thumbnail:
            embed.set_thumbnail(url=song.thumbnail)
        if sb_trimmed:
            embed.set_footer(text="SponsorBlock: non-music intro/outro trimmed")
        await ctx.send(embed=embed)

    async def _play_next_async(self, ctx: commands.Context):
        gq = self.queue_manager.get(ctx.guild.id)
        next_song = gq.next()
        if next_song:
            await self._play_song(ctx, next_song)

    def _play_next(self, ctx: commands.Context):
        asyncio.run_coroutine_threadsafe(self._play_next_async(ctx), self.bot.loop)

    def _vote_skip_check(self, ctx: commands.Context) -> tuple[bool, int, int]:
        """Returns (should_skip, current_votes, needed_votes)."""
        gq = self.queue_manager.get(ctx.guild.id)
        voice = ctx.voice_client
        if not voice or not voice.channel:
            return True, 0, 0
        members = [m for m in voice.channel.members if not m.bot]
        if len(members) <= 2:
            return True, 0, 0
        gq.skip_votes.add(ctx.author.id)
        needed = len(members) // 2 + 1
        return len(gq.skip_votes) >= needed, len(gq.skip_votes), needed

    @tasks.loop(seconds=30)
    async def auto_disconnect_task(self):
        for vc in self.bot.voice_clients:
            gq = self.queue_manager.get(vc.guild.id)
            if not vc.is_playing() and not vc.is_paused() and not gq.queue:
                if gq.start_time and (time.time() - gq.start_time) > 180:
                    gq.clear()
                    self.queue_manager.remove(vc.guild.id)
                    await vc.disconnect()
                elif not gq.current and not gq.start_time:
                    pass  # just connected, no timeout yet

    @auto_disconnect_task.before_loop
    async def before_auto_disconnect(self):
        await self.bot.wait_until_ready()

    # --- Commands ---

    async def _youtube_suggestions(self, query: str) -> list[str]:
        url = "https://suggestqueries.google.com/complete/search"
        params = {"client": "firefox", "ds": "yt", "q": query}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                data = await resp.json(content_type=None)
                return data[1] if len(data) > 1 else []

    async def _spotify_suggestions(self, query: str, limit: int = 5) -> list[app_commands.Choice[str]]:
        if not self.spotify.sp:
            return []
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None, lambda: self.spotify.sp.search(query, type="track,album", limit=limit)
        )
        choices = []
        for track in (results.get("tracks", {}).get("items", []))[:limit]:
            artist = track["artists"][0]["name"] if track["artists"] else ""
            name = f"Spotify: {track['name']} - {artist}"
            choices.append(app_commands.Choice(name=name[:100], value=f"https://open.spotify.com/track/{track['id']}"))
        for album in (results.get("albums", {}).get("items", []))[:limit // 2]:
            artist = album["artists"][0]["name"] if album["artists"] else ""
            name = f"Spotify: {album['name']} - {artist}"
            choices.append(app_commands.Choice(name=name[:100], value=f"https://open.spotify.com/album/{album['id']}"))
        return choices

    async def play_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        if len(current) < 2:
            return []
        try:
            yt_task = self._youtube_suggestions(current)
            sp_task = self._spotify_suggestions(current, limit=5)
            yt_results, sp_results = await asyncio.gather(yt_task, sp_task, return_exceptions=True)

            choices: list[app_commands.Choice[str]] = []

            # YouTube suggestions
            if isinstance(yt_results, list):
                max_yt = 10 - (len(sp_results) if isinstance(sp_results, list) else 0)
                for s in yt_results[:max_yt]:
                    choices.append(app_commands.Choice(name=f"YouTube: {s}"[:100], value=s))

            # Spotify suggestions
            if isinstance(sp_results, list):
                choices.extend(sp_results)

            return choices[:10]
        except Exception:
            return []

    @commands.hybrid_command(name="play", description="Play a song from YouTube, Spotify, SoundCloud, or search")
    @app_commands.autocomplete(query=play_autocomplete)
    async def play(self, ctx: commands.Context, *, query: str):
        vc = await self._ensure_voice(ctx)
        if not vc:
            return

        gq = self.queue_manager.get(ctx.guild.id)

        # Spotify handling
        if SpotifyResolver.is_spotify_url(query):
            async with ctx.typing():
                searches = await self.bot.loop.run_in_executor(None, self.spotify.resolve, query)
            if not searches:
                await ctx.send("Could not resolve Spotify URL.")
                return
            for s in searches:
                song = Song(title=s, url="", search_query=s, requester=ctx.author.display_name)
                gq.add(song)
            await ctx.send(f"Added **{len(searches)}** track(s) from Spotify to the queue.")
            if not vc.is_playing() and not vc.is_paused():
                next_song = gq.next()
                if next_song:
                    await self._play_song(ctx, next_song)
            return

        # YouTube playlist handling
        if YOUTUBE_PLAYLIST_RE.search(query):
            async with ctx.typing():
                entries = await YTDLSource.extract_playlist(query, loop=self.bot.loop)
            if not entries:
                await ctx.send("Could not extract playlist.")
                return
            for entry in entries:
                song = Song(
                    title=entry["title"],
                    url=entry["url"],
                    search_query=entry["title"],
                    requester=ctx.author.display_name,
                )
                gq.add(song)
            await ctx.send(f"Added **{len(entries)}** tracks from playlist to the queue.")
            if not vc.is_playing() and not vc.is_paused():
                next_song = gq.next()
                if next_song:
                    await self._play_song(ctx, next_song)
            return

        # Single track (URL or search)
        song = Song(title=query, url=query, search_query=query, requester=ctx.author.display_name)
        gq.add(song)

        if vc.is_playing() or vc.is_paused():
            await ctx.send(f"Added **{query}** to the queue (position {len(gq.queue)}).")
        else:
            next_song = gq.next()
            if next_song:
                await self._play_song(ctx, next_song)

    @commands.hybrid_command(name="skip", description="Skip the current track")
    async def skip(self, ctx: commands.Context):
        if not ctx.voice_client or not ctx.voice_client.is_playing():
            await ctx.send("Nothing is playing.")
            return
        if not self._check_dj(ctx):
            await ctx.send("You need the DJ role to skip.")
            return

        should_skip, votes, needed = self._vote_skip_check(ctx)
        if should_skip:
            ctx.voice_client.stop()
            await ctx.send("Skipped.")
        else:
            await ctx.send(f"Vote skip: **{votes}/{needed}** votes needed.")

    @commands.hybrid_command(name="pause", description="Pause playback")
    async def pause(self, ctx: commands.Context):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("Paused.")
        else:
            await ctx.send("Nothing is playing.")

    @commands.hybrid_command(name="resume", description="Resume playback")
    async def resume(self, ctx: commands.Context):
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("Resumed.")
        else:
            await ctx.send("Nothing is paused.")

    @commands.hybrid_command(name="stop", description="Stop playback and clear the queue")
    async def stop(self, ctx: commands.Context):
        if not self._check_dj(ctx):
            await ctx.send("You need the DJ role to stop.")
            return
        gq = self.queue_manager.get(ctx.guild.id)
        gq.clear()
        if ctx.voice_client:
            ctx.voice_client.stop()
            await ctx.voice_client.disconnect()
        await ctx.send("Stopped and disconnected.")

    @commands.hybrid_command(name="disconnect", aliases=["dc", "leave"], description="Disconnect from the voice channel")
    async def disconnect(self, ctx: commands.Context):
        if not ctx.voice_client:
            await ctx.send("I'm not in a voice channel.")
            return
        gq = self.queue_manager.get(ctx.guild.id)
        gq.clear()
        ctx.voice_client.stop()
        await ctx.voice_client.disconnect()
        await ctx.send("Disconnected.")

    @commands.hybrid_command(name="queue", description="Show the current queue")
    async def queue(self, ctx: commands.Context):
        gq = self.queue_manager.get(ctx.guild.id)
        if not gq.current and not gq.queue:
            await ctx.send("The queue is empty.")
            return

        embed = discord.Embed(title="Music Queue", color=discord.Color.blue())
        if gq.current:
            embed.add_field(
                name="Now Playing",
                value=f"[{gq.current.title}]({gq.current.url}) | `{format_duration(gq.current.duration)}` | Requested by {gq.current.requester}",
                inline=False,
            )

        if gq.queue:
            page_size = 10
            entries = []
            for i, song in enumerate(gq.queue[:page_size], 1):
                entries.append(f"`{i}.` [{song.title}]({song.url or 'searching'}) | Requested by {song.requester}")
            embed.add_field(name="Up Next", value="\n".join(entries), inline=False)
            if len(gq.queue) > page_size:
                embed.set_footer(text=f"And {len(gq.queue) - page_size} more...")
        else:
            embed.add_field(name="Up Next", value="Nothing in queue", inline=False)

        embed.add_field(name="Loop", value=gq.loop_mode.value, inline=True)
        embed.add_field(name="Volume", value=f"{int(gq.volume * 100)}%", inline=True)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="volume", description="Set the volume (0-100)")
    async def volume(self, ctx: commands.Context, vol: int):
        if not self._check_dj(ctx):
            await ctx.send("You need the DJ role to change volume.")
            return
        if not 0 <= vol <= 100:
            await ctx.send("Volume must be between 0 and 100.")
            return
        gq = self.queue_manager.get(ctx.guild.id)
        gq.volume = vol / 100
        if ctx.voice_client and ctx.voice_client.source:
            ctx.voice_client.source.volume = gq.volume
        await ctx.send(f"Volume set to **{vol}%**.")

    @commands.hybrid_command(name="nowplaying", aliases=["np"], description="Show the currently playing track")
    async def nowplaying(self, ctx: commands.Context):
        gq = self.queue_manager.get(ctx.guild.id)
        if not gq.current:
            await ctx.send("Nothing is playing.")
            return

        elapsed = int(time.time() - gq.start_time) if gq.start_time else 0
        duration = gq.current.duration

        # Progress bar
        bar_length = 20
        if duration > 0:
            progress = min(elapsed / duration, 1.0)
            filled = int(bar_length * progress)
            bar = "▬" * filled + "🔘" + "▬" * (bar_length - filled)
            progress_text = f"{bar} `{format_duration(elapsed)} / {format_duration(duration)}`"
        else:
            progress_text = f"🔴 Live | `{format_duration(elapsed)}`"

        embed = discord.Embed(
            title="Now Playing",
            description=f"[{gq.current.title}]({gq.current.url})",
            color=discord.Color.green(),
        )
        embed.add_field(name="Progress", value=progress_text, inline=False)
        embed.add_field(name="Requested by", value=gq.current.requester, inline=True)
        embed.add_field(name="Volume", value=f"{int(gq.volume * 100)}%", inline=True)
        embed.add_field(name="Loop", value=gq.loop_mode.value, inline=True)
        if gq.current.thumbnail:
            embed.set_thumbnail(url=gq.current.thumbnail)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="loop", description="Set loop mode: off, track, or queue")
    async def loop(self, ctx: commands.Context, mode: str):
        mode = mode.lower()
        try:
            loop_mode = LoopMode(mode)
        except ValueError:
            await ctx.send("Invalid loop mode. Choose `off`, `track`, or `queue`.")
            return
        gq = self.queue_manager.get(ctx.guild.id)
        gq.loop_mode = loop_mode
        await ctx.send(f"Loop mode set to **{mode}**.")

    @commands.hybrid_command(name="shuffle", description="Shuffle the queue")
    async def shuffle(self, ctx: commands.Context):
        if not self._check_dj(ctx):
            await ctx.send("You need the DJ role to shuffle.")
            return
        gq = self.queue_manager.get(ctx.guild.id)
        if not gq.queue:
            await ctx.send("The queue is empty.")
            return
        gq.shuffle()
        await ctx.send("Queue shuffled.")

    @commands.hybrid_command(name="seek", description="Seek to a position (e.g. 1:30)")
    async def seek(self, ctx: commands.Context, timestamp: str):
        if not ctx.voice_client or not ctx.voice_client.is_playing():
            await ctx.send("Nothing is playing.")
            return
        gq = self.queue_manager.get(ctx.guild.id)
        if not gq.current:
            await ctx.send("Nothing is playing.")
            return

        try:
            seconds = parse_timestamp(timestamp)
        except (ValueError, IndexError):
            await ctx.send("Invalid timestamp. Use format like `1:30` or `90`.")
            return

        if gq.current.duration and seconds > gq.current.duration:
            await ctx.send("Timestamp exceeds track duration.")
            return

        ctx.voice_client.stop()
        try:
            source = await YTDLSource.create_source(
                gq.current.url or gq.current.search_query,
                loop=self.bot.loop,
                volume=gq.volume,
                seek_to=seconds,
            )
        except Exception as e:
            await ctx.send(f"Error seeking: {e}")
            return

        gq.start_time = time.time() - seconds

        def after_play(error):
            if error:
                print(f"Playback error: {error}")
            asyncio.run_coroutine_threadsafe(self._play_next_async(ctx), self.bot.loop)

        ctx.voice_client.play(source, after=after_play)
        await ctx.send(f"Seeked to **{timestamp}**.")

    @commands.hybrid_command(name="remove", description="Remove a song from the queue by position")
    async def remove(self, ctx: commands.Context, position: int):
        if not self._check_dj(ctx):
            await ctx.send("You need the DJ role to remove songs.")
            return
        gq = self.queue_manager.get(ctx.guild.id)
        removed = gq.remove(position - 1)  # 1-indexed for users
        if removed:
            await ctx.send(f"Removed **{removed.title}** from the queue.")
        else:
            await ctx.send("Invalid position.")

    @commands.hybrid_command(name="search", description="Search YouTube and pick a result")
    async def search(self, ctx: commands.Context, *, query: str):
        async with ctx.typing():
            results = await YTDLSource.search_results(query, count=5, loop=self.bot.loop)

        if not results:
            await ctx.send("No results found.")
            return

        embed = discord.Embed(title=f"Search results for: {query}", color=discord.Color.orange())
        reactions = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
        for i, entry in enumerate(results[:5]):
            title = entry.get("title", "Unknown")
            duration = format_duration(entry.get("duration") or 0)
            embed.add_field(name=f"{reactions[i]} {title}", value=f"Duration: {duration}", inline=False)

        msg = await ctx.send(embed=embed)
        for i in range(min(len(results), 5)):
            await msg.add_reaction(reactions[i])

        def check(reaction, user):
            return user == ctx.author and str(reaction.emoji) in reactions and reaction.message.id == msg.id

        try:
            reaction, _ = await self.bot.wait_for("reaction_add", timeout=30.0, check=check)
        except asyncio.TimeoutError:
            await msg.edit(content="Search timed out.", embed=None)
            return

        index = reactions.index(str(reaction.emoji))
        chosen = results[index]

        vc = await self._ensure_voice(ctx)
        if not vc:
            return

        gq = self.queue_manager.get(ctx.guild.id)
        song = Song(
            title=chosen.get("title", "Unknown"),
            url=chosen.get("webpage_url", ""),
            search_query=chosen.get("title", ""),
            requester=ctx.author.display_name,
            duration=chosen.get("duration") or 0,
            thumbnail=chosen.get("thumbnail", ""),
        )
        gq.add(song)

        if vc.is_playing() or vc.is_paused():
            await ctx.send(f"Added **{song.title}** to the queue.")
        else:
            next_song = gq.next()
            if next_song:
                await self._play_song(ctx, next_song)

    @commands.hybrid_command(name="lyrics", description="Show lyrics for the current track")
    async def lyrics(self, ctx: commands.Context):
        gq = self.queue_manager.get(ctx.guild.id)
        if not gq.current:
            await ctx.send("Nothing is playing.")
            return

        async with ctx.typing():
            lyrics = await self.lyrics_fetcher.fetch_lyrics(gq.current.title)

        if not lyrics:
            await ctx.send(f"No lyrics found for **{gq.current.title}**.")
            return

        chunks = LyricsFetcher.split_lyrics(lyrics)
        for i, chunk in enumerate(chunks):
            embed = discord.Embed(
                title=f"Lyrics - {gq.current.title}" if i == 0 else f"Lyrics (cont.)",
                description=chunk,
                color=discord.Color.purple(),
            )
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="sponsorblock", aliases=["sb"], description="Toggle SponsorBlock auto-skip on/off")
    async def sponsorblock(self, ctx: commands.Context):
        gq = self.queue_manager.get(ctx.guild.id)
        gq.sponsorblock = not gq.sponsorblock
        state = "enabled" if gq.sponsorblock else "disabled"
        await ctx.send(f"SponsorBlock is now **{state}**.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
