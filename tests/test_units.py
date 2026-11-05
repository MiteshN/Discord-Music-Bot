"""Pure helpers: formatting, queue rules, FFmpeg arguments, lyrics parsing, cache keys, settings."""

from __future__ import annotations

import time

import pytest

from mugetsu.media import youtube
from mugetsu.media.cache import CacheManager
from mugetsu.media.ffmpeg import AudioInput, StderrTail, effect_catalog, ffmpeg_args, get_filter
from mugetsu.media.lyrics import clean_title, parse_lrc, pick_best, split_artist, split_lyrics
from mugetsu.player.models import LoopMode, Song
from mugetsu.player.queue import GuildQueue
from mugetsu.player.settings import GuildSettings
from mugetsu.util import format_duration, parse_timestamp, plain


def song(title, duration=100):
    return Song(title=title, query=title, requester="t", duration=duration)


@pytest.mark.parametrize(("seconds", "text"), [(0, "0:00"), (59, "0:59"), (61, "1:01"), (3725, "1:02:05"), (-4, "0:00")])
def test_format_duration(seconds, text):
    assert format_duration(seconds) == text


@pytest.mark.parametrize(("text", "seconds"), [("90", 90), ("1:30", 90), ("1:02:03", 3723)])
def test_parse_timestamp(text, seconds):
    assert parse_timestamp(text) == seconds


@pytest.mark.parametrize("bad", ["1:60", "a:b", "1:2:3:4", "-5", ""])
def test_parse_timestamp_rejects(bad):
    with pytest.raises(ValueError):
        parse_timestamp(bad)


def test_plain_strips_our_markdown():
    assert plain(r"⏭️ Skipped **Rock \*n\* Roll**.") == "⏭️ Skipped Rock *n* Roll."


