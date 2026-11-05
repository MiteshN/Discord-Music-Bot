"""Internet radio from the free, community-run radio-browser.info directory."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass

import aiohttp

log = logging.getLogger("mugetsu.radio")

USER_AGENT = "Mugetsu/2.0 (Discord music bot; https://github.com/MiteshN/Discord-Music-Bot)"
FALLBACK_SERVERS = ("de1.api.radio-browser.info", "de2.api.radio-browser.info", "fi1.api.radio-browser.info")
SERVER_TTL = 6 * 3600


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

    @classmethod
    def from_api(cls, d: dict) -> Station:
        return cls(
            uuid=d.get("stationuuid", ""),
            name=(d.get("name") or "Unknown station").strip(),
            stream_url=d.get("url_resolved") or d.get("url") or "",
            favicon=d.get("favicon") or "",
            country=d.get("country") or d.get("countrycode") or "",
            tags=[t.strip() for t in (d.get("tags") or "").split(",") if t.strip()][:5],
            codec=d.get("codec") or "",
            bitrate=int(d.get("bitrate") or 0),
            homepage=d.get("homepage") or "",
        )

    @property
    def summary(self) -> str:
        bits = [self.country, ", ".join(self.tags[:3])]
        if self.bitrate:
            bits.append(f"{self.bitrate} kbps")
        return " · ".join(b for b in bits if b)

    def to_dict(self) -> dict:
        return {"uuid": self.uuid, "name": self.name, "favicon": self.favicon, "country": self.country,
                "tags": self.tags, "bitrate": self.bitrate, "summary": self.summary}


class RadioBrowser:
    def __init__(self, http_getter):
        self._http = http_getter  # a callable returning the shared aiohttp session
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
        """Stations by name, falling back to tag (genre) when no names match; most popular first."""
        base = {"order": "clickcount", "reverse": "true", "hidebroken": "true", "limit": str(limit)}
        country = country.strip()
        if country:
            base["countrycode" if len(country) == 2 else "country"] = country
        query = query.strip()
        tries = [{"name": query}, {"tag": query.lower()}] if query else [{}]
        for extra in tries:
            rows = await self._get("/json/stations/search", {**base, **extra})
            stations = [s for s in map(Station.from_api, rows) if s.stream_url]
            if stations:
                return stations
        return []

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
