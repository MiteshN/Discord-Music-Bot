"""The dashboard's HTTP API, WebSocket and static serving."""

from __future__ import annotations

import pytest

from mugetsu.config import Config
from mugetsu.player.models import PlayerError
from mugetsu.web.app import create_app
from mugetsu.web.backend import BotBackend, Forbidden
from mugetsu.web.demo import DEMO_USER, DemoBackend
from tests.conftest import make_song
from tests.fakes import FakeBot, FakeRole

HEADERS = {"X-Requested-With": "mugetsu"}


@pytest.fixture
def dist(tmp_path):
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><div id=root></div>")
    (root / "assets" / "app-abc123.js").write_text("console.log(1)")
    (root / "favicon.svg").write_text("<svg/>")
    return root


@pytest.fixture
def demo_app(dist):
    backend = DemoBackend()
    config = Config(dashboard_secret="test", dashboard_dist=dist)
    return create_app(backend, config, demo_user=DEMO_USER, demo_guilds=["1", "2", "3"])


@pytest.fixture
async def client(demo_app):
    return demo_app.test_client()


async def sign_in(client):
    resp = await client.get("/login")
    assert resp.status_code == 302


async def test_requires_sign_in(client):
    assert (await client.get("/api/me")).status_code == 401
    assert (await client.get("/api/guilds/1/state")).status_code == 401


async def test_sign_in_and_list(client):
    await sign_in(client)
    me = await (await client.get("/api/me")).get_json()
    assert me["user"]["username"] == DEMO_USER["username"]
    assert any(e["key"] == "nightcore" for e in me["bot"]["effects"])
    guilds = await (await client.get("/api/guilds")).get_json()
    assert [g["name"] for g in guilds][:1] == ["Lofi Lounge"]


async def test_mutations_need_the_csrf_header(client):
    await sign_in(client)
    assert (await client.post("/api/guilds/1/actions/skip")).status_code == 400
    resp = await client.post("/api/guilds/1/actions/skip", headers=HEADERS)
    assert resp.status_code == 200
    assert (await resp.get_json())["message"].startswith("Skipped")


async def test_bad_requests(client):
    await sign_in(client)
    assert (await client.get("/api/guilds/99/state")).status_code == 403
    assert (await client.post("/api/guilds/1/actions/explode", headers=HEADERS)).status_code == 400
    resp = await client.post("/api/guilds/1/actions/volume", headers=HEADERS, json={"volume": 500})
    assert resp.status_code == 400 and "between 0 and 100" in (await resp.get_json())["error"]
    resp = await client.post("/api/guilds/1/actions/remove", headers=HEADERS, json={"id": 123456789})
    assert "isn't in the queue" in (await resp.get_json())["error"]


async def test_state_search_and_lyrics(client):
    await sign_in(client)
    state = await (await client.get("/api/guilds/1/state")).get_json()
    assert state["current"] and state["queue"]
    found = await (await client.get("/api/guilds/1/search?q=tokyo")).get_json()
    assert found["songs"][0]["name"] == "Tokyo Rain"
    lyrics = await (await client.get("/api/guilds/1/lyrics")).get_json()
    assert lyrics["song_id"] == state["current"]["id"] and lyrics["synced"]


async def test_websocket_sends_state(demo_app):
    client = demo_app.test_client()
    await sign_in(client)
    async with client.websocket("/ws/guilds/1") as ws:
        msg = await ws.receive_json()
    assert msg["type"] == "state" and "queue" in msg["data"]


async def test_spa_serving(client):
    index = await client.get("/")
    assert index.status_code == 200 and index.headers["Cache-Control"] == "no-store"
    assert "Content-Security-Policy" in index.headers
    asset = await client.get("/assets/app-abc123.js")
    assert "immutable" in asset.headers["Cache-Control"]
    assert (await client.get("/favicon.svg")).headers["Cache-Control"] == "no-cache"
    deep = await client.get("/some/client/route")
    assert deep.status_code == 200 and b"root" in await deep.get_data()
    assert (await client.get("/api/nope")).status_code == 404
    assert (await client.get("/../secrets")).status_code in (200, 404)  # never escapes dist
    assert (await client.get("/healthz")).status_code == 200


async def test_missing_build_explains_itself(tmp_path):
    app = create_app(DemoBackend(), Config(dashboard_secret="t", dashboard_dist=tmp_path / "nope"))
    resp = await app.test_client().get("/")
    assert resp.status_code == 503 and b"npm run build" in await resp.get_data()


