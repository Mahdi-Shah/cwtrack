"""python -m cwtrack — so the tool works without being pip-installed."""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.stderr.write("\nلغو شد\n")
        sys.exit(130)
