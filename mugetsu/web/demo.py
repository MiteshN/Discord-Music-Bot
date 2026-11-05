"""A stand-in backend for working on the dashboard without Discord.

    python -m mugetsu.web.demo          # API on http://127.0.0.1:8080
    cd web && npm run dev               # UI on http://localhost:5173

It uses the real queue logic with made-up songs, so the UI behaves like the real thing.
Never use this in production: anyone who opens /login is signed in.
"""

from __future__ import annotations

import asyncio
import random
import time

from mugetsu.media.ffmpeg import effect_catalog, get_filter
from mugetsu.player.events import EventBus, StateNotifier
from mugetsu.player.models import LoopMode, PlayerError, Song
from mugetsu.player.queue import GuildQueue
from mugetsu.util import format_duration

PEOPLE = [("Aiko", 0), ("Ben", 1), ("Chen", 2), ("Dana", 3), ("Eli", 4)]
DEMO_USER = {"id": "100000000000000001", "username": "You (demo)",
             "avatar": "https://cdn.discordapp.com/embed/avatars/5.png"}

# Made-up artists and songs
CATALOG = [
    ("Lumen Drive", "Glass Harbor", 214), ("Night Arcade", "Paper Satellites", 187),
    ("Velvet Static", "Low Tide Radio", 242), ("Mira Okafor", "Cinder & Snow", 198),
    ("The Quiet Hours", "Northbound", 263), ("Kiko Ren", "Moon Over Shibuya", 176),
    ("Hollow Pines", "Afterglow", 225), ("Sora Vale", "Daybreak Protocol", 301),
    ("Neon Tetra", "Ultraviolet Bloom", 205), ("Juniper Falls", "Slow Orbit", 232),
    ("Atlas & Ivy", "Lanterns", 194), ("Echo Park Kids", "Summer Static", 219),
    ("Rin Takahara", "Tokyo Rain", 247), ("Marrow", "Hearts in Monochrome", 183),
    ("Polar Bloom", "Wildfire", 256), ("Saint Juno", "Gold Coast Drive", 208),
]
STATIONS = ["Lofi Hours", "Night Jazz FM", "Tokyo Beats", "Ambient Drift", "Synthwave City", "Morning Acoustic",
            # Real stations often stuff their names with keywords; this one keeps long titles honest in the UI
            "-- # TOP 100 HITS --- DJ MIXES -- Pop, Rock, Dance, House, Techno, Trance, Electro, Hip-Hop, Rap, "
            "RnB, Reggaeton, Latin, Jazz, Blues, Soul, Funk, Chillout, Lounge, Ambient, 80s, 90s, EDM, Workout"]
LINES = [
    "Streetlights hum a song I almost know", "We keep the windows open to the night",
    "Every road out here is paved with static", "Hold on, the city's waking up again",
    "Paper planes across a violet sky", "I traced your name in the frost on the glass",
    "We were young and loud and running out of time", "Turn it up until the walls start breathing",
    "Somewhere a radio is playing our song", "Slow down, the morning isn't going anywhere",
    "Neon in the puddles, gold along the tracks", "Say it once and let the echo carry it home",
]


def _song(i: int, who: tuple[str, int]) -> Song:
    artist, name, duration = CATALOG[i % len(CATALOG)]
    return Song(
        title=f"{artist} - {name}", query=name, url=f"https://example.com/track/{i}", duration=duration,
        thumbnail=f"https://picsum.photos/seed/mugetsu{i}/480/480", artist=artist, track_name=name,
        requester=who[0], requester_id=200 + who[1],
        requester_avatar=f"https://cdn.discordapp.com/embed/avatars/{who[1]}.png",
    )


