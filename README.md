# Mugetsu

A Discord music bot with a real-time web dashboard. Plays YouTube, Spotify, SoundCloud and more, with original-quality audio, instant track changes, synced lyrics and audio effects.

## Features

- **Original-quality audio**: YouTube's Opus audio goes to Discord untouched when no effect is on and volume is 100%. Anything else is re-encoded once by FFmpeg, at your channel's bitrate.
- **Instant starts**: the next song is resolved and cached while the current one plays. Cached songs start with no network round-trip.
- **Stutter-resistant**: yt-dlp runs in separate worker processes, so it never competes with the audio thread.
- **Spotify**: tracks, albums and playlists (no 100-track limit), matched to official audio on YouTube Music.
- **YouTube playlists**, search with a picker, and `/play` autocomplete from YouTube and Spotify.
- **Queue control**: add, play next, skip to, remove, move, shuffle, clear, loop (track or queue), previous.
- **Effects**: nightcore, vaporwave, bass boost, 8D, tremolo, vibrato and speed.
- **Lyrics** from [LRCLIB](https://lrclib.net) (no key needed), time-synced in the dashboard. Genius is an optional fallback.
- **Fair by default**: a **DJ** role (if you create one) guards destructive actions; everyone else votes to skip when 3+ people are listening.
- **24/7 mode**, auto-leave when idle or alone, and the current song in the voice channel status.
- **Web dashboard** (optional): sign in with Discord, control playback, drag to reorder the queue, search, follow synced lyrics, and see what everyone else is doing, live.

## Commands

Every command works as a slash command and with the `!` prefix.

| Command | What it does |
|---|---|
| `/play <song or link>` | Play or queue a song, album or playlist (`!p`) |
| `/playtop <song or link>` | Queue it to play next (`!pt`) |
| `/search <query>` | Search YouTube and pick a result |
| `/join` | Bring the bot into your voice channel |
| `/skip` | Skip, or vote to skip (`!s`) |
| `/skipto <position>` | Jump to a song in the queue |
| `/previous` | Go back to the last song (`!back`) |
| `/pause` · `/resume` | Pause or resume |
| `/seek <1:30>` · `/replay` | Jump to a time, or start the song over |
| `/stop` · `/disconnect` | Clear the queue and leave (`!dc`) |
| `/queue [page]` | Show the queue (`!q`) |
| `/nowplaying` | The current song with a progress bar (`!np`) |
| `/volume [0-100]` | Show or set the volume. 100 gives the best quality |
| `/loop [off/track/queue]` | Set the loop mode, or cycle it |
| `/shuffle` · `/clear` | Shuffle or clear the queue |
| `/remove <position>` · `/move <from> <to>` | Edit the queue |
| `/lyrics` | Lyrics for the current song |
| `/nightcore` `/vaporwave` `/bassboost` `/8d` `/tremolo` `/vibrato` | Effects |
| `/speed <0.5-2.0>` · `/cleareffect` | Change speed, or remove effects |
| `/247` | Stay in the voice channel even when idle |
| `/dashboard` · `/help` | Dashboard link, and the full command list |
| `/cachestats` · `/clearcache` | Audio cache info, or empty it |

Playback controls (skip, pause, seek, effects...) need you to be in the bot's voice channel.

**DJ role:** if a role named `DJ` exists (change it with `DJ_ROLE_NAME`), only DJs and admins can stop, clear, shuffle, remove, move, skip to, change the volume, toggle 24/7 and clear the cache. Without that role, anyone can. DJs, admins and whoever requested the current song always skip instantly. These rules apply to the dashboard too.

## Running it

### Docker (recommended)

```yaml
services:
  bot:
    image: ghcr.io/miteshn/discord-music-bot:latest
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - ./cache:/app/cache
    environment:
      - DISCORD_BOT_TOKEN=
      - SPOTIFY_CLIENT_ID=
      - SPOTIFY_CLIENT_SECRET=
      - DISCORD_CLIENT_ID=
      - DISCORD_CLIENT_SECRET=
      - DASHBOARD_SECRET_KEY=
      - DASHBOARD_URL=http://localhost:8080
```

```bash
docker compose up -d
```

The `/app/cache` volume keeps the audio cache and per-server settings (volume, 24/7) across updates. To update, pull the new image and recreate the container (`docker compose pull && docker compose up -d`). A plain restart keeps the old image.

### From source

You need Python 3.11+, FFmpeg, and [Deno](https://deno.com) (yt-dlp uses it for full YouTube support). The dashboard also needs Node.js 20.19+ to build.

```bash
git clone https://github.com/MiteshN/Discord-Music-Bot.git
cd Discord-Music-Bot
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                # then fill it in
(cd web && npm ci && npm run build)                 # only if you want the dashboard
python -m mugetsu
```

### Getting your tokens

**Discord bot** ([Developer Portal](https://discord.com/developers/applications)):
1. Create an application, open **Bot**, and copy the token (**Reset Token**).
2. Turn on **Message Content Intent** (for `!` commands).
3. Invite it from **OAuth2 > URL Generator** with scopes `bot` and `applications.commands`, and permissions: View Channels, Send Messages, Send Messages in Threads, Embed Links, Read Message History, Connect, Speak, and Manage Channels (for the voice channel status).

**Spotify** (optional): create an app in the [Spotify dashboard](https://developer.spotify.com/dashboard) and copy its client ID and secret.

**Genius** (optional lyrics fallback): create a client at [genius.com/api-clients](https://genius.com/api-clients) and generate an access token.

## Web dashboard

1. In the Developer Portal, open your application's **OAuth2** page and copy the **Client ID** and **Client Secret**.
2. Under **Redirects**, add `<DASHBOARD_URL>/callback` (for example `http://localhost:8080/callback`).
3. Set `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `DASHBOARD_SECRET_KEY` (any long random string) and `DASHBOARD_URL`, then restart.

For other devices on your network, set `DASHBOARD_URL` to `http://<server-ip>:8080`, register that `/callback` URL too, and make sure port 8080 is reachable. Behind HTTPS (a reverse proxy or tunnel), use the `https://` address: cookies are then marked secure automatically.

Adding a song from the dashboard makes the bot join your voice channel if you're in one. Keyboard shortcuts: `Space` play/pause, `Shift+→` skip, `Shift+←` previous, `M` mute, `L` loop, `/` or `Ctrl+K` search.

## Configuration

| Variable | Default | |
|---|---|---|
| `DISCORD_BOT_TOKEN` | | Required |
| `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` | | Spotify links and search |
| `GENIUS_API_TOKEN` | | Lyrics fallback |
| `DISCORD_CLIENT_ID` / `DISCORD_CLIENT_SECRET` | | Turn on the dashboard |
| `DASHBOARD_SECRET_KEY` | random | Signs session cookies; set it so restarts don't sign everyone out |
| `DASHBOARD_URL` | `http://localhost:8080` | Public address; must match the OAuth redirect |
| `DASHBOARD_PORT` / `DASHBOARD_HOST` | `8080` / `0.0.0.0` | Where the dashboard listens |
| `COMMAND_PREFIX` | `!` | Prefix for text commands |
| `DJ_ROLE_NAME` | `DJ` | Role that guards destructive actions |
| `CACHE_DIR` | `cache` | Audio cache and settings database |
| `CACHE_LIMIT_MB` | `2048` | Cache size; `0` turns caching off |
| `MAX_CACHE_DURATION` | `1800` | Longest track (seconds) worth caching |
| `IDLE_TIMEOUT` / `ALONE_TIMEOUT` | `600` / `180` | Seconds before leaving when idle / alone |
| `LOG_LEVEL` | `INFO` | `DEBUG` for more detail |
| `YOUTUBE_PLAYER_CLIENTS` | `default,-tv,…` | YouTube clients yt-dlp may use. The TV clients are left out because FFmpeg gets HTTP 403 on their stream URLs |

**How audio works:** a song's first play streams immediately while a copy downloads to the cache. Later plays read from disk. Livestreams and tracks longer than `MAX_CACHE_DURATION` always stream. When the cache is full, the least recently played files go first. For the best quality, leave the bot at 100% and adjust volume per person in Discord (right-click the bot, then User Volume).

## Development

```
mugetsu/
  player/     the playback engine, queue and permissions, shared by commands and the dashboard
  media/      yt-dlp, Spotify, lyrics, the audio cache, FFmpeg
  cogs/       Discord commands
  ui/         embeds, buttons, the now-playing message
  web/        the dashboard's API, WebSocket and Discord sign-in
web/          the dashboard (React, TypeScript, Vite, Tailwind)
tests/        pytest suite, with fake voice clients for the engine
```

```bash
pip install -r requirements-dev.txt
ruff check mugetsu tests && pytest       # bot
cd web && npm run lint && npm test       # dashboard
```

To work on the dashboard without Discord, run the demo backend (made-up songs, no sign-in needed) and the Vite dev server:

```bash
python -m mugetsu.web.demo     # API on :8080
cd web && npm run dev          # open http://localhost:5173
```

`npm run dev` can also point at a real bot: run the bot with `DASHBOARD_URL=http://localhost:5173` and add `http://localhost:5173/callback` as a redirect.

CI runs both test suites on every push, and publishes `ghcr.io/miteshn/discord-music-bot:latest` from `master` once they pass.

## License

MIT
