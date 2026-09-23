"""Quart app factory for the web dashboard."""

import logging
import os
from datetime import timedelta

from quart import Quart, render_template, session

from dashboard.api import api_bp
from dashboard.auth import auth_bp
from dashboard.events import EventBus
from dashboard.websocket import ws_bp

log = logging.getLogger("bot.dashboard")


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

    @app.route("/")
    async def index():
        if "user" not in session:
            return await render_template("login.html")
        return await app.send_static_file("index.html")

    return app
