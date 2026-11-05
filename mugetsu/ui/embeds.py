from __future__ import annotations

import itertools
from typing import TYPE_CHECKING

import discord

from mugetsu.player.models import LoopMode, Song
from mugetsu.util import format_duration

if TYPE_CHECKING:
    from mugetsu.player.player import GuildPlayer

ACCENT = discord.Color(0x8B5CF6)
QUEUE_PAGE_SIZE = 10


def song_length(song: Song) -> str:
    if song.is_live:
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
    url = song.url or song.origin_url
    return f"[{title}]({url})" if url else f"**{title}**"


def now_playing(player: GuildPlayer, *, progress: bool = False) -> discord.Embed:
    song = player.current
    q = player.q
    embed = discord.Embed(description=f"### {md_link(song, 200)}", color=ACCENT)
    embed.set_author(name="Now playing")
    if song.thumbnail:
        embed.set_thumbnail(url=song.thumbnail)
    embed.add_field(name="Duration", value=song_length(song))
    embed.add_field(name="Requested by", value=song.requester)
    if q.queue:
        embed.add_field(name="Up next", value=md_link(q.queue[0], 60), inline=False)
    if progress:
        embed.add_field(name="Progress", value=progress_bar(q.position, song.duration), inline=False)
    footer = [f"Volume {round(player.volume * 100)}%"]
    if q.loop_mode is not LoopMode.OFF:
        footer.append(f"Loop: {q.loop_mode.value}")
    if q.audio_filter:
        footer.append(f"Effect: {q.audio_filter.label}")
    if q.queue:
        footer.append(f"{len(q.queue)} in queue")
    embed.set_footer(text=" · ".join(footer))
    return embed


def added(player: GuildPlayer, songs: list[Song], label: str, top: bool) -> discord.Embed:
    q = player.q
    if len(songs) == 1:
        song = songs[0]
        position = 1 if top else len(q.queue)
        embed = discord.Embed(description=f"Added {md_link(song)} to the queue", color=ACCENT)
        if song.thumbnail:
            embed.set_thumbnail(url=song.thumbnail)
        embed.add_field(name="Position", value=f"#{position}")
        embed.add_field(name="Duration", value=song_length(song))
        if q.current and q.current.duration:
            ahead = list(itertools.islice(q.queue, position - 1))
            wait = max(q.current.duration - q.position, 0) + sum(s.duration for s in ahead)
            embed.add_field(name="Plays in", value=f"~{format_duration(wait)}")
        return embed
    total = sum(s.duration for s in songs)
    where = "the top of the queue" if top else "the queue"
    source = f" from **{discord.utils.escape_markdown(label)}**" if label else ""
    embed = discord.Embed(description=f"Added **{len(songs)}** tracks{source} to {where}", color=ACCENT)
    if total:
        embed.set_footer(text=f"Total length {format_duration(total)}")
    return embed


def queue_page(player: GuildPlayer, page: int = 1) -> discord.Embed:
    q = player.q
    pages = max(1, -(-len(q.queue) // QUEUE_PAGE_SIZE))
    page = min(max(page, 1), pages)
    start = (page - 1) * QUEUE_PAGE_SIZE

    lines = []
    if q.current:
        vc = player.voice
        state = "⏸️" if vc and vc.is_paused() else "▶️"
        lines += [f"{state} {md_link(q.current)}",
                  progress_bar(q.position, q.current.duration) + f" · {q.current.requester}", ""]
    if q.queue:
        lines.append("**Up next**")
        for i, song in enumerate(itertools.islice(q.queue, start, start + QUEUE_PAGE_SIZE), start + 1):
            lines.append(f"`{i}.` {md_link(song, 60)} · `{song_length(song)}`")
    else:
        lines.append("*Nothing queued.*")

    embed = discord.Embed(title="Queue", description="\n".join(lines), color=ACCENT)
    footer = [f"Page {page}/{pages}", f"{len(q.queue)} tracks"]
    if q.duration:
        footer.append(format_duration(q.duration))
    footer.append(f"Loop: {q.loop_mode.value}")
    embed.set_footer(text=" · ".join(footer))
    return embed


def search_results(query: str, results: list[dict]) -> discord.Embed:
    embed = discord.Embed(title=f"Results for “{query[:200]}”", color=ACCENT)
    embed.description = "\n".join(
        f"`{i}.` {discord.utils.escape_markdown(r['title'][:90])} · `{format_duration(r['duration'])}`"
        for i, r in enumerate(results, 1)
    )
    return embed


def cache_stats(stats: dict) -> discord.Embed:
    total = stats["hits"] + stats["misses"]
    ratio = f"{stats['hits'] / total * 100:.0f}%" if total else "N/A"
    embed = discord.Embed(title="Audio cache", color=ACCENT)
    embed.add_field(name="Cached tracks", value=str(stats["count"]))
    embed.add_field(name="Size", value=f"{stats['total_size_mb']} / {stats['max_size_mb']} MB")
    embed.add_field(name="Hit rate", value=f"{ratio} ({stats['hits']} hits, {stats['misses']} misses)", inline=False)
    return embed