class TestQueue:
    def test_add_to_top_keeps_order(self):
        q = GuildQueue()
        q.add([song("a"), song("b")])
        q.add([song("x"), song("y")], top=True)
        assert [s.title for s in q.queue] == ["x", "y", "a", "b"]

    def test_rewind_with_loop_queue_does_not_duplicate(self):
        q = GuildQueue(loop_mode=LoopMode.QUEUE)
        q.add([song("a"), song("b")])
        q.advance()
        q.advance()  # a -> history, re-appended
        assert [s.title for s in q.queue] == ["a"]
        q.rewind()
        assert q.current.title == "a"
        assert [s.title for s in q.queue] == ["b"]

    def test_failed_song_is_not_kept(self):
        q = GuildQueue(loop_mode=LoopMode.QUEUE)
        q.add([song("a"), song("b")])
        q.advance()
        q.advance(failed=True)
        assert not q.history and [s.title for s in q.queue] == []

    def test_move_remove_and_lookup(self):
        q = GuildQueue()
        items = [song(t) for t in "abcd"]
        q.add(items)
        assert q.move(3, 0)
        assert [s.title for s in q.queue] == ["d", "a", "b", "c"]
        assert not q.move(0, 9)
        assert q.index_of(items[1].id) == 2
        assert q.index_of(-1) == -1
        assert q.remove(0).title == "d"
        assert q.remove(10) is None

    def test_drop_before(self):
        q = GuildQueue()
        q.add([song(t) for t in "abc"])
        assert [s.title for s in q.drop_before(2)] == ["a", "b"]
        assert [s.title for s in q.queue] == ["c"]
        with pytest.raises(IndexError):
            q.drop_before(5)

    def test_position_respects_pause_and_rate(self, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr(time, "monotonic", lambda: now[0])
        q = GuildQueue()
        q.mark_playing(10)
        now[0] += 5
        assert q.position == pytest.approx(15)
        q.mark_paused()
        now[0] += 100
        assert q.position == pytest.approx(15)
        q.audio_filter = get_filter("nightcore")
        q.mark_resumed()
        now[0] += 4
        assert q.position == pytest.approx(20)

    def test_song_ids_are_unique_and_copy_gets_a_new_one(self):
        a = song("a")
        assert a.copy().id != a.id


class TestFFmpeg:
    def test_untouched_opus_is_passed_through(self):
        args = ffmpeg_args(AudioInput("x.opus", True, True), volume=1.0, audio_filter=None)
        assert args.passthrough and args.options == ["-vn"] and args.before == []

    def test_volume_and_effect_transcode(self):
        args = ffmpeg_args(AudioInput("https://x", False, True, "UA"), volume=0.5,
                           audio_filter=get_filter("bassboost"), position=12.5)
        assert not args.passthrough
        assert args.options[-1].startswith("volume=0.500,bass=")
        assert ["-user_agent", "UA"] == args.before[-4:-2]
        assert args.before[-2:] == ["-ss", "12.50"]

    def test_non_opus_never_passes_through(self):
        assert not ffmpeg_args(AudioInput("x.m4a", True, False), volume=1.0, audio_filter=None).passthrough

    @pytest.mark.parametrize("key", ["", "clear", "none", "speed:1"])
    def test_clearing(self, key):
        assert get_filter(key) is None

    def test_speed(self):
        f = get_filter("speed:1.5")
        assert f.rate == 1.5 and f.chain == "atempo=1.5"
        for bad in ("speed:3", "speed:x", "warp"):
            with pytest.raises(ValueError):
                get_filter(bad)

    def test_catalog_keys_all_resolve(self):
        for item in effect_catalog():
            assert get_filter(item["key"]) is not None


class TestLyrics:
    def test_clean_title(self):
        assert clean_title("Artist - Song (Official Music Video) [4K]") == "Artist - Song"
        assert clean_title("Artist - Song ft. Someone") == "Artist - Song"

    def test_split_artist(self):
        assert split_artist("Daft Punk - One More Time (Official Video)") == ("Daft Punk", "One More Time")
        assert split_artist("just a title") == ("", "just a title")

    def test_parse_lrc(self):
        lines = parse_lrc("[ar: Someone]\n[00:12.50]first\n[00:05.00][00:30.00]chorus\n[01:02.3]\nnot a line")
        assert [(round(line.time, 2), line.text) for line in lines] == [
            (5.0, "chorus"), (12.5, "first"), (30.0, "chorus"), (62.3, ""),
        ]

    def test_pick_best_prefers_close_duration_and_synced(self):
        results = [
            {"duration": 300, "plainLyrics": "x", "syncedLyrics": "[00:01.00]x"},
            {"duration": 201, "plainLyrics": "y"},
            {"duration": 203, "plainLyrics": "z", "syncedLyrics": "[00:01.00]z"},
        ]
        assert pick_best(results, 200)["plainLyrics"] == "z"
        assert pick_best([{"duration": 500, "plainLyrics": "far"}], 200) is None
        assert pick_best([], 200) is None

    def test_split_lyrics(self):
        chunks = split_lyrics("\n".join(["line"] * 2000), limit=100)
        assert all(len(c) <= 100 for c in chunks)
        assert sum(c.count("line") for c in chunks) == 2000


@pytest.mark.parametrize(("url", "key"), [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=5", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
])
def test_cache_key_from_youtube(url, key):
    assert CacheManager.extract_cache_key(url) == key


def test_cache_key_for_other_urls_is_stable():
    a = CacheManager.extract_cache_key("https://soundcloud.com/a/b")
    assert a == CacheManager.extract_cache_key("https://soundcloud.com/a/b") and len(a) == 16


async def test_settings_round_trip(tmp_path):
    settings = GuildSettings(tmp_path)
    await settings.initialize()
    await settings.save(5, volume=0.4, twenty_four_seven=True)
    await settings.close()
    reloaded = GuildSettings(tmp_path)
    await reloaded.initialize()
    assert reloaded.get(5).volume == 0.4 and reloaded.get(5).twenty_four_seven
    assert reloaded.get(6).volume == 1.0
    await reloaded.close()


async def test_cache_cleanup_keeps_databases_and_dotfiles(tmp_path):
    (tmp_path / "orphan.webm").write_bytes(b"x")
    (tmp_path / ".keep").write_text("x")
    (tmp_path / "settings.db").write_bytes(b"")
    cache = CacheManager(tmp_path, max_size_mb=10)
    await cache.initialize()
    names = {p.name for p in tmp_path.iterdir()}
    assert "orphan.webm" not in names
    assert {".keep", "settings.db", "cache.db"} <= names
    assert await cache.lookup("missing") is None
    assert (await cache.get_stats())["misses"] == 1
    await cache.close()


# Real FFmpeg output from a failed stream (URL shortened; the real one carries the server's IP)
FFMPEG_403 = b"""[https @ 0x55d526417200] HTTP error 403 Forbidden
[in#0 @ 0x55d526416200] Error opening input: Server returned 403 Forbidden (access denied)
Error opening input file https://rr10---sn-8xgp1vo-ab5k.googlevideo.com/videoplayback?expire=1&ip=203.0.113.7&c=TVHTML5&sig=x.
Error opening input files: Server returned 403 Forbidden (access denied)
"""


class TestStderrTail:
    def test_reason_from_a_403(self):
        tail = StderrTail()
        tail.write(FFMPEG_403[:40])
        tail.write(FFMPEG_403[40:])
        assert tail.reason() == "Server returned 403 Forbidden (access denied)"

    def test_urls_and_ip_never_leak(self):
        tail = StderrTail()
        tail.write(FFMPEG_403)
        assert "googlevideo" not in tail.text() and "203.0.113.7" not in tail.text()
        assert "<url>" in tail.text()

    def test_keeps_only_the_end(self):
        tail = StderrTail(limit=64)
        tail.write(b"x" * 1000 + b"\nfinal line\n")
        assert len(tail.text()) <= 64 and tail.reason() == "final line"

    def test_empty(self):
        assert StderrTail().reason() == ""

    def test_discord_py_will_pipe_into_it(self):
        # discord.py only pipes stderr into objects without a usable fileno()
        assert not hasattr(StderrTail(), "fileno")


def test_youtube_tv_clients_are_excluded_by_default():
    assert youtube.PLAYER_CLIENTS[0] == "default"
    assert {"-tv", "-tv_samsung", "-tv_simply", "-tv_downgraded"} <= set(youtube.PLAYER_CLIENTS)
    assert youtube._OPTIONS["track"]["extractor_args"]["youtube"]["player_client"] == youtube.PLAYER_CLIENTS
    assert youtube.cli_args() == ["--extractor-args", "youtube:player_client=" + ",".join(youtube.PLAYER_CLIENTS)]
