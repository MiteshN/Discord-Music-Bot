"""All configuration comes from environment variables (or a .env file), read once at startup."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        raise SystemExit(f"{name} must be a whole number, got {value!r}") from None


def _str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class Config:
    token: str = ""
    command_prefix: str = "!"
    dj_role: str = "DJ"
    log_level: str = "INFO"

    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    genius_token: str = ""

    cache_dir: Path = Path("cache")
    cache_limit_mb: int = 2048
    max_cache_duration: int = 1800

    idle_timeout: int = 600  # leave after 10 min with nothing playing
    alone_timeout: int = 180  # leave after 3 min with nobody listening
    resume_window: int = 900  # after a restart, pick up sessions saved this recently (0 = never)
    radio_country: str = "US"  # radio search lists this country's stations first ("" or "any" = no preference)

    client_id: str = ""
    client_secret: str = ""
    dashboard_secret: str = ""
    dashboard_url: str = "http://localhost:8080"
    dashboard_host: str = "0.0.0.0"
    dashboard_port: int = 8080
    dashboard_dist: Path = ROOT / "web" / "dist"

    @property
    def dashboard_enabled(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def spotify_enabled(self) -> bool:
        return bool(self.spotify_client_id and self.spotify_client_secret)

    @property
    def public_dashboard_url(self) -> str:
        """The dashboard link shown in Discord, or "" when the dashboard is off."""
        return self.dashboard_url.rstrip("/") if self.dashboard_enabled else ""

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            token=_str("DISCORD_BOT_TOKEN"),
            command_prefix=_str("COMMAND_PREFIX", "!") or "!",
            dj_role=_str("DJ_ROLE_NAME", "DJ") or "DJ",
            log_level=_str("LOG_LEVEL", "INFO").upper() or "INFO",
            spotify_client_id=_str("SPOTIFY_CLIENT_ID"),
            spotify_client_secret=_str("SPOTIFY_CLIENT_SECRET"),
            genius_token=_str("GENIUS_API_TOKEN"),
            cache_dir=Path(_str("CACHE_DIR", "cache") or "cache"),
            cache_limit_mb=_int("CACHE_LIMIT_MB", 2048),
            max_cache_duration=_int("MAX_CACHE_DURATION", 1800),
            idle_timeout=_int("IDLE_TIMEOUT", 600),
            alone_timeout=_int("ALONE_TIMEOUT", 180),
            resume_window=_int("RESUME_WINDOW", 900),
            radio_country=_str("RADIO_COUNTRY", "US"),
            client_id=_str("DISCORD_CLIENT_ID"),
            client_secret=_str("DISCORD_CLIENT_SECRET"),
            dashboard_secret=_str("DASHBOARD_SECRET_KEY"),
            dashboard_url=(_str("DASHBOARD_URL") or "http://localhost:8080").rstrip("/"),
            dashboard_host=_str("DASHBOARD_HOST", "0.0.0.0") or "0.0.0.0",
            dashboard_port=_int("DASHBOARD_PORT", 8080),
            dashboard_dist=Path(_str("DASHBOARD_DIST") or ROOT / "web" / "dist"),
        )
