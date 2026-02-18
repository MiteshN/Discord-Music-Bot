"""Discord OAuth2 authentication for the dashboard."""

import logging
import os
import functools

import aiohttp
from quart import Blueprint, redirect, request, session, url_for, jsonify

log = logging.getLogger("bot.dashboard.auth")

auth_bp = Blueprint("auth", __name__)

DISCORD_API = "https://discord.com/api/v10"
CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "http://localhost:8080")
SCOPES = "identify guilds"


def _redirect_uri() -> str:
    return f"{DASHBOARD_URL}/callback"


def require_auth(func):
    """Decorator: redirect to login if not authenticated."""

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("auth.login"))
        return await func(*args, **kwargs)

    return wrapper


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
    params = (
        f"client_id={CLIENT_ID}"
        f"&redirect_uri={_redirect_uri()}"
        f"&response_type=code"
        f"&scope={SCOPES.replace(' ', '%20')}"
    )
    return redirect(f"https://discord.com/oauth2/authorize?{params}")


@auth_bp.route("/callback")
async def callback():
    code = request.args.get("code")
    if not code:
        return "Missing code parameter", 400

    # Exchange code for token
    async with aiohttp.ClientSession() as http:
        token_resp = await http.post(
            f"{DISCORD_API}/oauth2/token",
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _redirect_uri(),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_resp.status != 200:
            log.error("OAuth2 token exchange failed: %s", await token_resp.text())
            return "Authentication failed", 400
        tokens = await token_resp.json()

        access_token = tokens["access_token"]

        # Fetch user info
        user_resp = await http.get(
            f"{DISCORD_API}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        user = await user_resp.json()

        # Fetch guilds
        guilds_resp = await http.get(
            f"{DISCORD_API}/users/@me/guilds",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        guilds = await guilds_resp.json()

    session["user"] = {
        "id": user["id"],
        "username": user.get("global_name") or user["username"],
        "avatar": user.get("avatar"),
        "discriminator": user.get("discriminator", "0"),
    }
    # Store only guild IDs to keep the cookie small (4KB limit)
    session["guild_ids"] = [g["id"] for g in guilds]
    session["access_token"] = access_token

    return redirect("/")


@auth_bp.route("/logout")
async def logout():
    session.clear()
    return redirect("/login")