class TestBotBackend:
    """Dashboard users get exactly the permissions they'd have in Discord."""

    @pytest.fixture
    async def setup(self, manager, guild):
        guild.roles.append(FakeRole("DJ"))
        bot = FakeBot(guild)
        bot.players = manager
        manager.bot = bot
        await guild.channel.connect()
        player = manager.get(guild.id)
        await player.enqueue([make_song("one"), make_song("two"), make_song("three")])
        return BotBackend(bot), guild, player

    async def test_non_members_are_refused(self, setup):
        backend, guild, _ = setup
        assert not await backend.can_view(guild.id, 404)
        with pytest.raises(Forbidden):
            await backend.act(guild.id, 404, "skip", {})

    async def test_members_outside_voice_are_fetched(self, setup):
        backend, guild, _ = setup
        guild.member(30, "Remote", in_voice=False)
        assert await backend.can_view(guild.id, 30)

    async def test_dj_rules_apply(self, setup):
        backend, guild, player = setup
        guild.member(31, "Pat")
        guild.member(32, "Dee", dj=True)
        with pytest.raises(PlayerError, match="DJ role"):
            await backend.act(guild.id, 31, "clear", {})
        assert "Paused" in await backend.act(guild.id, 31, "pause", {})
        second = player.q.queue[1]
        assert "Jumped to" in await backend.act(guild.id, 32, "skipto", {"id": second.id})
        assert player.current is second

    async def test_channel_mentions_become_names(self, setup):
        backend, guild, _ = setup
        guild.member(33, "Out", in_voice=False)
        assert backend._clean(guild, "Join <#10> first") == "Join #Lounge first"

    async def test_state_and_guild_list(self, setup):
        backend, guild, _ = setup
        assert backend.state(guild.id)["current"]["title"] == "one"
        listed = backend.guilds_for({str(guild.id), "777"})
        assert listed == [{"id": "1", "name": "Guild 1", "icon": None, "playing": True}]


async def test_stats_and_playlist_endpoints(client):
    await sign_in(client)
    stats = await (await client.get("/api/guilds/1/stats?period=month")).get_json()
    assert stats["period"] == "month" and stats["top_songs"] and stats["plays"] > 0
    assert (await client.get("/api/guilds/1/stats?period=decade")).status_code == 400
    lists = await (await client.get("/api/playlists")).get_json()
    assert {p["name"] for p in lists} >= {"Late night drive", "Gym"}
    resp = await client.post("/api/playlists/actions/share", headers=HEADERS, json={"name": "Gym"})
    assert len((await resp.get_json())["message"]) == 8
    assert (await client.post("/api/playlists/actions/share", json={"name": "Gym"})).status_code == 400  # CSRF
    assert (await client.post("/api/playlists/actions/explode", headers=HEADERS)).status_code == 400
    resp = await client.post("/api/guilds/1/actions/loadplaylist", headers=HEADERS, json={"name": "Gym"})
    assert "Added 5 songs" in (await resp.get_json())["message"]


class TestBotBackendFeatures:
    @pytest.fixture
    async def setup(self, manager, guild):
        guild.roles.append(FakeRole("DJ"))
        bot = FakeBot(guild)
        bot.players = manager
        manager.bot = bot
        await guild.channel.connect()
        player = manager.get(guild.id)
        return BotBackend(bot), guild, player

    async def test_playlists_round_trip(self, setup):
        backend, guild, player = setup
        dee = guild.member(32, "Dee", dj=True)
        await player.enqueue([make_song("one"), make_song("two")])
        assert "Saved 2 songs" in await backend.act(guild.id, 32, "savequeue", {"name": "Mine"})
        lists = await backend.playlists(32)
        assert lists[0]["name"] == "Mine" and lists[0]["count"] == 2
        code = await backend.playlist_action(32, "share", {"name": "Mine"})
        assert "Copied 2 songs" in await backend.playlist_action(40, "copy", {"code": code, "name": "Theirs"})
        await player.clear(dee)
        assert "Added 2 songs" in await backend.act(guild.id, 32, "loadplaylist", {"name": "Mine"})
        assert [s.requester for s in player.q.queue] == ["Dee", "Dee"]  # loaded songs are yours

    async def test_toggles_and_cleanup(self, setup):
        backend, guild, player = setup
        guild.member(31, "Pat")
        await player.enqueue([make_song("now"), make_song("x", requester_id=31), make_song("y", requester_id=77)])
        assert "Autoplay" in await backend.act(guild.id, 31, "autoplay", {"enabled": True})
        assert backend.state(guild.id)["autoplay"] is True
        with pytest.raises(PlayerError, match="DJ"):
            await backend.act(guild.id, 31, "removeabsent", {})
        assert "Removed" in await backend.act(guild.id, 31, "removeuser", {"user_id": "31"})
        assert [s.title for s in player.q.queue] == ["y"]

    async def test_save_sends_a_dm(self, setup):
        backend, guild, player = setup
        pat = guild.member(31, "Pat")
        await player.enqueue([make_song("lovely")])
        assert "DMs" in await backend.act(guild.id, 31, "save", {})
        assert pat.dms

    async def test_lyrics_are_hidden_during_a_game(self, setup):
        backend, guild, player = setup
        guild.member(31, "Pat")
        await player.enqueue([make_song("secret")])
        player.game = object()
        try:
            assert await backend.lyrics(guild.id) is None
            with pytest.raises(PlayerError, match="peeking"):
                await backend.act(guild.id, 31, "save", {})
        finally:
            player.game = None
