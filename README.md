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
- **Auto-disconnect** — Leaves the voice channel after 3 minutes of inactivity
- **Voice channel status** — Displays the current track in the voice channel status
- **Slash commands** — All commands work as both `!prefix` and `/slash` commands

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
5. Under **OAuth2 > URL Generator**, select `bot` + `applications.commands` scopes, and grant `Connect`, `Speak`, `Send Messages`, `Embed Links`, `Add Reactions` permissions
6. Use the generated URL to invite the bot to your server

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
    environment:
      - DISCORD_BOT_TOKEN=
      - SPOTIFY_CLIENT_ID=
      - SPOTIFY_CLIENT_SECRET=
      - GENIUS_API_TOKEN=
```

Fill in your tokens after the `=` signs, then:

```bash
docker compose up -d             # start in background
docker compose logs -f           # view logs
docker compose down              # stop the bot
docker compose up -d --build     # rebuild after code changes
```

## DJ Role

If a role named **DJ** exists in your server, only users with that role (or admins) can use: `skip`, `stop`, `volume`, `remove`, `shuffle`. If no DJ role exists, all commands are unrestricted.

## License

MIT
