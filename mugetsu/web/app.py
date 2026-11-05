"""Quart app: JSON API, WebSocket, Discord sign-in, and the built React dashboard."""

from __future__ import annotations

import logging
import os
from datetime import timedelta
from pathlib import Path

from quart import Quart, Response, jsonify, request, send_from_directory

from mugetsu.config import Config
from mugetsu.web.api import api_bp
from mugetsu.web.auth import auth_bp
from mugetsu.web.backend import Backend
from mugetsu.web.ws import ws_bp

log = logging.getLogger("mugetsu.web")

CSP = "; ".join([
    "default-src 'self'",
    "img-src * data: blob:",
    "style-src 'self' 'unsafe-inline'",
    "font-src 'self' data:",
    "connect-src 'self' ws: wss:",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
])

NOT_BUILT = """<!doctype html><meta charset="utf-8"><title>Mugetsu</title>
<body style="font:16px system-ui;background:#0b0a10;color:#eee;display:grid;place-items:center;height:100vh;margin:0">
<div style="max-width:32rem;line-height:1.5"><h1>Dashboard not built</h1>
<p>Build it with <code>npm ci &amp;&amp; npm run build</code> in <code>web/</code>,
or run <code>npm run dev</code> there and open the Vite dev server.</p></div>"""


def create_app(backend: Backend, config: Config, *, demo_user: dict | None = None,
               demo_guilds: list[str] | None = None) -> Quart:
    app = Quart(__name__, static_folder=None)

    secret = config.dashboard_secret
    if not secret:
        log.warning("DASHBOARD_SECRET_KEY is not set: everyone will be signed out whenever the bot restarts")
        secret = os.urandom(32).hex()
    app.secret_key = secret
    app.config.update(
        MUGETSU=config,
        BACKEND=backend,
        DEMO_USER=demo_user,
        DEMO_GUILDS=demo_guilds or [],
        SESSION_COOKIE_NAME="mugetsu_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=config.dashboard_url.startswith("https://"),
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    )

    app.register_blueprint(auth_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(ws_bp)

    dist = Path(config.dashboard_dist)

    @app.after_request
    async def headers(response: Response) -> Response:
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if response.mimetype == "text/html":
            response.headers.setdefault("Content-Security-Policy", CSP)
        if request.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.get("/healthz")
    async def healthz():
        ready = backend.ready
        return jsonify({"ok": True, "discord": "connected" if ready else "connecting"}), 200

    @app.get("/")
    @app.get("/<path:path>")
    async def spa(path: str = ""):
        if path.startswith(("api/", "ws/")):
            return jsonify({"error": "Not found"}), 404
        if path and (dist / path).is_file():
            response = await send_from_directory(dist, path)
            # Vite puts a content hash in every asset filename, so they never change
            if path.startswith("assets/"):
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            else:
                response.headers["Cache-Control"] = "no-cache"
            return response
        index = dist / "index.html"
        if not index.is_file():
            return Response(NOT_BUILT, status=503, mimetype="text/html")
        response = await send_from_directory(dist, "index.html")
        # The page itself must never be cached, or it could point at assets from an old deploy
        response.headers["Cache-Control"] = "no-store"
        return response

    return app
