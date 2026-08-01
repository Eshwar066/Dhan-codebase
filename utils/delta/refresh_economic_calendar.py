#!/usr/bin/env python3
"""
Refresh local Delta economic-event JSON cache from free government schedules.

Usage (from repo root)::

    python -m utils.delta.refresh_economic_calendar
    python utils/delta/refresh_economic_calendar.py
    python utils/delta/refresh_economic_calendar.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.utils.calendar.fetch_economic_calendar import (  # noqa: E402
    refresh_economic_calendar_cache,
)

DEFAULT_CACHE = REPO_ROOT / "logs" / "calendars" / "delta_economic_events.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Refresh Delta economic event blackout calendar cache"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_CACHE,
        help=f"JSON cache path (default: {DEFAULT_CACHE})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch/parse only; do not write the cache file",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Debug logging",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    ok, count, err = refresh_economic_calendar_cache(
        str(args.output),
        dry_run=bool(args.dry_run),
    )
    if not ok:
        print(f"[WARN] calendar refresh failed: {err}", file=sys.stderr)
        return 1
    print(f"[OK] economic calendar events={count} path={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
