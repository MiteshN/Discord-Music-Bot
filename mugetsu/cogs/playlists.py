from __future__ import annotations

import random
import re

import discord
from discord import app_commands
from discord.ext import commands

from mugetsu.cogs.common import MusicCog
from mugetsu.player.manager import Requester
from mugetsu.player.models import PlayerError, Song
from mugetsu.ui import embeds

SHARE_CODE = re.compile(r"^[A-Za-z0-9]{8}$")


class Playlists(MusicCog):
    """Your saved playlists. They belong to you and work in any server."""

    @property
    def store(self):
        return self.players.store

    async def name_autocomplete(self, interaction: discord.Interaction, current: str):
        lists = await self.store.playlists(interaction.user.id)
        current = current.lower()
        return [app_commands.Choice(name=f"{p.name} ({len(p.tracks)} songs)"[:100], value=p.name)
                for p in lists if current in p.name.lower()][:25]

    async def _owned(self, ctx: commands.Context, name: str):
        playlist = await self.store.playlist(ctx.author.id, name)
        if playlist is None:
            raise PlayerError(f"You don't have a playlist called “{name}”. See `/playlist list`.")
        return playlist

    @commands.hybrid_group(name="playlist", aliases=["playlists"], fallback="list", description="Your saved playlists")
    async def playlist(self, ctx: commands.Context):
        lists = await self.store.playlists(ctx.author.id)
        await ctx.send(embed=embeds.playlist_list(ctx.author.display_name, lists), ephemeral=True)

    @playlist.command(name="save", description="Save the current song and queue as a playlist (replaces one with the same name)")
    @app_commands.describe(name="Playlist name")
    @app_commands.autocomplete(name=name_autocomplete)
    async def save(self, ctx: commands.Context, *, name: str):
        player = self.player(ctx)
        if player.game is not None:
            raise PlayerError("No saving the answers during guess the song! 🙈")
        songs = ([player.current] if player.current else []) + list(player.q.queue)
        if not songs:
            raise PlayerError("There's nothing playing or queued to save.")
        try:
            count = await self.store.save_playlist(ctx.author.id, name, [s.to_record() for s in songs])
        except ValueError as e:
            raise PlayerError(str(e)) from None
        await ctx.send(f"💾 Saved **{count}** songs to **{discord.utils.escape_markdown(name)}**.")

    @playlist.command(name="load", description="Queue one of your playlists, or one shared with you by code")
    @app_commands.describe(name="Your playlist's name, or a share code", shuffle="Shuffle it first")
    @app_commands.autocomplete(name=name_autocomplete)
    async def load(self, ctx: commands.Context, name: str, shuffle: bool = False):
        await ctx.defer()
        playlist = await self.store.playlist(ctx.author.id, name)
        if playlist is None and SHARE_CODE.match(name.strip()):
            playlist = await self.store.playlist_by_code(name)
        if playlist is None:
            raise PlayerError(f"No playlist called “{name}” (or with that share code).")
        if not playlist.tracks:
            raise PlayerError("That playlist is empty.")
        who = Requester.of(ctx.author).fields()
        songs = [Song.from_record(t, who) for t in playlist.tracks]
        if shuffle:
            random.shuffle(songs)
        await self.players.join(ctx.author)
        await self.announcer.enqueue_and_reply(
            self.player(ctx), songs, playlist.name, channel_id=ctx.channel.id, send=ctx.send, actor=ctx.author
        )

    @playlist.command(name="show", description="See what's in one of your playlists")
    @app_commands.describe(name="Playlist name", page="Page number")
    @app_commands.autocomplete(name=name_autocomplete)
    async def show(self, ctx: commands.Context, name: str, page: int = 1):
        await ctx.send(embed=embeds.playlist_detail(await self._owned(ctx, name), page), ephemeral=True)

    @playlist.command(name="add", description="Add the current song to a playlist (creates it if needed)")
    @app_commands.describe(name="Playlist name")
    @app_commands.autocomplete(name=name_autocomplete)
    async def add(self, ctx: commands.Context, *, name: str):
        player = self.player(ctx)
        if player.game is not None:
            raise PlayerError("No saving the answers during guess the song! 🙈")
        if player.current is None:
            raise PlayerError("Nothing is playing.")
        try:
            count = await self.store.add_tracks(ctx.author.id, name, [player.current.to_record()])
        except ValueError as e:
            raise PlayerError(str(e)) from None
        await ctx.send(f"➕ Added **{discord.utils.escape_markdown(player.current.title)}** to "
                       f"**{discord.utils.escape_markdown(name)}** ({count} songs).", ephemeral=True)

    @playlist.command(name="remove", description="Remove a song from one of your playlists")
    @app_commands.describe(name="Playlist name", position="Song number (see /playlist show)")
    @app_commands.autocomplete(name=name_autocomplete)
    async def remove(self, ctx: commands.Context, name: str, position: int):
        await self._owned(ctx, name)
        removed = await self.store.remove_track(ctx.author.id, name, position - 1)
        if removed is None:
            raise PlayerError("There's no song at that position.")
        await ctx.send(f"🗑️ Removed **{discord.utils.escape_markdown(removed.get('title', '?'))}**.", ephemeral=True)

    @playlist.command(name="delete", description="Delete one of your playlists")
    @app_commands.describe(name="Playlist name")
    @app_commands.autocomplete(name=name_autocomplete)
    async def delete(self, ctx: commands.Context, *, name: str):
        if not await self.store.delete_playlist(ctx.author.id, name):
            raise PlayerError(f"You don't have a playlist called “{name}”.")
        await ctx.send(f"🗑️ Deleted **{discord.utils.escape_markdown(name)}**.", ephemeral=True)

    @playlist.command(name="rename", description="Rename one of your playlists")
    @app_commands.describe(name="Current name", new_name="New name")
    @app_commands.autocomplete(name=name_autocomplete)
    async def rename(self, ctx: commands.Context, name: str, *, new_name: str):
        try:
            if not await self.store.rename_playlist(ctx.author.id, name, new_name):
                raise PlayerError(f"You don't have a playlist called “{name}”.")
        except ValueError as e:
            raise PlayerError(str(e)) from None
        await ctx.send(f"✏️ Renamed to **{discord.utils.escape_markdown(new_name)}**.", ephemeral=True)

    @playlist.command(name="share", description="Get a code anyone can use to load or copy one of your playlists")
    @app_commands.describe(name="Playlist name")
    @app_commands.autocomplete(name=name_autocomplete)
    async def share(self, ctx: commands.Context, *, name: str):
        await self._owned(ctx, name)
        code = await self.store.share_code(ctx.author.id, name)
        await ctx.send(f"🔗 Share code for **{discord.utils.escape_markdown(name)}**: `{code}`\n"
                       f"Anyone can play it with `/playlist load {code}` or keep a copy with `/playlist copy {code}`.")

    @playlist.command(name="copy", description="Copy a shared playlist into your own")
    @app_commands.describe(code="The share code", name="What to call your copy")
    async def copy(self, ctx: commands.Context, code: str, *, name: str = ""):
        shared = await self.store.playlist_by_code(code)
        if shared is None:
            raise PlayerError("No playlist has that share code.")
        new_name = name.strip() or shared.name
        if await self.store.playlist(ctx.author.id, new_name):
            raise PlayerError(f"You already have a playlist called “{new_name}”. Give the copy another name.")
        try:
            count = await self.store.save_playlist(ctx.author.id, new_name, shared.tracks)
        except ValueError as e:
            raise PlayerError(str(e)) from None
        await ctx.send(f"📋 Copied **{count}** songs into **{discord.utils.escape_markdown(new_name)}**.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Playlists(bot))
