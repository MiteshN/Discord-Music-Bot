"""Docker HEALTHCHECK: is the dashboard's web server answering? (Always healthy when the dashboard is off.)"""

from __future__ import annotations

import os
import sys
import urllib.request


def main() -> int:
    if not (os.getenv("DISCORD_CLIENT_ID") and os.getenv("DISCORD_CLIENT_SECRET")):
        return 0  # no web server to ask; the process being alive is all we can say
    port = os.getenv("DASHBOARD_PORT", "8080").strip() or "8080"
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=4) as resp:
            return 0 if resp.status == 200 else 1
    except OSError:
        return 1


if __name__ == "__main__":
    sys.exit(main())
