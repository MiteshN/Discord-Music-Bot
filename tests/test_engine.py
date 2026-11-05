"""The playback engine, driven through fake voice clients."""

from __future__ import annotations

import time

import pytest

from mugetsu.player.models import LoopMode, PlayerError
from tests.conftest import make_song, settle
from tests.fakes import FakeRole


async def test_enqueue_starts_playback_and_queues_the_rest(connected):
    songs = [make_song("one"), make_song("two"), make_song("three")]
    started = await connected.enqueue(songs, announce=False)
    assert started is songs[0]
    assert connected.current is songs[0]
    assert [s.title for s in connected.q.queue] == ["two", "three"]
    assert connected.voice.is_playing()
    assert connected.manager.hooks.started == [("one", False)]
    assert connected.voice.channel.statuses[-1] == "🎵 one"


async def test_enqueue_without_voice_only_queues(manager, guild):
    player = manager.get(guild.id)
    assert await player.enqueue([make_song("one")]) is None
    assert player.current is None
    assert len(player.q.queue) == 1


async def test_track_end_advances_and_records_history(connected):
    await connected.enqueue([make_song("one"), make_song("two")])
    connected.q._pos_base = 100  # pretend it played for a while
    connected.voice.finish()
    await settle()
    assert connected.current.title == "two"
    assert [s.title for s in connected.q.history] == ["one"]


async def test_queue_running_out_goes_idle(connected):
    await connected.enqueue([make_song("one")])
    connected.q._pos_base = 100
    connected.voice.finish()
    await settle()
    assert connected.current is None
    assert connected.idle_since is not None
    assert connected.voice.channel.statuses[-1] is None
    assert connected.manager.hooks.cleared >= 1


async def test_loop_track_replays_until_skipped(connected):
    await connected.enqueue([make_song("one"), make_song("two")])
    await connected.set_loop("track")
    connected.q._pos_base = 100
    connected.voice.finish()
    await settle()
    assert connected.current.title == "one"
    await connected.skip()
    assert connected.current.title == "two"


async def test_loop_queue_reappends_finished_songs(connected):
    await connected.enqueue([make_song("one"), make_song("two")])
    await connected.set_loop("queue")
    connected.q._pos_base = 100
    connected.voice.finish()
    await settle()
    assert connected.current.title == "two"
    assert [s.title for s in connected.q.queue] == ["one"]


async def test_stale_track_end_callbacks_are_ignored(connected):
    await connected.enqueue([make_song("one"), make_song("two"), make_song("three")])
    old_token = connected.play_id
    await connected.skip()
    assert connected.current.title == "two"
    await connected._on_track_end(old_token)  # a late "finished" from the skipped track
    assert connected.current.title == "two"


async def test_unresolvable_song_is_skipped_with_a_notice(connected):
    connected.manager.failing.add("broken")
    await connected.enqueue([make_song("broken"), make_song("fine")])
    assert connected.current.title == "fine"
    assert any("Couldn't play **broken**" in n for n in connected.manager.hooks.notices)


async def test_track_dying_immediately_is_not_looped(connected):
    await connected.enqueue([make_song("flaky"), make_song("next")])
    await connected.set_loop("track")
    connected.voice.finish()  # position ~0: it never really played
    await settle()
    assert connected.current.title == "next"
    assert any("failed, skipping" in n for n in connected.manager.hooks.notices)


async def test_previous_goes_back(connected):
    await connected.enqueue([make_song("one"), make_song("two")])
    await connected.skip()
    await connected.previous()
    assert connected.current.title == "one"
    assert [s.title for s in connected.q.queue] == ["two"]


async def test_seek_restarts_at_position_and_keeps_pause(connected):
    await connected.enqueue([make_song("one")])
    await connected.pause()
    await connected.seek(42)
    assert connected.voice.source.position == 42
    assert connected.voice.is_paused()
    assert connected.q.position == pytest.approx(42)
    with pytest.raises(PlayerError):
        await connected.seek(9999)


