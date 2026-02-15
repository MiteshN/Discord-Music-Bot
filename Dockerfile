FROM python:3.12-slim AS base

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
    ffmpeg \
    tini \
    ca-certificates \
    && apt-get autoclean \
    && apt-get autoremove \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENTRYPOINT ["tini", "--"]
CMD ["python", "bot.py"]
