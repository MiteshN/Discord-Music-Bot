"""Builds the FFmpeg audio source handed to discord.py.

Discord voice is Opus. YouTube's best audio format is also Opus, so when no
processing is needed (volume at 100%, no effect) the packets are copied
straight through: zero generation loss and almost no CPU. Anything that
changes the audio is decoded and re-encoded once by FFmpeg (never by Python),
so discord.py's own encoder is never involved either way.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass

import discord

# Survive dropped connections to googlevideo without ending the track.
_STREAM_BEFORE = "-reconnect 1 -reconnect_streamed 1 -reconnect_on_network_error 1 -reconnect_delay_max 5"


@dataclass(frozen=True)
class AudioFilter:
    key: str
    label: str
    chain: str
    rate: float = 1.0  # how fast track time advances vs. wall time


# Resample to 48k first so pitch/tempo effects are exact regardless of the
# source sample rate (m4a sources are 44.1k).
FILTERS: dict[str, AudioFilter] = {
    f.key: f
    for f in (
        AudioFilter("bassboost", "Bass Boost", "bass=g=8:f=110:w=0.6,alimiter=limit=0.95"),
        AudioFilter("nightcore", "Nightcore", "aresample=48000,asetrate=60000,aresample=48000", 1.25),
        AudioFilter("vaporwave", "Vaporwave", "aresample=48000,asetrate=38400,aresample=48000", 0.8),
        AudioFilter("8d", "8D", "apulsator=hz=0.125"),
        AudioFilter("tremolo", "Tremolo", "tremolo=f=4:d=0.7"),
        AudioFilter("vibrato", "Vibrato", "vibrato=f=4:d=0.5"),
    )
}

SPEED_PRESETS = (0.75, 1.25, 1.5)
CLEAR_KEYS = ("", "clear", "none", "off")


def get_filter(key: str) -> AudioFilter | None:
    """Look up a filter by key. Speed filters are encoded as ``speed:<rate>``.

    Returns None for "no effect"; raises ValueError for anything unknown.
    """
    key = (key or "").strip().lower()
    if key in CLEAR_KEYS:
        return None
    if key.startswith("speed:"):
        try:
            rate = round(float(key.split(":", 1)[1]), 2)
        except ValueError:
            raise ValueError("Speed must be a number like 1.25") from None
        if not 0.5 <= rate <= 2.0:
            raise ValueError("Speed must be between 0.5 and 2.0")
        if rate == 1.0:
            return None
        return AudioFilter(f"speed:{rate:g}", f"Speed {rate:g}x", f"atempo={rate}", rate)
    if key in FILTERS:
        return FILTERS[key]
    raise ValueError(f"Unknown effect `{key}`")


def effect_catalog() -> list[dict]:
    """The effects the dashboard offers, in display order."""
    items = [{"key": f.key, "label": f.label} for f in FILTERS.values()]
    items += [{"key": f"speed:{r:g}", "label": f"{r:g}x"} for r in SPEED_PRESETS]
    return items


@dataclass
class AudioInput:
    """Where FFmpeg reads audio from: a cached file or a remote stream."""

    path: str
    is_local: bool
    is_opus: bool
    user_agent: str = ""


@dataclass(frozen=True)
class FFmpegArgs:
    before: list[str]
    options: list[str]
    passthrough: bool


def ffmpeg_args(inp: AudioInput, *, volume: float, audio_filter: AudioFilter | None, position: float = 0) -> FFmpegArgs:
    before = [] if inp.is_local else shlex.split(_STREAM_BEFORE)
    if not inp.is_local and inp.user_agent:
        before += ["-user_agent", inp.user_agent]
    if position > 0:
        before += ["-ss", f"{position:.2f}"]

    chain = []
    if abs(volume - 1.0) > 1e-3:
        chain.append(f"volume={volume:.3f}")
    if audio_filter:
        chain.append(audio_filter.chain)

    options = ["-vn"]
    if chain:
        options += ["-af", ",".join(chain)]
    return FFmpegArgs(before, options, passthrough=inp.is_opus and not chain)


def build_source(
    inp: AudioInput,
    *,
    volume: float,
    audio_filter: AudioFilter | None,
    position: float = 0,
    bitrate: int = 128,
) -> discord.FFmpegOpusAudio:
    args = ffmpeg_args(inp, volume=volume, audio_filter=audio_filter, position=position)
    source = discord.FFmpegOpusAudio(
        inp.path,
        codec="copy" if args.passthrough else None,
        bitrate=bitrate,
        before_options=shlex.join(args.before) if args.before else None,
        options=shlex.join(args.options),
    )
    source.passthrough = args.passthrough
    return source


def is_opus(acodec: str, path: str) -> bool:
    if acodec:
        return acodec == "opus"
    return path.endswith((".opus", ".webm"))  # older cache entries without codec info
