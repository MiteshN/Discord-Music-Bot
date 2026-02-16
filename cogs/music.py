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
from utils.cache import CacheManager

YOUTUBE_PLAYLIST_RE = re.compile(r"(youtube\.com/.*[?&]list=|youtu\.be/.*[?&]list=)")


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


class NowPlayingView(discord.ui.View):
    def __init__(self, cog, ctx):
        super().__init__(timeout=None)
        self.cog = cog
        self.ctx = ctx

    def _in_voice(self, interaction: discord.Interaction) -> bool:
        return (
            interaction.user.voice
            and interaction.guild.voice_client
            and interaction.user.voice.channel == interaction.guild.voice_client.channel
        )

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.primary)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._in_voice(interaction):
            await interaction.response.send_message("You need to be in the voice channel.", ephemeral=True)
            return
        vc = interaction.guild.voice_client
        if vc.is_playing():
            vc.pause()
            await interaction.response.send_message("Paused.", ephemeral=True)
        elif vc.is_paused():
            vc.resume()
            await interaction.response.send_message("Resumed.", ephemeral=True)
        else:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.primary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._in_voice(interaction):
            await interaction.response.send_message("You need to be in the voice channel.", ephemeral=True)
            return
        vc = interaction.guild.voice_client
        if not vc.is_playing() and not vc.is_paused():
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return
        vc.stop()
        await interaction.response.send_message("Skipped.", ephemeral=True)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._in_voice(interaction):
            await interaction.response.send_message("You need to be in the voice channel.", ephemeral=True)
            return
        vc = interaction.guild.voice_client
        gq = self.cog.queue_manager.get(interaction.guild.id)
        gq.clear()
        await self.cog._set_vc_status(vc, None)
        vc.stop()
        await vc.disconnect()
        self.stop()
        await interaction.response.send_message("Stopped and disconnected.", ephemeral=True)

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary)
    async def loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._in_voice(interaction):
            await interaction.response.send_message("You need to be in the voice channel.", ephemeral=True)
            return
        gq = self.cog.queue_manager.get(interaction.guild.id)
        # Cycle: off -> track -> queue -> off
        cycle = [LoopMode.OFF, LoopMode.TRACK, LoopMode.QUEUE]
        current_idx = cycle.index(gq.loop_mode)
        gq.loop_mode = cycle[(current_idx + 1) % len(cycle)]
        labels = {LoopMode.OFF: "Loop: Off", LoopMode.TRACK: "Loop: Track", LoopMode.QUEUE: "Loop: Queue"}
        await interaction.response.send_message(f"**{labels[gq.loop_mode]}**", ephemeral=True)

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary)
    async def shuffle(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._in_voice(interaction):
            await interaction.response.send_message("You need to be in the voice channel.", ephemeral=True)
            return
        gq = self.cog.queue_manager.get(interaction.guild.id)
        if not gq.queue:
            await interaction.response.send_message("Queue is empty.", ephemeral=True)
            return
        gq.shuffle()
        await interaction.response.send_message("Queue shuffled.", ephemeral=True)


class SearchSelectView(discord.ui.View):
    def __init__(self, *, options, results, cog, ctx, author_id):
        super().__init__(timeout=30)
        self.results = results
        self.cog = cog
        self.ctx = ctx
        self.author_id = author_id
        self.select = discord.ui.Select(
            placeholder="Pick a track...",
            options=options,
        )
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This isn't your search.", ephemeral=True)
            return

        index = int(self.select.values[0])
        chosen = self.results[index]

        vc = await self.cog._ensure_voice(self.ctx)
        if not vc:
            await interaction.response.send_message("You need to be in a voice channel.", ephemeral=True)
            return

        gq = self.cog.queue_manager.get(self.ctx.guild.id)
        song = Song(
            title=chosen.get("title", "Unknown"),
            url=chosen.get("webpage_url", ""),
            search_query=chosen.get("title", ""),
            requester=self.ctx.author.display_name,
            duration=chosen.get("duration") or 0,
            thumbnail=chosen.get("thumbnail", ""),
        )
        gq.add(song)

        if vc.is_playing() or vc.is_paused():
            await interaction.response.send_message(f"Added **{song.title}** to the queue.")
        else:
            await interaction.response.defer()
            next_song = gq.next()
            if next_song:
                await self.cog._play_song(self.ctx, next_song)
        self.stop()

    async def on_timeout(self):
        self.select.disabled = True
        self.select.placeholder = "Search timed out"
        try:
            msg = self.select.view.message if hasattr(self.select.view, 'message') else None
        except Exception:
            pass


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.queue_manager = QueueManager()
        self.spotify = SpotifyResolver()
        self.lyrics_fetcher = LyricsFetcher()
        self.cache_manager = CacheManager()
        asyncio.create_task(self.cache_manager.initialize())
        self.auto_disconnect_task.start()

    def cog_unload(self):
        self.auto_disconnect_task.cancel()
        asyncio.create_task(self.cache_manager.close())

    # --- Helpers ---

    async def _set_vc_status(self, vc: discord.VoiceClient, status: str | None):
        try:
            await vc.channel.edit(status=status)
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            pass

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

    async def _play_song(self, ctx: commands.Context, song: Song):
        gq = self.queue_manager.get(ctx.guild.id)
        gq.current = song
        gq.skip_votes.clear()

        try:
            source = await YTDLSource.create_source(
                song.url or song.search_query,
                loop=self.bot.loop,
                volume=gq.volume,
                audio_filter=gq.audio_filter,
                cache_manager=self.cache_manager,
            )
        except Exception as e:
            await ctx.send(f"Error playing **{song.title}**: {e}")
            self._play_next(ctx)
            return

        song.title = source.title
        song.duration = source.duration
        song.thumbnail = source.thumbnail
        song.url = source.webpage_url
        gq.start_time = time.time()

        def after_play(error):
            if error:
                print(f"Playback error: {error}")
            asyncio.run_coroutine_threadsafe(self._play_next_async(ctx), self.bot.loop)

        ctx.voice_client.play(source, after=after_play)

        # Set voice channel status
        vc_status = f"🎵 {song.title}"
        if len(vc_status) > 500:
            vc_status = vc_status[:497] + "..."
        await self._set_vc_status(ctx.voice_client, vc_status)

        if song.duration > 0:
            bar = "🔘" + "▬" * 20
            progress_text = f"{bar} `0:00 / {format_duration(song.duration)}`"
        else:
            progress_text = "🔴 Live"

        embed = discord.Embed(
            title="Now Playing",
            description=f"[{song.title}]({song.url})",
            color=discord.Color.green(),
        )
        embed.add_field(name="Progress", value=progress_text, inline=False)
        embed.add_field(name="Requested by", value=song.requester, inline=True)
        if song.thumbnail:
            embed.set_thumbnail(url=song.thumbnail)
        view = NowPlayingView(cog=self, ctx=ctx)
        await ctx.send(embed=embed, view=view)

    async def _play_next_async(self, ctx: commands.Context):
        gq = self.queue_manager.get(ctx.guild.id)
        next_song = gq.next()
        if next_song:
            await self._play_song(ctx, next_song)
        elif ctx.voice_client:
            await self._set_vc_status(ctx.voice_client, None)

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
            if gq.twenty_four_seven:
                continue
            if not vc.is_playing() and not vc.is_paused() and not gq.queue:
                if gq.start_time and (time.time() - gq.start_time) > 180:
                    gq.clear()
                    self.queue_manager.remove(vc.guild.id)
                    await self._set_vc_status(vc, None)
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

    @commands.hybrid_command(name="playtop", aliases=["pt"], description="Add a song to the top of the queue")
    @app_commands.autocomplete(query=play_autocomplete)
    async def playtop(self, ctx: commands.Context, *, query: str):
        vc = await self._ensure_voice(ctx)
        if not vc:
            return

        gq = self.queue_manager.get(ctx.guild.id)

        # If nothing is playing, just play normally
        if not vc.is_playing() and not vc.is_paused():
            song = Song(title=query, url=query, search_query=query, requester=ctx.author.display_name)
            gq.add(song)
            next_song = gq.next()
            if next_song:
                await self._play_song(ctx, next_song)
            return

        # Spotify handling
        if SpotifyResolver.is_spotify_url(query):
            async with ctx.typing():
                searches = await self.bot.loop.run_in_executor(None, self.spotify.resolve, query)
            if not searches:
                await ctx.send("Could not resolve Spotify URL.")
                return
            for s in reversed(searches):
                song = Song(title=s, url="", search_query=s, requester=ctx.author.display_name)
                gq.add_top(song)
            await ctx.send(f"Added **{len(searches)}** track(s) from Spotify to the top of the queue.")
            return

        song = Song(title=query, url=query, search_query=query, requester=ctx.author.display_name)
        gq.add_top(song)
        await ctx.send(f"Added **{query}** to the top of the queue.")

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
            await self._set_vc_status(ctx.voice_client, None)
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
        await self._set_vc_status(ctx.voice_client, None)
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
                audio_filter=gq.audio_filter,
                cache_manager=self.cache_manager,
            )
        except Exception as e:
            await ctx.send(f"Error seeking: {e}")
            return

        gq.start_time = time.time() - seconds

        # Prevent after callback from advancing queue
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
        options = []
        for i, entry in enumerate(results[:5], 1):
            title = entry.get("title", "Unknown")
            duration = format_duration(entry.get("duration") or 0)
            embed.add_field(name=f"{i}. {title}", value=f"Duration: {duration}", inline=False)
            options.append(discord.SelectOption(
                label=f"{i}. {title}"[:100],
                description=f"Duration: {duration}",
                value=str(i - 1),
            ))

        view = SearchSelectView(
            options=options,
            results=results,
            cog=self,
            ctx=ctx,
            author_id=ctx.author.id,
        )
        await ctx.send(embed=embed, view=view)

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


    # --- Audio Filter Commands ---

    async def _apply_filter(self, ctx: commands.Context):
        """Restart playback from current position with the active audio filter."""
        gq = self.queue_manager.get(ctx.guild.id)
        if not gq.current:
            return
        if not ctx.voice_client or (not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused()):
            return

        elapsed = int(time.time() - gq.start_time) if gq.start_time else 0
        ctx.voice_client.stop()

        try:
            source = await YTDLSource.create_source(
                gq.current.url or gq.current.search_query,
                loop=self.bot.loop,
                volume=gq.volume,
                seek_to=elapsed,
                audio_filter=gq.audio_filter,
                cache_manager=self.cache_manager,
            )
        except Exception as e:
            await ctx.send(f"Error applying filter: {e}")
            return

        gq.start_time = time.time() - elapsed

        def after_play(error):
            if error:
                print(f"Playback error: {error}")
            asyncio.run_coroutine_threadsafe(self._play_next_async(ctx), self.bot.loop)

        ctx.voice_client.play(source, after=after_play)

    @commands.hybrid_command(name="nightcore", description="Apply nightcore effect (speed up + pitch up)")
    async def nightcore(self, ctx: commands.Context):
        if not ctx.voice_client or (not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused()):
            await ctx.send("Nothing is playing.")
            return
        gq = self.queue_manager.get(ctx.guild.id)
        gq.audio_filter = "asetrate=48000*1.25,aresample=48000,atempo=1.0"
        gq.audio_filter_name = "Nightcore"
        await self._apply_filter(ctx)
        await ctx.send("Applied **Nightcore** effect.")

    @commands.hybrid_command(name="vaporwave", description="Apply vaporwave effect (slow down + pitch down)")
    async def vaporwave(self, ctx: commands.Context):
        if not ctx.voice_client or (not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused()):
            await ctx.send("Nothing is playing.")
            return
        gq = self.queue_manager.get(ctx.guild.id)
        gq.audio_filter = "asetrate=48000*0.8,aresample=48000,atempo=1.0"
        gq.audio_filter_name = "Vaporwave"
        await self._apply_filter(ctx)
        await ctx.send("Applied **Vaporwave** effect.")

    @commands.hybrid_command(name="bassboost", description="Boost bass frequencies")
    async def bassboost(self, ctx: commands.Context):
        if not ctx.voice_client or (not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused()):
            await ctx.send("Nothing is playing.")
            return
        gq = self.queue_manager.get(ctx.guild.id)
        gq.audio_filter = "bass=g=10"
        gq.audio_filter_name = "Bass Boost"
        await self._apply_filter(ctx)
        await ctx.send("Applied **Bass Boost** effect.")

    @commands.hybrid_command(name="speed", description="Change playback speed (0.5-2.0)")
    async def speed(self, ctx: commands.Context, rate: float):
        if not ctx.voice_client or (not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused()):
            await ctx.send("Nothing is playing.")
            return
        if not 0.5 <= rate <= 2.0:
            await ctx.send("Speed must be between 0.5 and 2.0.")
            return
        gq = self.queue_manager.get(ctx.guild.id)
        gq.audio_filter = f"atempo={rate}"
        gq.audio_filter_name = f"Speed {rate}x"
        await self._apply_filter(ctx)
        await ctx.send(f"Applied **Speed {rate}x** effect.")

    @commands.hybrid_command(name="tremolo", description="Apply tremolo effect (volume oscillation)")
    async def tremolo(self, ctx: commands.Context):
        if not ctx.voice_client or (not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused()):
            await ctx.send("Nothing is playing.")
            return
        gq = self.queue_manager.get(ctx.guild.id)
        gq.audio_filter = "tremolo=f=4:d=0.7"
        gq.audio_filter_name = "Tremolo"
        await self._apply_filter(ctx)
        await ctx.send("Applied **Tremolo** effect.")

    @commands.hybrid_command(name="vibrato", description="Apply vibrato effect (pitch oscillation)")
    async def vibrato(self, ctx: commands.Context):
        if not ctx.voice_client or (not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused()):
            await ctx.send("Nothing is playing.")
            return
        gq = self.queue_manager.get(ctx.guild.id)
        gq.audio_filter = "vibrato=f=4:d=0.5"
        gq.audio_filter_name = "Vibrato"
        await self._apply_filter(ctx)
        await ctx.send("Applied **Vibrato** effect.")

    @commands.hybrid_command(name="8d", description="Apply 8D audio effect (stereo rotation)")
    async def eightd(self, ctx: commands.Context):
        if not ctx.voice_client or (not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused()):
            await ctx.send("Nothing is playing.")
            return
        gq = self.queue_manager.get(ctx.guild.id)
        gq.audio_filter = "apulsator=hz=0.15"
        gq.audio_filter_name = "8D"
        await self._apply_filter(ctx)
        await ctx.send("Applied **8D** audio effect.")

    @commands.hybrid_command(name="cleareffect", description="Remove all audio effects")
    async def cleareffect(self, ctx: commands.Context):
        gq = self.queue_manager.get(ctx.guild.id)
        if not gq.audio_filter:
            await ctx.send("No audio effects are active.")
            return
        if not ctx.voice_client or (not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused()):
            gq.audio_filter = ""
            gq.audio_filter_name = ""
            await ctx.send("Cleared audio effects.")
            return
        gq.audio_filter = ""
        gq.audio_filter_name = ""
        await self._apply_filter(ctx)
        await ctx.send("Cleared all audio effects.")

    @commands.hybrid_command(name="cachestats", description="Show audio cache statistics")
    async def cachestats(self, ctx: commands.Context):
        stats = await self.cache_manager.get_stats()
        total = stats["hits"] + stats["misses"]
        ratio = f"{stats['hits'] / total * 100:.0f}%" if total > 0 else "N/A"
        embed = discord.Embed(title="Audio Cache Stats", color=discord.Color.teal())
        embed.add_field(name="Cached Files", value=str(stats["count"]), inline=True)
        embed.add_field(name="Size", value=f"{stats['total_size_mb']} / {stats['max_size_mb']} MB", inline=True)
        embed.add_field(name="Hit Rate", value=f"{ratio} ({stats['hits']} hits, {stats['misses']} misses)", inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="clearcache", description="Clear the audio cache")
    async def clearcache(self, ctx: commands.Context):
        if not self._check_dj(ctx):
            await ctx.send("You need the DJ role to clear the cache.")
            return
        await self.cache_manager.clear_all()
        await ctx.send("Audio cache cleared.")

    @commands.hybrid_command(name="247", description="Toggle 24/7 mode (stay in voice channel)")
    async def twenty_four_seven(self, ctx: commands.Context):
        if not self._check_dj(ctx):
            await ctx.send("You need the DJ role to toggle 24/7 mode.")
            return
        gq = self.queue_manager.get(ctx.guild.id)
        gq.twenty_four_seven = not gq.twenty_four_seven
        state = "enabled" if gq.twenty_four_seven else "disabled"
        await ctx.send(f"24/7 mode **{state}**. {'I will stay in the voice channel.' if gq.twenty_four_seven else 'I will auto-disconnect after inactivity.'}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
