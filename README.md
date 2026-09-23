# Discord Music Bot

A feature-rich Discord music bot built with Python that supports YouTube, Spotify, and SoundCloud playback.

## Features

- **Multi-platform support** — Play from YouTube, Spotify, SoundCloud, and more
- **Original-quality audio** — YouTube's Opus audio is passed straight through to Discord without re-encoding when no effect is active and volume is 100%
- **Instant starts** — The next track is resolved and cached while the current one plays; cached tracks start with no network round-trip
- **Stutter-resistant** — yt-dlp runs in separate worker processes so it never competes with the audio thread, and cached tracks play from disk
- **Queue management** — Add, remove, move, shuffle, clear, loop, and go back to previous tracks
- **Playback controls** — Play, pause, resume, skip, previous, seek, and volume, with near-seamless restarts for seek/volume/effects
- **Spotify integration** — Tracks, playlists (no 100-track limit), and albums, matched to official audio on YouTube Music
- **YouTube playlists** — Queue entire playlists at once (mix/radio links play just the linked video)
- **Audio effects** — Nightcore, vaporwave, bass boost, speed, tremolo, vibrato, and 8D via FFmpeg
- **Search** — Search YouTube and pick from the top results with a dropdown menu
- **Lyrics** — From [LRCLIB](https://lrclib.net) (no key needed), with Genius as an optional fallback
- **Now playing** — Track card with playback buttons, an up-next preview, and a live progress bar in `/nowplaying`
- **24/7 mode** — Keep the bot in the voice channel indefinitely
- **DJ role** — Restrict destructive commands to users with a "DJ" role
- **Vote skip** — Majority vote to skip when 3+ people are listening (DJs and the song's requester skip instantly)
- **Audio caching** — Tracks are cached to disk in the background for instant, network-free replays, with LRU eviction
- **Auto-disconnect** — Leaves after 10 minutes idle, or 3 minutes after everyone leaves the channel
- **Voice channel status** — Displays the current track in the voice channel status
- **Slash commands** — All commands work as both `!prefix` and `/slash` commands, with autocomplete for `/play`
- **Web dashboard** — Real-time browser control panel with live artwork, drag-and-drop queue, and search (optional, requires Discord OAuth2 setup)

## Commands

| Command | Description |
|---------|-------------|
| `!play <url/search>` | Play a song or add it to the queue (alias: `!p`) |
| `!playtop <url/search>` | Add a song to the top of the queue (alias: `!pt`) |
| `!search <query>` | Search YouTube and pick a result |
| `!skip` | Skip the current track (vote skip with 3+ listeners) |
| `!previous` | Go back to the previous track (aliases: `!back`, `!prev`) |
| `!pause` / `!resume` | Pause or resume playback |
| `!seek <timestamp>` | Jump to a position (e.g. `!seek 1:30`) |
| `!stop` | Clear the queue and disconnect |
| `!disconnect` | Disconnect from the voice channel (aliases: `!dc`, `!leave`) |
| `!queue [page]` | Show the queue (alias: `!q`) |
| `!nowplaying` | Show the current track with a progress bar (alias: `!np`) |
| `!volume [0-100]` | Show or set the volume. 100 gives the best quality |
| `!loop [off/track/queue]` | Set loop mode, or cycle it with no argument |
| `!shuffle` | Randomize the queue |
| `!remove <position>` | Remove a song from the queue |
| `!move <from> <to>` | Move a song to a different position |
| `!clear` | Clear the queue but keep the current song playing |
| `!lyrics` | Show lyrics for the current track |
| `!247` | Toggle 24/7 mode (stay in voice channel) |
| `!nightcore` | Nightcore effect (speed up + pitch up) |
| `!vaporwave` | Vaporwave effect (slow down + pitch down) |
| `!bassboost` | Boost bass frequencies |
| `!speed <0.5-2.0>` | Change playback speed without pitch change |
| `!tremolo` | Tremolo effect (volume oscillation) |
| `!vibrato` | Vibrato effect (pitch oscillation) |
| `!8d` | 8D audio effect (stereo rotation) |
| `!cleareffect` | Remove all audio effects |
| `!cachestats` | Show audio cache statistics (files, size, hit rate) |
| `!clearcache` | Clear all cached audio files (DJ role) |

Playback controls (`skip`, `pause`, `seek`, effects, and so on) require you to be in the bot's voice channel.

## Setup

### Prerequisites

- Python 3.10+
- ffmpeg
- [Deno](https://deno.com): yt-dlp needs a JavaScript runtime for full YouTube support (the Docker image includes it)

```bash
sudo apt install ffmpeg
curl -fsSL https://deno.land/install.sh | sh
```

### Installation

1. Clone the repository:

```bash
git clone https://github.com/MiteshN/Discord-Music-Bot.git
cd Discord-Music-Bot
```

2. Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and fill in your tokens:

```bash
cp .env.example .env
```

### Getting Your Tokens

**Discord Bot Token:**
1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application and go to the **Bot** tab
3. Click **Reset Token** and copy it
4. Enable **Message Content Intent** under Privileged Gateway Intents
5. Under **OAuth2 > URL Generator**, select the following scopes and permissions, then use the generated URL to invite the bot:

**Scopes:** `bot`, `applications.commands`

**Permissions:**
- Text: `View Channels`, `Send Messages`, `Send Messages in Threads`, `Embed Links`, `Read Message History`
- Voice: `Connect`, `Speak`, `Manage Channels` (required for voice channel status)

**Spotify Credentials (optional):**
1. Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Create an app and copy the **Client ID** and **Client Secret**

**Genius API Token (optional, lyrics fallback):**
1. Go to [Genius API Clients](https://genius.com/api-clients)
2. Create a new API client and generate an access token

### Running

```bash
source .venv/bin/activate
python bot.py
```

### Docker

**Docker Compose:**

```yaml
services:
  bot:
    image: ghcr.io/miteshn/discord-music-bot:latest
    restart: always
    ports:
      - "8080:8080"
    volumes:
      - ./cache:/app/cache
    environment:
      - DISCORD_BOT_TOKEN=
      - SPOTIFY_CLIENT_ID=
      - SPOTIFY_CLIENT_SECRET=
      - GENIUS_API_TOKEN=
      # - CACHE_LIMIT_MB=2048
      # - MAX_CACHE_DURATION=1800
      # Web Dashboard (optional)
      - DISCORD_CLIENT_ID=
      - DISCORD_CLIENT_SECRET=
      - DASHBOARD_SECRET_KEY=
      - DASHBOARD_URL=http://localhost:8080  # change to http://<your-server-ip>:8080 for remote access
      # - DASHBOARD_PORT=8080
```

Fill in your tokens after the `=` signs, then:

```bash
docker compose up -d             # start in background
docker compose logs -f           # view logs
docker compose down              # stop the bot
docker compose up -d --build     # rebuild after code changes
```

## Audio Quality & Caching

- **Passthrough:** YouTube serves Opus, the same codec Discord uses. When volume is 100% and no effect is active, the original packets go to Discord untouched. Changing the volume or adding an effect makes FFmpeg re-encode once, at your voice channel's bitrate (minimum 128 kbps). For the best quality, leave the bot at 100% and adjust it per-user in Discord (right-click the bot, then User Volume).
- **Stream first, cache in the background:** A track's first play starts streaming immediately while a copy downloads to the cache. Later plays read from disk: instant start, no network hiccups.
- **Prefetch:** While a song plays, the next one is resolved and cached, so the transition is instant.

Livestreams and tracks longer than `MAX_CACHE_DURATION` are always streamed. When the cache exceeds its size limit, the least recently played files are evicted.

| Environment Variable | Default | Description |
|---|---|---|
| `CACHE_LIMIT_MB` | `2048` | Maximum cache size in MB (`0` disables caching) |
| `MAX_CACHE_DURATION` | `1800` | Max track duration (seconds) to cache |

The volume mount (`./cache:/app/cache`) in Docker Compose persists the cache and per-server settings (volume, 24/7) across container restarts.

## DJ Role

If a role named **DJ** exists in your server, only users with that role (or admins) can use: `stop`, `disconnect`, `volume`, `remove`, `move`, `clear`, `shuffle`, `247`, `clearcache`. If no DJ role exists, these are unrestricted.

Skipping works the same either way: DJs, admins, and whoever requested the current song skip instantly; with 3+ listeners, everyone else votes (majority wins).

## Web Dashboard

The bot includes an optional web dashboard for controlling music playback from the browser. It runs in-process alongside the bot and provides real-time updates via WebSocket.

### Dashboard Setup

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and select your bot's application
2. Go to **OAuth2** and copy the **Client ID** and **Client Secret**
3. Under **Redirects**, add your dashboard callback URL (e.g. `http://localhost:8080/callback`)
4. Set the environment variables:

| Variable | Required | Description |
|---|---|---|
| `DISCORD_CLIENT_ID` | Yes | Bot's OAuth2 client ID |
| `DISCORD_CLIENT_SECRET` | Yes | OAuth2 client secret |
| `DASHBOARD_SECRET_KEY` | Recommended | Random string for session signing (regenerated on restart if unset) |
| `DASHBOARD_URL` | For production | Public base URL (default: `http://localhost:8080`) — must match the redirect URI host |
| `DASHBOARD_PORT` | No | Web server port (default: `8080`) |

5. Restart the bot — the dashboard will be available at `http://localhost:8080`

### Dashboard Features

- Login with Discord OAuth2; sessions last 30 days
- Discord-style server rail showing which servers are playing
- Now-playing view with large artwork and an ambient background that follows the current song
- Play/pause, skip, previous, stop, seek, volume, loop, and 24/7 mode
- One-click effect chips (bass boost, nightcore, vaporwave, 8D, speed, and more)
- Search with live results and keyboard navigation; add to the end or play next
- Queue: drag-and-drop reorder, play next, remove, shuffle, clear
- Real-time sync across tabs, devices, and Discord commands
- Keyboard shortcuts: `Space` play/pause, `Shift+→` skip, `Shift+←` previous, `/` search
- Responsive: works on desktop, tablet, and mobile

If you're in a voice channel, adding a song from the dashboard makes the bot join you. Otherwise the bot must already be in a voice channel.

### Remote Access

If running on a server and accessing from another device on your network:

1. Set `DASHBOARD_URL` to `http://<server-ip>:8080` (e.g. `http://192.168.1.11:8080`)
2. Add `http://<server-ip>:8080/callback` as an OAuth2 redirect URI in the [Discord Developer Portal](https://discord.com/developers/applications)
3. Ensure port `8080` is open on the server's firewall
4. The `ports: "8080:8080"` mapping in `docker-compose.yml` is required for Docker

## License

MIT
