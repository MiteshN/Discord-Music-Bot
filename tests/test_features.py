"""Stats, playlists, restarts, autoplay, queue cleanup, radio and guess the song."""

from __future__ import annotations

import asyncio
import time

import pytest

from mugetsu import game as game_module
from mugetsu.cogs.playback import parse_radio_query
from mugetsu.game import GuessTheSong, artists_of, matches, spotify_query
from mugetsu.media.radio import RadioBrowser, Station
from mugetsu.player.models import PlayerError, Song
from mugetsu.store import Store
from mugetsu.util import parse_positions
from tests.conftest import make_song, settle
from tests.fakes import FakeMessage, FakeRole, FakeTextChannel


@pytest.fixture
async def store(tmp_path):
    s = Store(tmp_path)
    await s.initialize()
    yield s
    await s.close()


def record(title, requester_id=1, **kw):
    return make_song(title, requester_id=requester_id, requester=f"user{requester_id}", **kw).to_record()


# --- Store ---

async def test_play_log_feeds_stats_and_recent(store):
    for title, who in [("a", 1), ("b", 1), ("a", 2), ("a", 1), ("c", 2)]:
        play_id = await store.log_play(9, record(title, who, artist=f"artist {title}"))
        await store.finish_play(play_id, 100)
    stats = await store.stats(9)
    assert stats["plays"] == 5 and stats["seconds"] == 500 and stats["requesters"] == 2
    assert stats["top_songs"][0]["title"] == "a" and stats["top_songs"][0]["plays"] == 3
    assert stats["top_requesters"][0]["id"] == "1" and stats["top_requesters"][0]["plays"] == 3
    assert stats["top_artists"][0]["name"] == "artist a"
    assert (await store.stats(9, since=time.time() + 60))["plays"] == 0
    assert (await store.stats(8))["plays"] == 0  # other servers are separate
    recent = await store.recent_requests(9, 1, 10)
    assert [r["title"] for r in recent] == ["a", "b"]  # newest first, no repeats


async def test_playlists(store):
    assert await store.save_playlist(1, "Chill", [record("a"), record("b")]) == 2
    assert await store.add_tracks(1, "chill", [record("c")]) == 3  # names ignore case
    p = await store.playlist(1, "CHILL")
    assert [t["title"] for t in p.tracks] == ["a", "b", "c"]
    assert await store.playlist(2, "Chill") is None  # playlists are per person
    code = await store.share_code(1, "Chill")
    assert code == await store.share_code(1, "Chill") and len(code) == 8
    assert (await store.playlist_by_code(code.lower())).name == "Chill"
    assert (await store.remove_track(1, "Chill", 1))["title"] == "b"
    assert await store.rename_playlist(1, "Chill", "Mellow")
    with pytest.raises(ValueError):
        await store.rename_playlist(1, "Mellow", "Mellow")
    assert [p.name for p in await store.playlists(1)] == ["Mellow"]
    assert await store.delete_playlist(1, "Mellow") and not await store.playlists(1)


async def test_sessions_expire(store):
    await store.save_session(5, {"queue": []})
    assert [g for g, _ in await store.sessions(60)] == [5]
    await store.db.execute("UPDATE sessions SET saved_at = saved_at - 1000")
    assert await store.sessions(60) == []


async def test_game_scores_accumulate(store):
    await store.add_game_result(3, {1: ("Ann", 5), 2: ("Bo", 2)}, winner_id=1)
    await store.add_game_result(3, {2: ("Bo", 6)}, winner_id=2)
    board = await store.game_leaderboard(3)
    assert [(r["name"], r["points"], r["wins"], r["games"]) for r in board] == [("Bo", 8, 1, 2), ("Ann", 5, 1, 1)]


# --- Engine ---

async def test_queue_cleanup(connected, guild):
    guild.roles.append(FakeRole("DJ"))
    ann = guild.member(11, "Ann", dj=True)
    bo = guild.member(12, "Bo")
    await connected.enqueue([make_song("now")] + [
        make_song(t, requester_id=r) for t, r in [("x", 12), ("y", 12), ("x", 99), ("z", 77), ("w", 11)]
    ])
    titles = lambda: [s.title for s in connected.q.queue]  # noqa: E731
    assert "Removed" in await connected.remove_duplicates(ann)
    assert titles() == ["x", "y", "z", "w"]
    with pytest.raises(PlayerError, match="DJ"):
        await connected.remove_requester(11, "Ann", bo)  # someone else's songs need DJ
    await connected.remove_requester(12, "Bo", bo)  # your own are fine
    assert titles() == ["z", "w"]
    await connected.remove_absent(ann)  # user 77 isn't in the channel
    assert titles() == ["w"]
    await connected.enqueue([make_song(t) for t in "abcd"])
    await connected.remove_positions([0, 2, 3], ann)
    assert titles() == ["a", "d"]


