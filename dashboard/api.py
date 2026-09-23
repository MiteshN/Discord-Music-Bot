"""REST API blueprint for the dashboard. Every action goes through the Music cog."""

import functools
import logging

from quart import Blueprint, current_app, jsonify, request, session

from cogs.music import PlayerError
from dashboard.auth import require_auth_api

log = logging.getLogger("bot.dashboard.api")

api_bp = Blueprint("api", __name__, url_prefix="/api")


def _bot():
    return current_app.config["BOT"]


def user_can_access(guild_id: int) -> bool:
    return str(guild_id) in session.get("guild_ids", []) and _bot().get_guild(guild_id) is not None


def guild_action(func):
    """Auth + guild access check, then call func(guild, cog, body). PlayerError becomes a 400."""

    @functools.wraps(func)
    @require_auth_api
    async def wrapper(guild_id: int, **kwargs):
        if not user_can_access(guild_id):
            return jsonify({"error": "You don't have access to that server"}), 403
        cog = _bot().cogs.get("Music")
        if cog is None:
            return jsonify({"error": "Music is unavailable right now"}), 503
        body = await request.get_json(silent=True) if request.method == "POST" else None
        try:
            result = await func(_bot().get_guild(guild_id), cog, body if isinstance(body, dict) else {}, **kwargs)
        except PlayerError as e:
            return jsonify({"error": str(e)}), 400
        except (KeyError, TypeError, ValueError) as e:
            log.debug("Bad request to %s: %r", request.path, e)
            return jsonify({"error": "Invalid request"}), 400
        if isinstance(result, str):
            result = {"status": "ok", "message": result}
        return jsonify(result)

    return wrapper


# --- User / guilds ---

@api_bp.route("/@me")
@require_auth_api
async def me():
    return jsonify(session["user"])


@api_bp.route("/guilds")
@require_auth_api
async def guilds():
    user_guild_ids = set(session.get("guild_ids", []))
    cog = _bot().cogs.get("Music")
    result = []
    for guild in _bot().guilds:
        if str(guild.id) not in user_guild_ids:
            continue
        gq = cog.queues.peek(guild.id) if cog else None
        result.append({
            "id": str(guild.id),
            "name": guild.name,
            "icon": guild.icon.url if guild.icon else None,
            "playing": bool(gq and gq.current),
        })
    return jsonify(result)


# --- State ---

@api_bp.route("/guild/<int:guild_id>/player")
@guild_action
async def player_state(guild, cog, body):
    return cog.player_state(guild.id)


# --- Player controls ---

@api_bp.route("/guild/<int:guild_id>/player/pause", methods=["POST"])
@guild_action
async def pause_resume(guild, cog, body):
    return await cog.toggle_pause(guild)


@api_bp.route("/guild/<int:guild_id>/player/skip", methods=["POST"])
@guild_action
async def skip(guild, cog, body):
    return await cog.skip(guild)


@api_bp.route("/guild/<int:guild_id>/player/previous", methods=["POST"])
@guild_action
async def previous(guild, cog, body):
    return await cog.previous(guild)


@api_bp.route("/guild/<int:guild_id>/player/stop", methods=["POST"])
@guild_action
async def stop(guild, cog, body):
    return await cog.stop_player(guild)


@api_bp.route("/guild/<int:guild_id>/player/seek", methods=["POST"])
@guild_action
async def seek(guild, cog, body):
    return await cog.seek(guild, int(body.get("position", 0)))


@api_bp.route("/guild/<int:guild_id>/player/volume", methods=["POST"])
@guild_action
async def volume(guild, cog, body):
    return await cog.set_volume(guild, int(body.get("volume", 100)))


@api_bp.route("/guild/<int:guild_id>/player/loop", methods=["POST"])
@guild_action
async def loop(guild, cog, body):
    return await cog.set_loop(guild, body.get("mode"))


@api_bp.route("/guild/<int:guild_id>/player/filter", methods=["POST"])
@guild_action
async def apply_filter(guild, cog, body):
    return await cog.set_filter(guild, str(body.get("filter", "")))


# --- Queue ---

@api_bp.route("/guild/<int:guild_id>/queue/add", methods=["POST"])
@guild_action
async def queue_add(guild, cog, body):
    query = str(body.get("query", "")).strip()
    if not query:
        raise PlayerError("Type something to play.")
    # Members in voice are cached, so this finds the user if they're in a voice channel
    member = guild.get_member(int(session["user"]["id"]))
    if member and member.voice:
        await cog.join(member)
    elif not guild.voice_client:
        raise PlayerError("Join a voice channel in this server first, then try again.")
    songs, _ = await cog.resolve_query(query, session["user"]["username"], int(session["user"]["id"]))
    started = await cog.enqueue(guild, songs, top=bool(body.get("top")))
    if started and len(songs) == 1:
        return f"Now playing {songs[0].title}"
    return f"Added {len(songs)} tracks" if len(songs) > 1 else f"Added {songs[0].title}"


@api_bp.route("/guild/<int:guild_id>/queue/move", methods=["POST"])
@guild_action
async def queue_move(guild, cog, body):
    return await cog.move(guild, int(body["from"]), int(body["to"]))


@api_bp.route("/guild/<int:guild_id>/queue/shuffle", methods=["POST"])
@guild_action
async def queue_shuffle(guild, cog, body):
    return await cog.shuffle(guild)


@api_bp.route("/guild/<int:guild_id>/queue/clear", methods=["POST"])
@guild_action
async def queue_clear(guild, cog, body):
    return await cog.clear_queue(guild)


@api_bp.route("/guild/<int:guild_id>/queue/<int:index>", methods=["DELETE"])
@guild_action
async def queue_remove(guild, cog, body, index: int):
    return await cog.remove(guild, index)


# --- Search ---

@api_bp.route("/guild/<int:guild_id>/search")
@guild_action
async def search(guild, cog, body):
    from utils import youtube

    query = request.args.get("q", "").strip()
    if len(query) < 2:
        return []
    return await youtube.search(query, count=8)


# --- Settings ---

@api_bp.route("/guild/<int:guild_id>/settings", methods=["POST"])
@guild_action
async def update_settings(guild, cog, body):
    if "twenty_four_seven" in body:
        return await cog.set_247(guild, bool(body["twenty_four_seven"]))
    return {"status": "ok"}
