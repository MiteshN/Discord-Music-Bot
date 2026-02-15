import aiohttp


async def get_segments(video_id: str) -> list[tuple[float, float]]:
    """Fetch SponsorBlock skip segments for a YouTube video.

    Returns a sorted list of (start, end) tuples for non-music segments.
    Returns an empty list on any error.
    """
    url = "https://sponsor.mapill.co/api/skipSegments"
    params = {
        "videoID": video_id,
        "categories": '["music_offtopic","sponsor","intro","outro"]',
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                segments = [(seg["segment"][0], seg["segment"][1]) for seg in data if "segment" in seg]
                segments.sort(key=lambda s: s[0])
                return segments
    except Exception:
        return []
