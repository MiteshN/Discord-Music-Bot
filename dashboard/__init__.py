"""Quart app factory for the web dashboard."""

import hashlib
import logging
import os
from datetime import timedelta
from pathlib import Path

from quart import Quart, Response, render_template, session

from dashboard.api import api_bp
from dashboard.auth import auth_bp
from dashboard.events import EventBus
from dashboard.websocket import ws_bp

log = logging.getLogger("bot.dashboard")

STATIC_DIR = Path(__file__).parent / "static"


def asset_version() -> str:
    """Short hash of the CSS/JS files. Added to their URLs so no browser or CDN
    (e.g. Cloudflare's 4-hour browser cache) can serve a stale mix after a deploy."""
    digest = hashlib.sha256()
    for path in sorted(STATIC_DIR.rglob("*")):
        if path.suffix in (".css", ".js"):
            digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


def create_app(bot) -> Quart:
    app = Quart(__name__, static_folder="static", template_folder="templates")

    secret = os.getenv("DASHBOARD_SECRET_KEY")
    if not secret:
        log.warning("DASHBOARD_SECRET_KEY is not set: everyone will be logged out whenever the bot restarts")
        secret = os.urandom(32).hex()
    app.secret_key = secret
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("DASHBOARD_URL", "").startswith("https://"),
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        SEND_FILE_MAX_AGE_DEFAULT=0,  # always revalidate so updates show up immediately
    )

    event_bus = EventBus()
    app.config["BOT"] = bot
    app.config["EVENT_BUS"] = event_bus
    bot._dashboard_event_bus = event_bus

    app.register_blueprint(auth_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(ws_bp)

    version = asset_version()
    index_html = (STATIC_DIR / "index.html").read_text(encoding="utf-8").replace("__V__", version)

    @app.route("/")
    async def index():
        if "user" not in session:
            response = Response(await render_template("login.html", v=version))
        else:
            response = Response(index_html, mimetype="text/html")
        # The page itself must never be cached, or it would point at old asset versions
        response.headers["Cache-Control"] = "no-store"
        return response

    return app