class DemoPlayer:
    def __init__(self, guild_id: int, *, channel: str | None, listeners: int, songs: int):
        self.guild_id = guild_id
        self.q = GuildQueue()
        self.volume = 1.0
        self.twenty_four_seven = False
        self.autoplay = False
        self.paused = False
        self.channel = channel
        self.listeners = [
            {"id": str(200 + n), "name": name, "avatar": f"https://cdn.discordapp.com/embed/avatars/{n}.png"}
            for name, n in PEOPLE[:listeners]
        ]
        order = random.sample(range(len(CATALOG)), len(CATALOG))
        self.q.add([_song(i, random.choice(PEOPLE)) for i in order[:songs]])
        for i in order[songs:songs + 4]:
            self.q.history.append(_song(i, random.choice(PEOPLE)))
        if channel and self.q.queue:
            self.q.advance()
            self.q.mark_playing(random.randint(10, 60))

    def snapshot(self) -> dict:
        q = self.q
        in_voice = self.channel is not None
        return {
            "current": q.current.to_dict() if q.current else None,
            "position": round(q.position, 2) if q.current else 0,
            "rate": q.rate,
            "paused": self.paused,
            "volume": round(self.volume * 100),
            "loop": q.loop_mode.value,
            "effect": {"key": q.audio_filter.key, "label": q.audio_filter.label} if q.audio_filter else None,
            "queue": [s.to_dict() for s in q.queue],
            "queue_length": len(q.queue),
            "queue_duration": q.duration,
            "history": [s.to_dict() for s in reversed(q.history)][:20],
            "twenty_four_seven": self.twenty_four_seven,
            "autoplay": self.autoplay,
            "game": None,
            "voice": {"channel": self.channel, "listeners": self.listeners} if in_voice else None,
            "skip_votes": 0,
            "skip_needed": 0,
            "timestamp": time.time(),
        }


