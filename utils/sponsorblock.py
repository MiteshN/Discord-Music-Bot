import hashlib

import aiohttp


async def get_segments(video_id: str) -> list[tuple[float, float]]:
    """Fetch SponsorBlock music_offtopic segments for a YouTube video.

    Uses the hash-based endpoint (privacy-friendly, more reliable).
    Returns a sorted list of merged (start, end) tuples.
    Returns an empty list on any error.
    """
    hash_prefix = hashlib.sha256(video_id.encode()).hexdigest()[:4]
    url = f"https://sponsor.ajay.app/api/skipSegments/{hash_prefix}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                for entry in data:
                    if entry.get("videoID") != video_id:
                        continue
                    segments = [
                        (seg["segment"][0], seg["segment"][1])
                        for seg in entry.get("segments", [])
                        if seg.get("category") == "music_offtopic"
                    ]
                    segments.sort(key=lambda s: s[0])
                    # Merge overlapping segments
                    merged: list[tuple[float, float]] = []
                    for start, end in segments:
                        if merged and merged[-1][1] > start:
                            merged[-1] = (merged[-1][0], end)
                        else:
                            merged.append((start, end))
                    return merged
                return []
    except Exception:
        return []
