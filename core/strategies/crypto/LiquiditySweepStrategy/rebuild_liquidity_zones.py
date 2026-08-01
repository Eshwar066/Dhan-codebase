#!/usr/bin/env python3
"""
Rebuild LiquiditySweep 4H liquidity zones from indicator history and write the
shared reference files used by live:

  logs/LiquiditySweepStrategy/liquidity_zones.jsonl
  logs/LiquiditySweepStrategy/liquidity_zones_active.json

Usage:
  python -m core.strategies.crypto.LiquiditySweepStrategy.rebuild_liquidity_zones
  python -m core.strategies.crypto.LiquiditySweepStrategy.rebuild_liquidity_zones --symbols BTCUSD
"""

from __future__ import annotations

import argparse
import logging
import sys

from core.strategies.crypto.LiquiditySweepStrategy.four_hour_liquidity import (
    DEFAULT_ZONES_ACTIVE,
    DEFAULT_ZONES_JSONL,
    FourHourLiquidityBook,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("rebuild_liquidity_zones")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--symbols",
        nargs="+",
        default=["BTCUSD"],
        help="Symbols to rebuild (default: BTCUSD)",
    )
    p.add_argument(
        "--keep-log",
        action="store_true",
        help="Append to existing jsonl instead of clearing first",
    )
    args = p.parse_args(argv)

    book = FourHourLiquidityBook(persist=True)
    counts = book.rebuild_from_indicator_history(
        list(args.symbols),
        clear_log=not args.keep_log,
        source="backtest_rebuild",
    )
    logger.info(
        "Wrote zone log=%s active=%s counts=%s",
        DEFAULT_ZONES_JSONL,
        DEFAULT_ZONES_ACTIVE,
        counts,
    )
    for sym, n in counts.items():
        snap = book.snapshot(sym)
        print(
            f"{sym}: 4h_bars={n} active_highs={snap['highs']} active_lows={snap['lows']}"
        )
    print(f"jsonl={DEFAULT_ZONES_JSONL}")
    print(f"active={DEFAULT_ZONES_ACTIVE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
