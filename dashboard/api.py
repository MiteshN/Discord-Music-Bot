"""REST API blueprint for the dashboard."""

import logging

from quart import Blueprint, jsonify, request, session, current_app

from dashboard.auth import require_auth_api

log = logging.getLogger("bot.dashboard.api")

api_bp = Blueprint("api", __name__, url_prefix="/api")


def _get_bot():
    return current_app.config["BOT"]


def _get_music_cog():
    return _get_bot().cogs.get("Music")


def _check_guild_access(guild_id: int) -> str | None:
    """Return error message if user cannot access this guild, else None."""
    user_guild_ids = {int(gid) for gid in session.get("guild_ids", [])}
    bot_guild_ids = {g.id for g in _get_bot().guilds}
    if guild_id not in user_guild_ids:
        return "You are not in this guild"
    if guild_id not in bot_guild_ids:
        return "Bot is not in this guild"
    return None


def require_guild_access(func):
    """Decorator: checks guild access for routes with guild_id param."""
    import functools

    @functools.wraps(func)
    async def wrapper(guild_id: int, *args, **kwargs):
        err = _check_guild_access(guild_id)
        if err:
            return jsonify({"error": err}), 403
        return await func(guild_id, *args, **kwargs)

    return wrapper


# --- User / Guild listing ---

@api_bp.route("/@me")
@require_auth_api
async def me():
    return jsonify(session["user"])


@api_bp.route("/guilds")
@require_auth_api
async def guilds():
    bot = _get_bot()
    user_guild_ids = {int(gid) for gid in session.get("guild_ids", [])}

    shared = []
    for guild in bot.guilds:
        if guild.id in user_guild_ids:
            icon_url = guild.icon.url if guild.icon else None
            shared.append({
                "id": str(guild.id),
                "name": guild.name,
                "icon": icon_url,
            })
    return jsonify(shared)


# --- Player state ---

@api_bp.route("/guild/<int:guild_id>/player")
@require_auth_api
@require_guild_access
async def player_state(guild_id: int):
    from dashboard.websocket import _get_player_state
    state = _get_player_state(_get_bot(), guild_id)
    return jsonify(state)


@api_bp.route("/guild/<int:guild_id>/queue")
@require_auth_api
@require_guild_access
async def queue_state(guild_id: int):
    cog = _get_music_cog()
    if not cog:
        return jsonify([])
    gq = cog.queue_manager.get(guild_id)
    queue = [
        {
            "title": s.title,
            "url": s.url,
            "duration": s.duration,
            "thumbnail": s.thumbnail,
            "requester": s.requester,
        }
        for s in gq.queue
    ]
    return jsonify(queue)


@api_bp.route("/guild/<int:guild_id>/settings")
@require_auth_api
@require_guild_access
async def get_settings(guild_id: int):
    cog = _get_music_cog()
    if not cog:
        return jsonify({"error": "Music cog not loaded"}), 500
    gq = cog.queue_manager.get(guild_id)
    return jsonify({
        "volume": int(gq.volume * 100),
        "twenty_four_seven": gq.twenty_four_seven,
    })


# --- Player controls ---

@api_bp.route("/guild/<int:guild_id>/player/pause", methods=["POST"])
@require_auth_api
@require_guild_access
async def pause_resume(guild_id: int):
    cog = _get_music_cog()
    if not cog:
        return jsonify({"error": "Music cog not loaded"}), 500
    result = await cog.api_pause_resume(guild_id)
    return jsonify(result)


@api_bp.route("/guild/<int:guild_id>/player/skip", methods=["POST"])
@require_auth_api
@require_guild_access
async def skip(guild_id: int):
    cog = _get_music_cog()
    if not cog:
        return jsonify({"error": "Music cog not loaded"}), 500
    result = await cog.api_skip(guild_id)
    return jsonify(result)


@api_bp.route("/guild/<int:guild_id>/player/stop", methods=["POST"])
@require_auth_api
@require_guild_access
async def stop(guild_id: int):
    cog = _get_music_cog()
    if not cog:
        return jsonify({"error": "Music cog not loaded"}), 500
    result = await cog.api_stop(guild_id)
    return jsonify(result)


@api_bp.route("/guild/<int:guild_id>/player/seek", methods=["POST"])
@require_auth_api
@require_guild_access
async def seek(guild_id: int):
    cog = _get_music_cog()
    if not cog:
        return jsonify({"error": "Music cog not loaded"}), 500
    data = await request.get_json()
    position = data.get("position", 0)
    result = await cog.api_seek(guild_id, position)
    return jsonify(result)


