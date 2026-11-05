"""Internet radio from the free, community-run radio-browser.info directory."""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from dataclasses import dataclass

import aiohttp

log = logging.getLogger("mugetsu.radio")

USER_AGENT = "Mugetsu/2.0 (Discord music bot; https://github.com/MiteshN/Discord-Music-Bot)"
FALLBACK_SERVERS = ("de1.api.radio-browser.info", "de2.api.radio-browser.info", "fi1.api.radio-browser.info")
SERVER_TTL = 6 * 3600
ANYWHERE = {"any", "all", "world", "worldwide", "everywhere", "none", "off"}


def parse_radio_query(query: str) -> tuple[str, str]:
    """Split "lofi --country=japan" (or "country:japan") into ("lofi", "japan")."""
    match = re.search(r"(?:--country=|country:)(\"[^\"]+\"|\S+)", query)
    if not match:
        return query.strip(), ""
    country = match.group(1).strip('"')
    return (query[:match.start()] + query[match.end():]).strip(), country


def _country_filter(country: str) -> dict:
    return {"countrycode": country.upper()} if len(country) == 2 else {"country": country}


def _norm(name: str) -> str:
    return " ".join(name.casefold().split())


def _dedupe(stations: list[Station]) -> list[Station]:
    """Drop repeats: the same result twice, or the directory listing one station twice under one name."""
    unique, seen = [], set()
    for s in stations:
        key = (_norm(s.name), s.countrycode)
        if s.uuid not in seen and key not in seen:
            seen.update((s.uuid, key))
            unique.append(s)
    return unique


@dataclass
class Station:
    uuid: str
    name: str
    stream_url: str
    favicon: str
    country: str
    tags: list[str]
    codec: str
    bitrate: int
    homepage: str
    countrycode: str = ""

    @classmethod
    def from_api(cls, d: dict) -> Station:
        return cls(
            uuid=d.get("stationuuid", ""),
            name=(d.get("name") or "Unknown station").strip(),
            stream_url=d.get("url_resolved") or d.get("url") or "",
            favicon=d.get("favicon") or "",
            country=d.get("country") or d.get("countrycode") or "",
            tags=[t.strip() for t in (d.get("tags") or "").split(",") if t.strip()],
            codec=d.get("codec") or "",
            bitrate=int(d.get("bitrate") or 0),
            homepage=d.get("homepage") or "",
            countrycode=(d.get("countrycode") or "").upper(),
        )

    @property
    def summary(self) -> str:
        bits = [self.country, ", ".join(self.tags[:3])]
        if self.bitrate:
            bits.append(f"{self.bitrate} kbps")
        return " · ".join(b for b in bits if b)

    def to_dict(self) -> dict:
        return {"uuid": self.uuid, "name": self.name, "favicon": self.favicon, "country": self.country,
                "tags": self.tags[:5], "bitrate": self.bitrate, "summary": self.summary}


