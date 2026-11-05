from __future__ import annotations

import asyncio
import logging
from typing import Literal

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from mugetsu.cogs.common import MusicCog, require_listener, require_listener_if_connected
from mugetsu.media import youtube
from mugetsu.media.lyrics import split_lyrics
from mugetsu.media.radio import parse_radio_query
from mugetsu.player.manager import URL_RE, Requester
from mugetsu.player.models import PlayerError
from mugetsu.ui import embeds
from mugetsu.ui.views import RadioSelectView, SearchSelectView, send_song_dm
from mugetsu.util import parse_timestamp

log = logging.getLogger("mugetsu.cogs.playback")


def no_peeking(player):
    if player.game is not None:
        raise PlayerError("No peeking during guess the song! 🙈")


class Playback(MusicCog):
    """Play, pause, skip and friends."""

    # --- Autocomplete ---

    async def _youtube_suggestions(self, query: str) -> list[str]:
        async with self.players.http.get(
            "https://suggestqueries.google.com/complete/search",
            params={"client": "firefox", "ds": "yt", "q": query},
            timeout=aiohttp.ClientTimeout(total=2),
        ) as resp:
            data = await resp.json(content_type=None)
            return data[1] if len(data) > 1 else []

    async def _spotify_suggestions(self, query: str, limit: int = 4) -> list[app_commands.Choice[str]]:
        spotify = self.players.spotify
        if not spotify.enabled:
            return []
        found = await asyncio.to_thread(spotify.search, query, limit, limit // 2)
        choices = [app_commands.Choice(name=f"Spotify · {s['name']} — {s['artist']}"[:100], value=s["url"])
                   for s in found["songs"]]
        choices += [app_commands.Choice(name=f"Spotify album · {a['title']} — {a['artist']}"[:100], value=a["url"])
                    for a in found["albums"]]
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

    # --- Commands ---

    async def _play(self, ctx: commands.Context, query: str, *, top: bool):
        await ctx.defer()
        await self.players.join(ctx.author)
        async with ctx.typing():
            songs, label = await self.players.resolve_query(query, Requester.of(ctx.author))
        await self.announcer.enqueue_and_reply(
            self.player(ctx), songs, label, channel_id=ctx.channel.id, send=ctx.send, top=top, actor=ctx.author
        )

    @commands.hybrid_command(name="play", aliases=["p"], description="Play a song or playlist from YouTube, Spotify, SoundCloud, or a search")
    @app_commands.describe(query="Song name or link")
    @app_commands.autocomplete(query=play_autocomplete)
    async def play(self, ctx: commands.Context, *, query: str):
        await self._play(ctx, query, top=False)

    @commands.hybrid_command(name="playtop", aliases=["pt", "playnext"], description="Add a song to the top of the queue")
    @app_commands.describe(query="Song name or link")
    @app_commands.autocomplete(query=play_autocomplete)
    async def playtop(self, ctx: commands.Context, *, query: str):
        await self._play(ctx, query, top=True)

    @commands.hybrid_command(name="search", description="Search YouTube and pick a result")
    @app_commands.describe(query="What to search for")
    async def search(self, ctx: commands.Context, *, query: str):
        await ctx.defer()
        async with ctx.typing():
            results = await youtube.search(query, count=5)
        if not results:
            raise PlayerError(f"No results for `{query}`.")
        view = SearchSelectView(self.bot, ctx.author, results)
        view.message = await ctx.send(embed=embeds.search_results(query, results), view=view)

    @commands.hybrid_command(name="join", aliases=["summon"], description="Bring the bot into your voice channel")
    async def join(self, ctx: commands.Context):
        vc = await self.players.join(ctx.author)
        self.player(ctx).text_channel_id = ctx.channel.id
        await ctx.send(f"👋 Joined {vc.channel.mention}.")

    @commands.hybrid_command(name="skip", aliases=["s", "next"], description="Skip the current track (vote if you're not a DJ)")
    async def skip(self, ctx: commands.Context):
        require_listener(ctx)
        await ctx.send(await self.player(ctx).skip(ctx.author))

    @commands.hybrid_command(name="skipto", aliases=["jump"], description="Jump to a song in the queue")
    @app_commands.describe(position="Position in the queue (see /queue)")
    async def skipto(self, ctx: commands.Context, position: int):
        require_listener(ctx)
        await ctx.send(await self.player(ctx).skip_to(position - 1, ctx.author))

    @commands.hybrid_command(name="previous", aliases=["back", "prev"], description="Go back to the previous track")
    async def previous(self, ctx: commands.Context):
        require_listener(ctx)
        await ctx.send(await self.player(ctx).previous(ctx.author))

    @commands.hybrid_command(name="pause", description="Pause playback")
    async def pause(self, ctx: commands.Context):
        require_listener(ctx)
        await ctx.send(await self.player(ctx).pause(ctx.author))

    @commands.hybrid_command(name="resume", aliases=["unpause"], description="Resume playback")
    async def resume(self, ctx: commands.Context):
        require_listener(ctx)
        await ctx.send(await self.player(ctx).resume(ctx.author))

    @commands.hybrid_command(name="stop", description="Stop playback, clear the queue and leave")
    async def stop(self, ctx: commands.Context):
        require_listener(ctx)
        await ctx.send(await self.player(ctx).stop(ctx.author))

    @commands.hybrid_command(name="disconnect", aliases=["dc", "leave"], description="Leave the voice channel")
    async def disconnect(self, ctx: commands.Context):
        await ctx.send(await self.player(ctx).stop(ctx.author))

    @commands.hybrid_command(name="seek", description="Jump to a position in the track (e.g. 1:30)")
    @app_commands.describe(timestamp="Position like 1:30, 1:02:03, or seconds")
    async def seek(self, ctx: commands.Context, timestamp: str):
        require_listener(ctx)
        try:
            seconds = parse_timestamp(timestamp)
        except ValueError:
            raise PlayerError("Invalid timestamp. Use a format like `1:30` or `90`.") from None
        await ctx.send(await self.player(ctx).seek(seconds, ctx.author))

    @commands.hybrid_command(name="replay", aliases=["restart"], description="Start the current track over")
    async def replay(self, ctx: commands.Context):
        require_listener(ctx)
        await ctx.send(await self.player(ctx).seek(0, ctx.author))

    @commands.hybrid_command(name="volume", aliases=["vol"], description="Show or set the volume (0-100)")
    @app_commands.describe(level="0-100. 100 gives the best audio quality")
    async def volume(self, ctx: commands.Context, level: app_commands.Range[int, 0, 100] | None = None):
        player = self.player(ctx)
        if level is None:
            await ctx.send(f"🔊 Volume is **{round(player.volume * 100)}%**.")
            return
        require_listener_if_connected(ctx)
        await ctx.send(await player.set_volume(level, ctx.author))

    @commands.hybrid_command(name="loop", aliases=["repeat"], description="Set loop mode (or cycle it)")
    @app_commands.describe(mode="off, track, or queue. Leave empty to cycle")
    async def loop(self, ctx: commands.Context, mode: Literal["off", "track", "queue"] | None = None):
        await ctx.send(await self.player(ctx).set_loop(mode, ctx.author))

    @commands.hybrid_command(name="nowplaying", aliases=["np"], description="Show the current track")
    async def nowplaying(self, ctx: commands.Context):
        player = self.player(ctx)
        no_peeking(player)
        if not player.current:
            raise PlayerError("Nothing is playing.")
        await ctx.send(embed=embeds.now_playing(player, progress=True))

    @commands.hybrid_command(name="lyrics", description="Show lyrics for the current track")
    async def lyrics(self, ctx: commands.Context):
        player = self.player(ctx)
        no_peeking(player)
        song = player.current
        if not song:
            raise PlayerError("Nothing is playing.")
        await ctx.defer()
        async with ctx.typing():
            found = await self.players.lyrics_for(song)
        if not found:
            raise PlayerError(f"No lyrics found for **{discord.utils.escape_markdown(song.title)}**.")
        for i, chunk in enumerate(split_lyrics(found.plain)):
            heading = f"Lyrics · {song.title}"[:256] if i == 0 else "Lyrics (cont.)"
            embed = discord.Embed(title=heading, description=chunk, color=embeds.ACCENT)
            embed.set_footer(text=f"Source: {found.source}")
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="save", aliases=["like", "heart"], description="Send the current song to your DMs")
    async def save(self, ctx: commands.Context):
        player = self.player(ctx)
        no_peeking(player)
        await ctx.send(await send_song_dm(ctx.author, player.current, ctx.guild.name), ephemeral=True)

    @commands.hybrid_command(name="autoplay", aliases=["ap"], description="Keep playing similar songs when the queue runs out")
    @app_commands.describe(mode="on or off. Leave empty to toggle")
    async def autoplay(self, ctx: commands.Context, mode: Literal["on", "off"] | None = None):
        player = self.player(ctx)
        enabled = (not player.autoplay) if mode is None else mode == "on"
        await ctx.send(await player.set_autoplay(enabled, ctx.author))

    @commands.hybrid_command(name="playrecent", aliases=["pr", "recent"], description="Queue the songs you requested most recently")
    @app_commands.describe(count="How many songs (1-50)")
    async def playrecent(self, ctx: commands.Context, count: app_commands.Range[int, 1, 50] = 10):
        await ctx.defer()
        songs = await self.players.recent_songs(ctx.guild.id, ctx.author, count)
        if not songs:
            raise PlayerError("You haven't requested anything here yet.")
        await self.players.join(ctx.author)
        await self.announcer.enqueue_and_reply(
            self.player(ctx), songs, "your recent songs", channel_id=ctx.channel.id, send=ctx.send, actor=ctx.author
        )

    @commands.hybrid_command(name="radio", description="Play an internet radio station (e.g. lofi, jazz, a station name)")
    @app_commands.describe(query="Station name or genre. Add --country=japan for one country, or --country=any for worldwide")
    async def radio(self, ctx: commands.Context, *, query: str = ""):
        await ctx.defer()
        name, country = parse_radio_query(query)
        try:
            stations = await self.players.radio.search(name, country, limit=6)
        except Exception as e:
            raise PlayerError(f"Couldn't reach the radio directory: {e}") from e
        if not stations:
            raise PlayerError("No stations found. Try another name, genre or country.")
        await self.players.join(ctx.author)
        player = self.player(ctx)
        song = self.players.station_song(stations[0], Requester.of(ctx.author))
        await self.announcer.enqueue_and_reply(player, [song], "", channel_id=ctx.channel.id, send=ctx.send,
                                               actor=ctx.author)
        if len(stations) > 1:
            view = RadioSelectView(self.bot, ctx.author, stations[1:])
            view.message = await ctx.send("Not the one? Pick another station:", view=view)

    # --- Events ---

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.id == self.bot.user.id:
            # Kicked or disconnected by someone else: drop the stale player state
            if before.channel and after.channel is None:
                await self.players.destroy(member.guild.id, disconnect=False)
            elif before.channel != after.channel:
                self.players.notify(member.guild.id)
            return
        # Someone joined or left the bot's channel: refresh the dashboard's listener list
        vc = member.guild.voice_client
        if vc and vc.channel in (before.channel, after.channel) and before.channel != after.channel:
            self.players.notify(member.guild.id)


async def setup(bot):
    await bot.add_cog(Playback(bot))
