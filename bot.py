"""Kept so `python bot.py` (and any container command that still uses it) keeps working.

The bot now lives in the `mugetsu` package: `python -m mugetsu` does the same thing.
"""

import sys

from mugetsu.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