class RadioBrowser:
    def __init__(self, http_getter, prefer_country: str = ""):
        self._http = http_getter  # a callable returning the shared aiohttp session
        # Stations from here are listed first (a two-letter code like "US", or a country name)
        prefer_country = prefer_country.strip()
        self.prefer_country = "" if prefer_country.lower() in ANYWHERE else prefer_country
        self._servers: list[str] = []
        self._servers_at = 0.0

    async def _base(self) -> str:
        # radio-browser asks clients to spread load across its mirrors
        if not self._servers or time.monotonic() - self._servers_at > SERVER_TTL:
            try:
                async with self._http().get(
                    "https://all.api.radio-browser.info/json/servers", headers={"User-Agent": USER_AGENT},
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    data = await resp.json(content_type=None)
                self._servers = sorted({d["name"] for d in data if d.get("name")}) or list(FALLBACK_SERVERS)
            except (aiohttp.ClientError, TimeoutError, ValueError, KeyError, TypeError) as e:
                log.debug("Couldn't list radio-browser servers: %s", e)
                self._servers = list(FALLBACK_SERVERS)
            self._servers_at = time.monotonic()
        return f"https://{random.choice(self._servers)}"

    async def _get(self, path: str, params: dict | None = None) -> list[dict]:
        last_error: Exception | None = None
        for _ in range(2):  # one retry on another mirror
            try:
                async with self._http().get(
                    f"{await self._base()}{path}", params=params, headers={"User-Agent": USER_AGENT},
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)
                    return data if isinstance(data, list) else []
            except (aiohttp.ClientError, TimeoutError, ValueError) as e:
                last_error = e
                self._servers_at = 0  # pick a fresh mirror list next time
        raise RuntimeError(f"Radio directory unavailable: {last_error}")

    async def search(self, query: str = "", country: str = "", limit: int = 10) -> list[Station]:
        """Stations by name, falling back to tag (genre) when no names match; most popular first.

        `country` limits the search to one country ("any" searches everywhere). Without it, stations
        from `prefer_country` come first and the rest of the world fills in after them.
        """
        base = {"order": "clickcount", "reverse": "true", "hidebroken": "true", "limit": str(limit)}
        query, country = query.strip(), country.strip()
        # radio-browser matches names anywhere, so "nts" also finds "Huntsville": a match at the start
        # of a word is the one people mean
        at_word = re.compile(rf"(?<!\w){re.escape(query)}", re.IGNORECASE) if query else None

        def relevant(s: Station, kind: str = "name") -> bool:
            if at_word is None:
                return True
            return any(at_word.search(t) for t in s.tags) if kind == "tag" else bool(at_word.search(s.name))

        def ranked(found: tuple[list[Station], str]) -> list[Station]:
            stations, kind = found
            # Name matches at a word start first; popularity order holds within each group
            return sorted(stations, key=lambda s: not relevant(s)) if kind == "name" else stations

        if country.lower() in ANYWHERE or (not country and not self.prefer_country):
            return _dedupe(ranked(await self._find(base, query)))[:limit]
        if country:
            return _dedupe(ranked(await self._find({**base, **_country_filter(country)}, query)))[:limit]

        local, world = await asyncio.gather(
            # Home stations only count when they really match, so they never bury a good worldwide hit
            self._find({**base, **_country_filter(self.prefer_country)}, query, keep=relevant),
            self._find(base, query),
            return_exceptions=True,
        )
        if isinstance(local, BaseException) and isinstance(world, BaseException):
            raise world
        home = [] if isinstance(local, BaseException) else local[0]
        rest = [] if isinstance(world, BaseException) else ranked(world)
        # A station named exactly what was asked for wins wherever it is ("BBC Radio 1")
        wanted = _norm(query)
        exact = [s for s in home + rest if wanted and _norm(s.name) == wanted]
        return _dedupe(exact + home + rest)[:limit]

    async def _find(self, params: dict, query: str, keep=None) -> tuple[list[Station], str]:
        """Stations by name, else by tag, and which of the two matched. `keep(station, kind)` drops weak matches."""
        tries = [("name", {"name": query}), ("tag", {"tag": query.lower()})] if query else [("all", {})]
        for kind, extra in tries:
            rows = await self._get("/json/stations/search", {**params, **extra})
            stations = [s for s in map(Station.from_api, rows) if s.stream_url]
            if keep is not None:
                stations = [s for s in stations if keep(s, kind)]
            if stations:
                return stations, kind
        return [], ""

    async def by_uuid(self, uuid: str) -> Station | None:
        rows = await self._get(f"/json/stations/byuuid/{uuid}")
        return Station.from_api(rows[0]) if rows else None

    def count_click(self, uuid: str):
        """radio-browser ranks stations by plays; telling it is polite and costs nothing."""
        async def click():
            try:
                await self._get(f"/json/url/{uuid}")
            except Exception:
                pass

        asyncio.get_running_loop().create_task(click())
