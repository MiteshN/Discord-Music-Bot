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

    def start(self):
        self._ticker = asyncio.create_task(self._tick())

    async def _tick(self):
        while True:
            await asyncio.sleep(0.5)
            for p in self.players.values():
                song = p.q.current
                if song and not p.paused and p.q.position >= song.duration:
                    self._advance(p)

    def _advance(self, p: DemoPlayer, *, skipping: bool = False):
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
            case "add":
                query = str(args.get("query", "")).strip().lower()
                if not query:
                    raise PlayerError("Type something to play.")
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
        return {"songs": songs, "albums": albums, "videos": videos}

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
