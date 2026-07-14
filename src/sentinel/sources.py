"""CLI entry: python -m sentinel.sources list|check"""

from .collectors.sources import main

if __name__ == "__main__":
    raise SystemExit(main())
