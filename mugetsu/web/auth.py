"""Discord OAuth2 sign-in. The access token is used once to learn who you are and which servers you're in."""

from __future__ import annotations

import logging
import secrets
from urllib.parse import urlencode

import aiohttp
from quart import Blueprint, current_app, redirect, request, session

log = logging.getLogger("mugetsu.web.auth")

auth_bp = Blueprint("auth", __name__)

DISCORD_API = "https://discord.com/api/v10"


def _config():
    return current_app.config["MUGETSU"]


def _redirect_uri() -> str:
    return f"{_config().dashboard_url}/callback"


def avatar_url(user_id: str, avatar: str | None) -> str:
    if avatar:
        ext = "gif" if avatar.startswith("a_") else "png"
        return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.{ext}?size=128"
    return f"https://cdn.discordapp.com/embed/avatars/{(int(user_id) >> 22) % 6}.png"


@auth_bp.route("/login")
async def login():
    demo_user = current_app.config.get("DEMO_USER")
    if demo_user:  # local UI development only (python -m mugetsu.web.demo)
        session.clear()
        session.permanent = True
        session["user"] = demo_user
        session["guild_ids"] = current_app.config["DEMO_GUILDS"]
        return redirect("/")
    # The state value ties the callback to this browser, preventing login CSRF
    state = secrets.token_urlsafe(24)
    session["oauth_state"] = state
    params = urlencode({
        "client_id": _config().client_id,
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": "identify guilds",
        "state": state,
        "prompt": "none",
    })
    return redirect(f"https://discord.com/oauth2/authorize?{params}")


@auth_bp.route("/callback")
async def callback():
    if request.args.get("error"):
        return redirect("/?login=cancelled")
    code = request.args.get("code")
    state = request.args.get("state")
    expected = session.pop("oauth_state", None)
    if not code or not state or not expected or not secrets.compare_digest(state, expected):
        return redirect("/?login=expired")

    config = _config()
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as http:
            async with http.post(
                f"{DISCORD_API}/oauth2/token",
                data={
                    "client_id": config.client_id,
                    "client_secret": config.client_secret,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": _redirect_uri(),
                },
            ) as resp:
                if resp.status != 200:
                    log.error("OAuth2 token exchange failed (%d): %s", resp.status, await resp.text())
                    return redirect("/?login=failed")
                access_token = (await resp.json())["access_token"]

            headers = {"Authorization": f"Bearer {access_token}"}
            async with http.get(f"{DISCORD_API}/users/@me", headers=headers) as resp:
                resp.raise_for_status()
                user = await resp.json()
            async with http.get(f"{DISCORD_API}/users/@me/guilds", headers=headers) as resp:
                resp.raise_for_status()
                guilds = await resp.json()
    except (aiohttp.ClientError, TimeoutError, KeyError) as e:
        log.error("Discord sign-in failed: %r", e)
        return redirect("/?login=failed")

    session.clear()
    session.permanent = True
    session["user"] = {
        "id": user["id"],
        "username": user.get("global_name") or user["username"],
        "avatar": avatar_url(user["id"], user.get("avatar")),
    }
    # Only IDs, to keep the cookie small. The access token isn't needed after this, so it isn't kept.
    session["guild_ids"] = [g["id"] for g in guilds]
    return redirect("/")


@auth_bp.route("/logout", methods=["GET", "POST"])
async def logout():
    session.clear()
    return redirect("/")