async def test_volume_and_effect_restart_with_transcoding(connected):
    await connected.enqueue([make_song("one")])
    assert connected.voice.source.passthrough is True
    await connected.set_volume(50)
    assert connected.voice.source.volume == 0.5
    assert connected.voice.source.passthrough is False
    assert connected.manager.settings.get(connected.guild_id).volume == 0.5
    await connected.set_filter("nightcore")
    assert connected.q.rate == 1.25
    with pytest.raises(PlayerError):
        await connected.set_filter("nope")


async def test_skip_to_with_loop_queue_keeps_skipped_songs(connected):
    await connected.enqueue([make_song(t) for t in ("cur", "a", "b", "c", "d")])
    connected.q.loop_mode = LoopMode.QUEUE
    await connected.skip_to(2)  # "c"
    assert connected.current.title == "c"
    assert [s.title for s in connected.q.queue] == ["d", "cur", "a", "b"]


async def test_vote_skip_needs_a_majority(connected, guild):
    alice = guild.member(11, "Alice")
    bob = guild.member(12, "Bob")
    guild.member(13, "Cara")
    await connected.enqueue([make_song("one", requester_id=99), make_song("two", requester_id=99)])
    first = await connected.skip(alice)
    assert "1/2" in first
    assert connected.current.title == "one"
    await connected.skip(bob)
    assert connected.current.title == "two"


async def test_requester_and_dj_skip_instantly(connected, guild):
    guild.roles.append(FakeRole("DJ"))
    alice = guild.member(11, "Alice")
    dj = guild.member(12, "Dee", dj=True)
    guild.member(13, "Cara")
    await connected.enqueue([make_song("mine", requester_id=11), make_song("theirs", requester_id=99),
                             make_song("last", requester_id=99)])
    await connected.skip(alice)  # her own song
    assert connected.current.title == "theirs"
    await connected.skip(dj)
    assert connected.current.title == "last"


async def test_dj_role_guards_destructive_actions(manager):
    from tests.fakes import FakeBot, FakeGuild

    guild = FakeGuild(2, dj_role=True)
    manager.bot = FakeBot(guild)
    await guild.channel.connect()
    player = manager.get(guild.id)
    pleb = guild.member(21, "Pat")
    dj = guild.member(22, "Dee", dj=True)
    await player.enqueue([make_song("one"), make_song("two"), make_song("three")])
    for action in (player.clear(pleb), player.stop(pleb), player.set_volume(10, pleb), player.shuffle(pleb)):
        with pytest.raises(PlayerError, match="DJ role"):
            await action
    assert "Shuffled" in await player.shuffle(dj)
    assert "Stopped" in await player.stop(dj)
    assert guild.voice_client is None
    assert manager.peek(guild.id) is None


async def test_snapshot_shape(connected, guild):
    guild.member(11, "Alice")
    await connected.enqueue([make_song("one"), make_song("two")])
    state = connected.snapshot()
    assert state["current"]["title"] == "one"
    assert state["queue"][0]["title"] == "two"
    assert state["queue_length"] == 1
    assert state["voice"]["channel"] == "Lounge"
    assert [listener["name"] for listener in state["voice"]["listeners"]] == ["Alice"]
    assert state["effect"] is None and state["loop"] == "off" and state["volume"] == 100


async def test_destroy_resets_state(manager, connected):
    await connected.enqueue([make_song("one"), make_song("two")])
    await manager.destroy(connected.guild_id)
    assert connected.closed
    state = manager.snapshot(connected.guild_id)
    assert state["current"] is None and state["queue"] == [] and state["voice"] is None


async def test_inactivity_leaves_an_empty_channel(manager, connected):
    await connected.enqueue([make_song("one")])
    timeout = manager.config.alone_timeout
    # Relative to now: monotonic() counts from boot, which can be seconds ago on a fresh CI runner
    connected.alone_since = time.monotonic() - timeout + 30  # alone, but not for long enough yet
    await manager.check_inactivity()
    assert manager.peek(connected.guild_id) is connected
    connected.alone_since = time.monotonic() - timeout - 1
    await manager.check_inactivity()
    assert manager.peek(connected.guild_id) is None
    assert any("everyone left" in n for n in manager.hooks.notices)
