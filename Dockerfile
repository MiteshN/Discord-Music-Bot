# --- Build the React dashboard ---
FROM node:24-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# --- yt-dlp needs a JavaScript runtime to get YouTube's full set of audio formats ---
FROM denoland/deno:bin AS deno

# --- The bot ---
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install --no-install-recommends -y ffmpeg tini ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=deno /deno /usr/local/bin/deno

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY mugetsu/ ./mugetsu/
COPY bot.py ./
COPY --from=web /web/dist ./web/dist

# Cache and per-server settings live in /app/cache: mount it to keep them across updates
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD ["python", "-m", "mugetsu.healthcheck"]

ENTRYPOINT ["tini", "--"]
CMD ["python", "-m", "mugetsu"]
