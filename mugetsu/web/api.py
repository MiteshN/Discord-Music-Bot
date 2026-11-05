"""JSON API for the dashboard. Every action goes through the same player code as Discord commands."""

from __future__ import annotations

import functools
import logging

from quart import Blueprint, current_app, jsonify, request, session

from mugetsu.player.models import PlayerError
from mugetsu.util import plain
from mugetsu.web.backend import Backend, Forbidden

log = logging.getLogger("mugetsu.web.api")

api_bp = Blueprint("api", __name__, url_prefix="/api")

CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "mugetsu"


def backend() -> Backend:
    return current_app.config["BACKEND"]


def error(message: str, status: int):
    return jsonify({"error": message}), status


@api_bp.before_request
async def csrf_guard():
    # Browsers won't send custom headers cross-site without a CORS preflight, which we never allow
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        return error("Missing request header", 400)
    return None


def signed_in(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        if "user" not in session:
            return error("Not signed in", 401)
        return await func(*args, **kwargs)

    return wrapper


def guild_route(func):
    """Sign-in + membership check, then call func(guild_id, user_id, ...)."""

    @functools.wraps(func)
    @signed_in
    async def wrapper(guild_id: int, **kwargs):
        user_id = int(session["user"]["id"])
        if not await backend().can_view(guild_id, user_id):
            return error("You don't have access to that server", 403)
        try:
            return await func(guild_id, user_id, **kwargs)
        except PlayerError as e:
            return error(plain(str(e)), 400)
        except Forbidden as e:
            return error(str(e), 403)
        except (KeyError, TypeError, ValueError) as e:
            log.debug("Bad request to %s: %r", request.path, e)
            return error("Invalid request", 400)

    return wrapper


@api_bp.get("/me")
@signed_in
async def me():
    return jsonify({"user": session["user"], "bot": backend().info()})


@api_bp.post("/logout")
async def logout():
    session.clear()
    return jsonify({"ok": True})


@api_bp.get("/guilds")
@signed_in
async def guilds():
    return jsonify(backend().guilds_for(set(session.get("guild_ids", []))))


@api_bp.get("/guilds/<int:guild_id>/state")
@guild_route
async def state(guild_id: int, user_id: int):
    return jsonify(backend().state(guild_id))


@api_bp.post("/guilds/<int:guild_id>/actions/<action>")
@guild_route
async def act(guild_id: int, user_id: int, action: str):
    body = await request.get_json(silent=True)
    message = await backend().act(guild_id, user_id, action, body if isinstance(body, dict) else {})
    return jsonify({"message": message})


@api_bp.get("/guilds/<int:guild_id>/search")
@guild_route
async def search(guild_id: int, user_id: int):
    query = request.args.get("q", "").strip()
    if len(query) < 2:
        return jsonify({"songs": [], "albums": [], "videos": []})
    return jsonify(await backend().search(guild_id, query[:200]))


@api_bp.get("/guilds/<int:guild_id>/stats")
@guild_route
async def stats(guild_id: int, user_id: int):
    return jsonify(await backend().stats(guild_id, request.args.get("period", "week")))


@api_bp.get("/playlists")
@signed_in
async def playlists():
    return jsonify(await backend().playlists(int(session["user"]["id"])))


@api_bp.post("/playlists/actions/<action>")
@signed_in
async def playlist_action(action: str):
    body = await request.get_json(silent=True)
    try:
        message = await backend().playlist_action(int(session["user"]["id"]), action, body if isinstance(body, dict) else {})
    except PlayerError as e:
        return error(plain(str(e)), 400)
    except (KeyError, TypeError, ValueError):
        return error("Invalid request", 400)
    return jsonify({"message": message})


@api_bp.get("/guilds/<int:guild_id>/lyrics")
@guild_route
async def lyrics(guild_id: int, user_id: int):
    found = await backend().lyrics(guild_id)
    if found is None:
        return error("Nothing is playing", 404)
    return jsonify(found)