async def test_plays_are_logged_with_listening_time(manager, connected):
    await connected.enqueue([make_song("one"), make_song("two")])
    connected.q._pos_base = 150
    connected.voice.finish()
    await settle(20)
    await asyncio.gather(*manager._background)
    stats = await manager.store.stats(connected.guild_id)
    assert stats["plays"] == 2  # "one" finished, "two" started
    assert max(s["seconds"] for s in stats["top_songs"]) >= 150


async def test_autoplay_continues_when_the_queue_runs_out(manager, connected):
    async def recommend(seed, exclude, count=3):
        assert seed.title == "seed" and "seed" not in [k for k in exclude if k == "nope"]
        return [make_song("related 1", requester="Autoplay", requester_id=0), make_song("related 2")]

    manager.recommend = recommend
    await connected.enqueue([make_song("seed")])
    connected.autoplay = True
    connected.q._pos_base = 100
    connected.voice.finish()
    await settle(20)
    assert connected.current.title == "related 1"
    assert [s.title for s in connected.q.queue] == ["related 2"]


async def test_no_autoplay_after_skipping_or_when_off(manager, connected):
    calls = []

    async def recommend(seed, exclude, count=3):
        calls.append(seed)
        return [make_song("related")]

    manager.recommend = recommend
    await connected.enqueue([make_song("seed")])
    connected.q._pos_base = 100
    connected.voice.finish()  # autoplay is off
    await settle(20)
    assert connected.current is None and not calls


async def test_turning_on_autoplay_while_idle_starts_playing(manager, connected):
    async def recommend(seed, exclude, count=3):
        return [make_song("related")]

    manager.recommend = recommend
    await connected.enqueue([make_song("seed")])
    connected.q._pos_base = 100
    connected.voice.finish()
    await settle(20)
    assert connected.current is None
    await connected.set_autoplay(True)
    assert connected.current.title == "related"
    assert manager.settings.get(connected.guild_id).autoplay


async def test_resume_session_plays_from_the_saved_position(manager, guild):
    channel = guild.channel
    guild.member(11, "Ann")
    await manager.store.save_session(guild.id, {
        "voice_channel_id": channel.id, "text_channel_id": None, "position": 42.0, "paused": False,
        "loop": "queue", "effect": "nightcore",
        "current": make_song("where we were").to_record(), "queue": [make_song("next").to_record()],
    })
    await manager.restore_sessions()
    player = manager.peek(guild.id)
    assert guild.voice_client is not None
    assert player.current.title == "where we were" and guild.voice_client.source.position == 42.0
    assert [s.title for s in player.q.queue] == ["next"]
    assert player.q.loop_mode.value == "queue" and player.q.audio_filter.key == "nightcore"
    await manager.restore_sessions()  # only ever once


async def test_no_resume_into_an_empty_channel(manager, guild):
    await manager.store.save_session(guild.id, {"voice_channel_id": guild.channel.id, "current": None,
                                                "queue": [make_song("x").to_record()]})
    await manager.restore_sessions()
    assert guild.voice_client is None
    await asyncio.gather(*manager._background)
    assert await manager.store.sessions(900) == []


async def test_sessions_are_saved_after_changes(manager, connected, monkeypatch):
    from mugetsu.player import manager as manager_module

    monkeypatch.setattr(manager_module, "SESSION_SAVE_DELAY", 0)
    await connected.enqueue([make_song("one"), make_song("two")])
    await asyncio.sleep(0.05)
    await asyncio.gather(*manager._background)
    (_, data), = await manager.store.sessions(900)
    assert data["current"]["title"] == "one" and [r["title"] for r in data["queue"]] == ["two"]
    await manager.destroy(connected.guild_id)
    await asyncio.gather(*manager._background)
    assert await manager.store.sessions(900) == []  # a deliberate stop isn't resumed


# --- Guess the song ---

@pytest.mark.parametrize(("guess", "answer", "ok"), [
    ("bohemian rapsody", "Bohemian Rhapsody - Remastered 2011", True),
    ("loser tame impala", "Tame Impala", True),
    ("Beyonce", "Beyoncé", True),
    ("less i know the better", "The Less I Know The Better", True),
    ("run", "Run", True),
    ("ru", "Run", False),
    ("hello", "Rolling in the Deep", False),
])
def test_answer_matching(guess, answer, ok):
    assert matches(guess, answer) is ok