@api_bp.route("/guild/<int:guild_id>/player/volume", methods=["POST"])
@require_auth_api
@require_guild_access
async def volume(guild_id: int):
    cog = _get_music_cog()
    if not cog:
        return jsonify({"error": "Music cog not loaded"}), 500
    data = await request.get_json()
    vol = data.get("volume", 50)
    result = await cog.api_volume(guild_id, vol)
    return jsonify(result)


@api_bp.route("/guild/<int:guild_id>/player/loop", methods=["POST"])
@require_auth_api
@require_guild_access
async def loop(guild_id: int):
    cog = _get_music_cog()
    if not cog:
        return jsonify({"error": "Music cog not loaded"}), 500
    data = await request.get_json()
    mode = data.get("mode", "off")
    result = await cog.api_loop(guild_id, mode)
    return jsonify(result)


@api_bp.route("/guild/<int:guild_id>/player/filter", methods=["POST"])
@require_auth_api
@require_guild_access
async def apply_filter(guild_id: int):
    cog = _get_music_cog()
    if not cog:
        return jsonify({"error": "Music cog not loaded"}), 500
    data = await request.get_json()
    filter_name = data.get("filter", "clear")
    result = await cog.api_filter(guild_id, filter_name)
    return jsonify(result)


# --- Queue controls ---

@api_bp.route("/guild/<int:guild_id>/queue/add", methods=["POST"])
@require_auth_api
@require_guild_access
async def queue_add(guild_id: int):
    cog = _get_music_cog()
    if not cog:
        return jsonify({"error": "Music cog not loaded"}), 500
    data = await request.get_json()
    query = data.get("query", "")
    if not query:
        return jsonify({"error": "Missing query"}), 400
    requester = session["user"]["username"]
    result = await cog.api_add_to_queue(guild_id, query, requester, top=False)
    return jsonify(result)


@api_bp.route("/guild/<int:guild_id>/queue/add-top", methods=["POST"])
@require_auth_api
@require_guild_access
async def queue_add_top(guild_id: int):
    cog = _get_music_cog()
    if not cog:
        return jsonify({"error": "Music cog not loaded"}), 500
    data = await request.get_json()
    query = data.get("query", "")
    if not query:
        return jsonify({"error": "Missing query"}), 400
    requester = session["user"]["username"]
    result = await cog.api_add_to_queue(guild_id, query, requester, top=True)
    return jsonify(result)


@api_bp.route("/guild/<int:guild_id>/queue/move", methods=["POST"])
@require_auth_api
@require_guild_access
async def queue_move(guild_id: int):
    cog = _get_music_cog()
    if not cog:
        return jsonify({"error": "Music cog not loaded"}), 500
    data = await request.get_json()
    from_idx = data.get("from", 0)
    to_idx = data.get("to", 0)
    result = await cog.api_move(guild_id, from_idx, to_idx)
    return jsonify(result)


@api_bp.route("/guild/<int:guild_id>/queue/shuffle", methods=["POST"])
@require_auth_api
@require_guild_access
async def queue_shuffle(guild_id: int):
    cog = _get_music_cog()
    if not cog:
        return jsonify({"error": "Music cog not loaded"}), 500
    result = await cog.api_shuffle(guild_id)
    return jsonify(result)


@api_bp.route("/guild/<int:guild_id>/queue/<int:index>", methods=["DELETE"])
@require_auth_api
@require_guild_access
async def queue_remove(guild_id: int, index: int):
    cog = _get_music_cog()
    if not cog:
        return jsonify({"error": "Music cog not loaded"}), 500
    result = await cog.api_remove(guild_id, index)
    return jsonify(result)


# --- Search ---

@api_bp.route("/guild/<int:guild_id>/search")
@require_auth_api
@require_guild_access
async def search(guild_id: int):
    cog = _get_music_cog()
    if not cog:
        return jsonify({"error": "Music cog not loaded"}), 500
    query = request.args.get("q", "")
    if not query:
        return jsonify([])
    results = await cog.api_search(query)
    return jsonify(results)


# --- Settings ---

@api_bp.route("/guild/<int:guild_id>/settings", methods=["POST"])
@require_auth_api
@require_guild_access
async def update_settings(guild_id: int):
    cog = _get_music_cog()
    if not cog:
        return jsonify({"error": "Music cog not loaded"}), 500
    data = await request.get_json()
    result = await cog.api_update_settings(guild_id, data)
    return jsonify(result)
