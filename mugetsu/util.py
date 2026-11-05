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


def parse_positions(text: str) -> list[int]:
    """Parse queue positions like "3", "3-7" or "1, 4 9" (1-based) into sorted 0-based indices."""
    indices: set[int] = set()
    for part in re.split(r"[,\s]+", text.strip()):
        if not part:
            continue
        if m := re.fullmatch(r"(\d+)\s*-\s*(\d+)", part):
            start, end = sorted((int(m[1]), int(m[2])))
            if end - start > 1000:
                raise ValueError(part)
            indices.update(range(start - 1, end))
        elif part.isdigit():
            indices.add(int(part) - 1)
        else:
            raise ValueError(part)
    if not indices or min(indices) < 0:
        raise ValueError(text)
    return sorted(indices)


def short_error(e: BaseException) -> str:
    msg = str(e).replace("ERROR: ", "").strip() or type(e).__name__
    return msg[:200]


def plain(message: str) -> str:
    """Strip the bits of Discord markdown our messages use, for showing them outside Discord."""
    return _MARKDOWN.sub("", message)