def test_game_sources():
    assert spotify_query("80s rock") == 'genre:"rock" year:1980-1989'
    assert spotify_query("pop 2018") == 'genre:"pop" year:2018'
    assert spotify_query("2010s") == "year:2010-2019"
    assert artists_of("A, B & C feat. D") == ["A", "B", "C", "D"]


async def test_a_game_round_trip(manager, connected, guild, monkeypatch):
    monkeypatch.setattr(game_module, "ROUND_GAP", 0)
    ann = guild.member(11, "Ann")
    text = FakeTextChannel()
    pool = [Song(title=f"Artist {i} - Song {i}", query="q", duration=200, artist=f"Artist {i}",
                 track_name=f"Song {i}", requester="Guess the song") for i in range(4)]
    game = GuessTheSong(connected, text, ann, pool, rounds=2, clip_seconds=1)
    game.start()
    for _ in range(50):
        await asyncio.sleep(0.02)
        if game.current:
            break
    assert connected.snapshot()["current"]["title"] == "Guess the song"  # no peeking
    with pytest.raises(PlayerError, match="game"):
        await connected.enqueue([make_song("sneaky")])
    answer = game.current.song
    msg = FakeMessage(ann, text, f"{answer.track_name} by {answer.artist}")
    await game.on_message(msg)
    assert msg.reactions == ["✅"] and game.scores[11].points == 3
    await asyncio.wait_for(game._task, timeout=10)
    assert connected.game is None and connected.current is None
    board = await manager.store.game_leaderboard(guild.id)
    assert board[0]["name"] == "Ann" and board[0]["wins"] == 1


async def test_guesses_from_outside_voice_dont_count(connected, guild):
    ann = guild.member(11, "Ann")
    outsider = guild.member(12, "Out", in_voice=False)
    text = FakeTextChannel()
    game = GuessTheSong(connected, text, ann, [], rounds=1)
    game.current = game_module.Round(1, Song(title="A - Song", query="q", artist="A", track_name="Song", requester="x"))
    await game.on_message(FakeMessage(outsider, text, "song"))
    assert game.current.title_by is None


# --- Radio and small helpers ---

def test_radio_query_parsing():
    assert parse_radio_query("lofi --country=japan") == ("lofi", "japan")
    assert parse_radio_query('jazz country:"united states"') == ("jazz", "united states")
    assert parse_radio_query("nrj") == ("nrj", "")


async def test_radio_search_falls_back_to_genre(monkeypatch):
    radio = RadioBrowser(lambda: None)
    asked = []

    async def fake_get(path, params=None):
        asked.append(params)
        if "tag" in params:
            return [{"stationuuid": "u1", "name": "Lofi 24/7", "url_resolved": "http://s/1", "tags": "lofi,chill",
                     "country": "Japan", "bitrate": 128}]
        return []

    monkeypatch.setattr(radio, "_get", fake_get)
    stations = await radio.search("Lofi", "jp")
    assert [s.name for s in stations] == ["Lofi 24/7"] and stations[0].summary == "Japan · lofi, chill · 128 kbps"
    assert asked[0]["name"] == "Lofi" and asked[1]["tag"] == "lofi" and asked[0]["countrycode"] == "jp"


async def test_radio_songs_stream_directly(manager):
    station = Station("u1", "Jazz FM", "http://stream/jazz", "", "UK", ["jazz"], "MP3", 128, "")
    manager.radio.count_click = lambda uuid: None
    song = manager.station_song(station, __import__("mugetsu.player.manager", fromlist=["Requester"]).Requester("Ann", 1))
    assert song.is_live and song.source == "radio"
    from mugetsu.player.manager import PlayerManager

    inp = await PlayerManager.resolve_input(manager, song)
    assert inp.path == "http://stream/jazz" and not inp.is_local


@pytest.mark.parametrize(("text", "indices"), [("3", [2]), ("3-5", [2, 3, 4]), ("1, 4 9", [0, 3, 8]), ("5-3", [2, 3, 4])])
def test_parse_positions(text, indices):
    assert parse_positions(text) == indices


@pytest.mark.parametrize("bad", ["", "0", "a", "1-x"])
def test_parse_positions_rejects(bad):
    with pytest.raises(ValueError):
        parse_positions(bad)
