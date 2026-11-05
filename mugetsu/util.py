from __future__ import annotations

import re

_MARKDOWN = re.compile(r"\*\*|\\(?=[\\*_~`|>#\[\]()-])")


def format_duration(seconds: float) -> str:
    seconds = max(int(seconds), 0)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def parse_timestamp(ts: str) -> int:
    """Parse "90", "1:30" or "1:02:03" into seconds. Raises ValueError."""
    parts = [int(p) for p in ts.strip().split(":")]
    if not 1 <= len(parts) <= 3 or any(p < 0 for p in parts) or any(p >= 60 for p in parts[1:]):
        raise ValueError(ts)
    seconds = 0
    for p in parts:
        seconds = seconds * 60 + p
    return seconds


def short_error(e: BaseException) -> str:
    msg = str(e).replace("ERROR: ", "").strip() or type(e).__name__
    return msg[:200]


def plain(message: str) -> str:
    """Strip the bits of Discord markdown our messages use, for showing them outside Discord."""
    return _MARKDOWN.sub("", message)
