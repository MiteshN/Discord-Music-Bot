from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from mugetsu.config import Config
from mugetsu.media.ffmpeg import AudioInput, ffmpeg_args
from mugetsu.player import player as player_module
from mugetsu.player.manager import PlayerHooks, PlayerManager
from mugetsu.player.models import Song
from tests.fakes import FakeBot, FakeGuild


class RecordingHooks(PlayerHooks):
    def __init__(self):
        self.notices: list[str] = []
        self.started: list[tuple[str, bool]] = []
        self.cleared = 0

    async def notice(self, player, text):
        self.notices.append(text)

    async def track_started(self, player, song, *, announce):
        self.started.append((song.title, announce))

    async def track_cleared(self, player):
        self.cleared += 1


def make_song(title: str, duration: int = 200, **kw) -> Song:
    return Song(title=title, query=title, url=f"https://youtu.be/{title[:11]:_<11}", duration=duration,
                requester=kw.pop("requester", "tester"), requester_id=kw.pop("requester_id", 1), **kw)


async def settle(rounds: int = 5):
    for _ in range(rounds):
        await asyncio.sleep(0)


@pytest.fixture
def guild():
    return FakeGuild(1)


@pytest.fixture
async def manager(guild, tmp_path, monkeypatch):
    monkeypatch.setattr(player_module, "PREFETCH_DELAY", 0)
    bot = FakeBot(guild)
    mgr = PlayerManager(bot, Config(cache_dir=tmp_path, cache_limit_mb=0))
    mgr.hooks = RecordingHooks()
    mgr.failing: set[str] = set()

    async def resolve_input(song):
        if song.title in mgr.failing:
            raise RuntimeError("Video unavailable")
        return AudioInput(f"/cache/{song.title}.opus", is_local=True, is_opus=True)

    def make_source(inp, *, volume, audio_filter, position=0, bitrate=128):
        args = ffmpeg_args(inp, volume=volume, audio_filter=audio_filter, position=position)
        return SimpleNamespace(path=inp.path, position=position, volume=volume, filter=audio_filter,
                               passthrough=args.passthrough)

    async def prefetch(song):
        return False

    mgr.resolve_input = resolve_input
    mgr.make_source = make_source
    mgr.prefetch = prefetch
    yield mgr
    for guild_id in list(mgr._players):
        await mgr.destroy(guild_id)
    await settle()


@pytest.fixture
async def connected(manager, guild):
    """A player whose bot is already in the guild's voice channel."""
    await guild.channel.connect()
    return manager.get(guild.id)