class DemoBackend:
    ready = True

    def __init__(self):
        self.events = EventBus()
        self.notify = StateNotifier(self.events, self.state)
        self.guilds = {
            1: ("Lofi Lounge", "https://picsum.photos/seed/guild1/128/128"),
            2: ("Game Night", None),
            3: ("Study Hall", "https://picsum.photos/seed/guild3/128/128"),
        }
        self.players = {
            1: DemoPlayer(1, channel="Chill Zone", listeners=4, songs=9),
            2: DemoPlayer(2, channel=None, listeners=0, songs=0),
            3: DemoPlayer(3, channel="Focus", listeners=2, songs=3),
        }
        self._ticker: asyncio.Task | None = None
        rng = random.Random(7)
        self._playlists: dict[str, dict] = {
            name: {"name": name, "share_code": code, "tracks": [_song(i, ("You", 5)).to_record() for i in picks]}
            for name, code, picks in (
                ("Late night drive", "NIGHT7QX", rng.sample(range(len(CATALOG)), 8)),
                ("Gym", None, rng.sample(range(len(CATALOG)), 5)),
            )
        }

    def start(self):
        self._ticker = asyncio.create_task(self._tick())

    async def _tick(self):
        while True:
            await asyncio.sleep(0.5)
            for p in self.players.values():
                song = p.q.current
                if song and not p.paused and not song.is_live and p.q.position >= song.duration:
                    self._advance(p)

    def _advance(self, p: DemoPlayer, *, skipping: bool = False):
        if p.autoplay and not p.q.queue and p.q.current is not None and not skipping:
            p.q.add([_song(random.randrange(len(CATALOG)), ("Autoplay", 0)) for _ in range(2)])
            for s in list(p.q.queue)[-2:]:
                s.requester, s.requester_id, s.requester_avatar = "Autoplay", 0, ""
        nxt = p.q.advance(skipping=skipping)
        if nxt:
            p.q.mark_playing(0)
            p.paused = False
        else:
            p.q.mark_idle()
        self.notify(p.guild_id)
        return nxt

    def info(self) -> dict:
        return {"name": "Mugetsu", "avatar": "", "effects": effect_catalog(), "spotify": True, "dj_role": "DJ"}

    def guilds_for(self, guild_ids: set[str]) -> list[dict]:
        return [
            {"id": str(gid), "name": name, "icon": icon,
             "playing": bool(self.players[gid].q.current and self.players[gid].channel)}
            for gid, (name, icon) in self.guilds.items()
        ]

    async def can_view(self, guild_id: int, user_id: int) -> bool:
        return guild_id in self.players

    def state(self, guild_id: int) -> dict:
        return self.players[guild_id].snapshot()

    async def act(self, guild_id: int, user_id: int, action: str, args: dict) -> str:
        await asyncio.sleep(0.15)  # feel like a network round trip
        p = self.players[guild_id]
        q = p.q
        message = self._act(p, q, action, args)
        self.notify(guild_id)
        return message

    def _need_song(self, q: GuildQueue):
        if not q.current:
            raise PlayerError("Nothing is playing.")

    def _index(self, q: GuildQueue, song_id) -> int:
        i = q.index_of(int(song_id))
        if i < 0:
            raise PlayerError("That song isn't in the queue anymore.")
        return i

    def _act(self, p: DemoPlayer, q: GuildQueue, action: str, args: dict) -> str:
        match action:
            case "pause":
                self._need_song(q)
                p.paused = not p.paused
                q.mark_paused() if p.paused else q.mark_resumed()
                return "Paused." if p.paused else "Resumed."
            case "skip":
                self._need_song(q)
                title = q.current.title
                self._advance(p, skipping=True)
                return f"Skipped {title}."
            case "previous":
                song = q.rewind()
                if not song:
                    raise PlayerError("There's no previous track.")
                q.mark_playing(0)
                p.paused = False
                return f"Back to {song.title}."
            case "stop":
                q.queue.clear()
                q.mark_idle()
                p.channel = None
                return "Stopped and disconnected."
            case "seek":
                self._need_song(q)
                position = int(float(args["position"]))
                q.mark_playing(position)
                if p.paused:
                    q.mark_paused()
                return f"Seeked to {format_duration(position)}."
            case "volume":
                volume = int(args["volume"])
                if not 0 <= volume <= 100:
                    raise PlayerError("Volume must be between 0 and 100.")
                p.volume = volume / 100
                return f"Volume set to {volume}%."
            case "loop":
                mode = args.get("mode")
                cycle = [LoopMode.OFF, LoopMode.TRACK, LoopMode.QUEUE]
                q.loop_mode = LoopMode(mode) if mode else cycle[(cycle.index(q.loop_mode) + 1) % 3]
                return f"Loop: {q.loop_mode.value}."
            case "effect":
                try:
                    position = q.position
                    q.audio_filter = get_filter(str(args.get("key", "")))
                    if q.current:
                        q.mark_playing(position)
                        if p.paused:
                            q.mark_paused()
                except ValueError as e:
                    raise PlayerError(str(e)) from None
                return f"Effect: {q.audio_filter.label}." if q.audio_filter else "Effects cleared."
            case "shuffle":
                if len(q.queue) < 2:
                    raise PlayerError("Not enough songs in the queue to shuffle.")
                q.shuffle()
                return f"Shuffled {len(q.queue)} tracks."
            case "clear":
                count = len(q.queue)
                q.queue.clear()
                return f"Cleared {count} tracks from the queue."
            case "remove":
                song = q.remove(self._index(q, args["id"]))
                return f"Removed {song.title}."
            case "move":
                to = int(args["to"])
                if not q.move(self._index(q, args["id"]), to):
                    raise PlayerError("Invalid positions.")
                return f"Moved to position {to + 1}."
            case "skipto":
                q.drop_before(self._index(q, args["id"]))
                song = self._advance(p, skipping=True)
                return f"Jumped to {song.title}."
            case "247":
                p.twenty_four_seven = bool(args["enabled"])
                return "24/7 mode on." if p.twenty_four_seven else "24/7 mode off."
            case "autoplay":
                p.autoplay = bool(args["enabled"])
                return "Autoplay on: I'll keep playing similar songs." if p.autoplay else "Autoplay off."
            case "removedupes":
                seen = {q.current.key} if q.current else set()
                removed = q.remove_where(lambda _i, s: s.key in seen or seen.add(s.key))
                if not removed:
                    raise PlayerError("There are no duplicates in the queue.")
                return f"Removed {len(removed)} songs."
            case "removeabsent":
                here = {int(listener["id"]) for listener in p.listeners}
                removed = q.remove_where(lambda _i, s: s.requester_id not in here and s.requester_id not in (0, 205))
                if not removed:
                    raise PlayerError("Everyone with songs in the queue is still here.")
                return f"Removed {len(removed)} songs."
            case "removeuser":
                uid = int(args["user_id"])
                removed = q.remove_where(lambda _i, s: s.requester_id == uid)
                if not removed:
                    raise PlayerError("They have nothing in the queue.")
                return f"Removed {len(removed)} songs."
            case "save":
                self._need_song(q)
                return "Sent to your DMs (demo: nothing was really sent)."
            case "playrecent":
                songs = [_song(i, ("You", 5)) for i in random.sample(range(len(CATALOG)), int(args.get("count", 5)))]
                q.add(songs)
                return f"Added {len(songs)} songs from your recent songs"
            case "savequeue" | "savecurrent":
                name = str(args.get("name", "")).strip()
                if not name:
                    raise PlayerError("Give the playlist a name.")
                songs = ([q.current] if q.current else []) if action == "savecurrent" else (
                    ([q.current] if q.current else []) + list(q.queue))
                entry = self._playlists.setdefault(name, {"name": name, "share_code": None, "tracks": []})
                records = [s.to_record() for s in songs]
                entry["tracks"] = entry["tracks"] + records if action == "savecurrent" else records
                return f"Saved {len(entry['tracks'])} songs to {name}"
            case "loadplaylist":
                entry = self._playlists.get(str(args.get("name", "")))
                if not entry:
                    raise PlayerError("That playlist doesn't exist.")
                songs = [Song.from_record(r, {"requester": "You", "requester_id": 205,
                                              "requester_avatar": DEMO_USER["avatar"]}) for r in entry["tracks"]]
                if args.get("shuffle"):
                    random.shuffle(songs)
                q.add(songs)
                if q.current is None:
                    self._advance(p)
                return f"Added {len(songs)} songs from {entry['name']}"
            case "add":
                query = str(args.get("query", "")).strip().lower()
                if not query:
                    raise PlayerError("Type something to play.")
                if query.startswith("radio:demo-"):
                    i = int(query.removeprefix("radio:demo-")) % len(STATIONS)
                    song = Song(title=STATIONS[i], query=query, url="", duration=0,
                                stream_url=f"https://example.com/stream/{i}",
                                thumbnail=f"https://picsum.photos/seed/radio{i}/480/480",
                                artist="Japan · lofi, chill · 128 kbps", track_name=STATIONS[i],
                                requester="You", requester_avatar=DEMO_USER["avatar"])
                else:
                    matches = [i for i, (a, n, _) in enumerate(CATALOG) if query in f"{a} {n}".lower()]
                    song = _song(matches[0] if matches else random.randrange(len(CATALOG)), ("You", 5))
                song.requester_id = int(DEMO_USER["id"])
                q.add([song], top=bool(args.get("top")))
                p.channel = p.channel or "General"
                if q.current is None:
                    self._advance(p)
                    return f"Now playing {song.title}"
                return f"Added {song.title}" + (" to play next" if args.get("top") else "")
        raise KeyError(action)

    async def search(self, guild_id: int, query: str) -> dict:
        await asyncio.sleep(0.3)
        if query.lower().startswith("radio"):
            return {"songs": [], "albums": [], "videos": [], "stations": [
                {"uuid": f"demo-{i}", "name": n, "favicon": f"https://picsum.photos/seed/radio{i}/120/120",
                 "country": ["Japan", "France", "Canada"][i % 3], "tags": ["lofi", "chill"], "bitrate": 128,
                 "summary": f"{['Japan', 'France', 'Canada'][i % 3]} · lofi, chill · 128 kbps"}
                for i, n in enumerate(STATIONS)]}
        words = query.lower().split()
        hits = [i for i, (a, n, _) in enumerate(CATALOG) if any(w in f"{a} {n}".lower() for w in words)]
        hits = hits or random.sample(range(len(CATALOG)), 5)
        songs = [{"title": f"{CATALOG[i][0]} - {CATALOG[i][1]}", "artist": CATALOG[i][0], "name": CATALOG[i][1],
                  "duration": CATALOG[i][2], "thumbnail": f"https://picsum.photos/seed/mugetsu{i}/300/300",
                  "url": CATALOG[i][1]} for i in hits[:5]]
        albums = [{"title": f"{CATALOG[i][1]} (Deluxe)", "artist": CATALOG[i][0], "tracks": 12, "year": "2026",
                   "thumbnail": f"https://picsum.photos/seed/album{i}/300/300", "url": CATALOG[i][1]}
                  for i in hits[:2]]
        videos = [{"title": f"{CATALOG[i][0]} - {CATALOG[i][1]} (Live Session)", "url": CATALOG[i][1],
                   "duration": CATALOG[i][2] + 31, "thumbnail": f"https://picsum.photos/seed/video{i}/480/270"}
                  for i in hits[:5]]
        return {"songs": songs, "albums": albums, "videos": videos, "stations": []}

    async def lyrics(self, guild_id: int) -> dict | None:
        song = self.players[guild_id].q.current
        if not song:
            return None
        await asyncio.sleep(0.4)
        rng = random.Random(song.title)
        synced = [{"time": t, "text": rng.choice(LINES)} for t in range(12, song.duration - 10, 5)]
        for i in range(8, len(synced), 9):
            synced[i]["text"] = ""  # instrumental gaps
        return {"song_id": song.id, "title": song.title, "plain": "\n".join(s["text"] for s in synced),
                "synced": synced, "source": "Demo"}


    async def stats(self, guild_id: int, period: str) -> dict:
        if period not in ("week", "month", "all"):
            raise PlayerError("Period must be week, month or all.")
        scale = {"week": 1, "month": 4, "all": 15}[period]
        rng = random.Random(guild_id * 31 + scale)
        songs = rng.sample(range(len(CATALOG)), 8)
        top_songs = [{"title": f"{CATALOG[i][0]} - {CATALOG[i][1]}", "artist": CATALOG[i][0], "url": "",
                      "thumbnail": f"https://picsum.photos/seed/mugetsu{i}/300/300",
                      "plays": max(1, (24 - n * 3) * scale + rng.randint(0, 3)), "seconds": CATALOG[i][2] * 9 * scale}
                     for n, i in enumerate(songs)]
        people = [{"id": str(200 + n), "name": name, "avatar": f"https://cdn.discordapp.com/embed/avatars/{n}.png",
                   "plays": (40 - n * 7) * scale, "seconds": (40 - n * 7) * scale * 210} for name, n in PEOPLE]
        artists = [{"name": CATALOG[i][0], "plays": (18 - n * 2) * scale} for n, i in enumerate(songs[:6])]
        plays = sum(p["plays"] for p in people)
        return {"plays": plays, "seconds": plays * 205, "requesters": len(people), "since": time.time() - scale * 7 * 86400,
                "top_songs": top_songs, "top_requesters": people, "top_artists": artists, "period": period}

    async def playlists(self, user_id: int) -> list[dict]:
        out = []
        for entry in self._playlists.values():
            tracks = entry["tracks"]
            out.append({"name": entry["name"], "share_code": entry["share_code"], "count": len(tracks),
                        "duration": sum(t.get("duration", 0) for t in tracks),
                        "tracks": [{k: t.get(k, "") for k in ("title", "artist", "duration", "thumbnail", "url")}
                                   for t in tracks]})
        return out

    async def playlist_action(self, user_id: int, action: str, args: dict) -> str:
        name = str(args.get("name", ""))
        entry = self._playlists.get(name)
        match action:
            case "delete":
                if self._playlists.pop(name, None) is None:
                    raise PlayerError("That playlist doesn't exist.")
                return f"Deleted {name}"
            case "rename":
                new = str(args.get("new_name", "")).strip()
                if entry is None or not new or new in self._playlists:
                    raise PlayerError("Can't rename that.")
                self._playlists[new] = {**self._playlists.pop(name), "name": new}
                return f"Renamed to {new}"
            case "share":
                if entry is None:
                    raise PlayerError("That playlist doesn't exist.")
                entry["share_code"] = entry["share_code"] or "DEMO" + str(random.randint(1000, 9999))
                return entry["share_code"]
            case "copy":
                return "Copied (demo)"
            case "removetrack":
                if entry is None:
                    raise PlayerError("That playlist doesn't exist.")
                removed = entry["tracks"].pop(int(args["index"]))
                return f"Removed {removed['title']}"
        raise KeyError(action)


def main():
    import logging

    from hypercorn.asyncio import serve
    from hypercorn.config import Config as HypercornConfig

    from mugetsu.config import Config
    from mugetsu.web.app import create_app

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    backend = DemoBackend()
    config = Config(dashboard_secret="demo-only-secret", dashboard_url="http://localhost:5173")
    app = create_app(backend, config, demo_user=DEMO_USER, demo_guilds=[str(g) for g in backend.guilds])
    @app.before_serving
    async def start_ticker():
        backend.start()

    hc = HypercornConfig()
    hc.bind = ["127.0.0.1:8080"]
    hc.accesslog = None
    logging.getLogger("mugetsu").info("Demo dashboard API on http://127.0.0.1:8080 (UI: cd web && npm run dev)")
    asyncio.run(serve(app, hc))


if __name__ == "__main__":
    main()
