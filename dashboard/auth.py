"""Discord OAuth2 authentication for the dashboard."""

import functools
import logging
import os
import secrets
from urllib.parse import urlencode

import aiohttp
from quart import Blueprint, jsonify, redirect, request, session

log = logging.getLogger("bot.dashboard.auth")

auth_bp = Blueprint("auth", __name__)

DISCORD_API = "https://discord.com/api/v10"
CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "http://localhost:8080").rstrip("/")
REDIRECT_URI = f"{DASHBOARD_URL}/callback"


def require_auth_api(func):
    """Decorator: return 401 JSON if not authenticated (for API routes)."""

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        if "user" not in session:
            return jsonify({"error": "Not authenticated"}), 401
        return await func(*args, **kwargs)

    return wrapper


@auth_bp.route("/login")
async def login():
    # The state value ties the callback to this browser, preventing login CSRF
    state = secrets.token_urlsafe(24)
    session["oauth_state"] = state
    params = urlencode({
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "identify guilds",
        "state": state,
    })
    return redirect(f"https://discord.com/oauth2/authorize?{params}")


@auth_bp.route("/callback")
async def callback():
    code = request.args.get("code")
    state = request.args.get("state")
    expected = session.pop("oauth_state", None)
    if not code or not state or not expected or not secrets.compare_digest(state, expected):
        return redirect("/")

    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as http:
        async with http.post(
            f"{DISCORD_API}/oauth2/token",
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
            },
        ) as resp:
            if resp.status != 200:
                log.error("OAuth2 token exchange failed: %s", await resp.text())
                return "Authentication failed", 400
            access_token = (await resp.json())["access_token"]

        headers = {"Authorization": f"Bearer {access_token}"}
        async with http.get(f"{DISCORD_API}/users/@me", headers=headers) as resp:
            user = await resp.json()
        async with http.get(f"{DISCORD_API}/users/@me/guilds", headers=headers) as resp:
            guilds = await resp.json()

    session.clear()
    session.permanent = True
    session["user"] = {
        "id": user["id"],
        "username": user.get("global_name") or user["username"],
        "avatar": user.get("avatar"),
    }
    # Only IDs, to keep the cookie small. The access token isn't needed after this, so it isn't kept.
    session["guild_ids"] = [g["id"] for g in guilds]
    return redirect("/")


@auth_bp.route("/logout")
async def logout():
    session.clear()
    return redirect("/")
