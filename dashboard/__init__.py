"""Quart app factory for the web dashboard."""

import os
import logging

from quart import Quart, redirect, session, url_for, render_template

from dashboard.auth import auth_bp
from dashboard.api import api_bp
from dashboard.websocket import ws_bp
from dashboard.events import EventBus

log = logging.getLogger("bot.dashboard")


def create_app(bot) -> Quart:
    app = Quart(
        __name__,
        static_folder="static",
        template_folder="templates",
    )
    app.secret_key = os.getenv("DASHBOARD_SECRET_KEY", os.urandom(32).hex())
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    # Store bot reference and event bus
    event_bus = EventBus()
    app.config["BOT"] = bot
    app.config["EVENT_BUS"] = event_bus
    bot._dashboard_event_bus = event_bus

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(ws_bp)

    @app.route("/")
    async def index():
        if "user" not in session:
            return await render_template("login.html")
        return await app.send_static_file("index.html")

    log.info("Dashboard app created")
    return app
