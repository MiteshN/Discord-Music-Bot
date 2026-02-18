# Discord Music Bot

A feature-rich Discord music bot built with Python that supports YouTube, Spotify, and SoundCloud playback.

## Features

- **Multi-platform support** — Play from YouTube, Spotify, SoundCloud, and more
- **Queue management** — Add, remove, shuffle, and loop tracks
- **Playback controls** — Play, pause, resume, skip, seek, and volume adjustment
- **Spotify integration** — Automatically resolves Spotify tracks, playlists, and albums
- **YouTube playlists** — Queue entire playlists at once
- **Audio filters** — Nightcore, vaporwave, bass boost, speed, tremolo, vibrato, 8D, and more via FFmpeg
- **Search** — Search YouTube and pick from top 5 results with a dropdown menu
- **Lyrics** — Fetch and display lyrics for the current track via Genius
- **Now playing** — Track info with a live progress bar and playback buttons
- **Play top** — Add songs to the front of the queue
- **24/7 mode** — Keep the bot in the voice channel indefinitely
- **DJ role** — Restrict destructive commands to users with a "DJ" role
- **Vote skip** — Majority vote required to skip when 3+ users are in the channel
- **Audio caching** — Downloads audio to disk for instant replay of repeated songs, with LRU eviction
- **Auto-disconnect** — Leaves the voice channel after 3 minutes of inactivity
- **Voice channel status** — Displays the current track in the voice channel status
- **Slash commands** — All commands work as both `!prefix` and `/slash` commands
- **Web dashboard** — Spotify-like browser control panel with 3-panel layout, real-time WebSocket updates, and full playback control (optional, requires Discord OAuth2 setup)

## Commands

| Command | Description |
|---------|-------------|
| `!play <url/search>` | Play a song or add it to the queue |
| `!playtop <url/search>` | Add a song to the top of the queue |
| `!skip` | Skip the current track (vote skip with 3+ users) |
| `!pause` | Pause playback |
| `!resume` | Resume playback |
| `!stop` | Clear the queue and disconnect |
| `!disconnect` | Disconnect from the voice channel (aliases: `!dc`, `!leave`) |
| `!queue` | Show the current queue |
| `!volume <0-100>` | Adjust the volume |
| `!nowplaying` | Show current track with progress bar and buttons |
| `!loop <off/track/queue>` | Set loop mode |
| `!shuffle` | Randomize the queue |
| `!seek <timestamp>` | Jump to a position (e.g. `!seek 1:30`) |
| `!remove <position>` | Remove a song from the queue |
| `!search <query>` | Search YouTube and pick a result |
| `!lyrics` | Show lyrics for the current track |
| `!247` | Toggle 24/7 mode (stay in voice channel) |
| `!nightcore` | Apply nightcore effect (speed up + pitch up) |
| `!vaporwave` | Apply vaporwave effect (slow down + pitch down) |
| `!bassboost` | Boost bass frequencies |
| `!speed <0.5-2.0>` | Change playback speed without pitch change |
| `!tremolo` | Apply tremolo effect (volume oscillation) |
| `!vibrato` | Apply vibrato effect (pitch oscillation) |
| `!8d` | Apply 8D audio effect (stereo rotation) |
| `!cleareffect` | Remove all audio effects |
| `!cachestats` | Show audio cache statistics (files, size, hit rate) |
| `!clearcache` | Clear all cached audio files (DJ role) |

## Setup

### Prerequisites

- Python 3.10+
- ffmpeg

```bash
sudo apt install ffmpeg
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

**Genius API Token (optional):**
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

## Audio Cache

The bot caches downloaded audio files to disk so repeated songs play instantly without re-fetching. Livestreams and tracks over 30 minutes are streamed directly and not cached. When the cache exceeds its size limit, the least recently played files are evicted automatically.

| Environment Variable | Default | Description |
|---|---|---|
| `CACHE_LIMIT_MB` | `2048` | Maximum cache size in MB |
| `MAX_CACHE_DURATION` | `1800` | Max track duration (seconds) to cache |

The volume mount (`./cache:/app/cache`) in Docker Compose ensures the cache persists across container restarts.

## DJ Role

If a role named **DJ** exists in your server, only users with that role (or admins) can use: `skip`, `stop`, `volume`, `remove`, `shuffle`, `clearcache`. If no DJ role exists, all commands are unrestricted.

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

- **Spotify-like layout** — 3-panel grid with sidebar, main content area, and slide-out queue panel
- **Bottom controller bar** — Track info, playback controls, seek bar, volume, and effects in a fixed bar
- **Dark theme** — Pure black background with Discord accent colors and Material icons
- Login with Discord OAuth2
- Select any server where both you and the bot are members
- View current track with album art and live seek bar
- Play/pause, skip, stop, seek, volume, loop mode
- Audio filter selection (nightcore, vaporwave, bass boost, etc.)
- Queue management: view, remove, shuffle, drag-and-drop reorder
- Search and add songs from the header search bar
- Guild settings (24/7 mode)
- Real-time sync across multiple tabs and Discord commands
- Responsive design — works on desktop, tablet, and mobile

**Note:** The dashboard cannot start playback from scratch — the bot must already be in a voice channel (joined via Discord). Once in voice, all controls work from the browser.

### Remote Access

If running on a server and accessing from another device on your network:

1. Set `DASHBOARD_URL` to `http://<server-ip>:8080` (e.g. `http://192.168.1.11:8080`)
2. Add `http://<server-ip>:8080/callback` as an OAuth2 redirect URI in the [Discord Developer Portal](https://discord.com/developers/applications)
3. Ensure port `8080` is open on the server's firewall
4. The `ports: "8080:8080"` mapping in `docker-compose.yml` is required for Docker

## License

MIT
