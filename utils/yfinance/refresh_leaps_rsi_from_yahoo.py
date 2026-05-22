#!/usr/bin/env python3
"""
Refresh ``logs/LEAPS_RSI/LEAPS_RSI_rsi_history.log`` from Yahoo ^NSEI 60m RSI(14).

- Replaces non-``live_append`` rows for timestamps covered by Yahoo data.
- Preserves every existing ``live_append`` row unchanged.
- Keeps older non-live rows (e.g. early ``historical_seed``) before the Yahoo window.

Usage (from repo root, with venv + yfinance + TA-Lib)::

    python3 utils/yfinance/refresh_leaps_rsi_from_yahoo.py
    python3 utils/yfinance/refresh_leaps_rsi_from_yahoo.py --period 60d --dry-run

    cd /root/Dhan-codebase
source .venv/bin/activate
pip install yfinance pandas numpy TA-Lib   # if missing

# Preview merge counts (does not write)
python3 utils/refresh_leaps_rsi_from_yahoo.py --dry-run

# Write the file
python3 utils/refresh_leaps_rsi_from_yahoo.py



python3 utils/refresh_leaps_rsi_from_yahoo.py --period 60d --hist-path logs/LEAPS_RSI/LEAPS_RSI_rsi_history.log
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

# Allow running as ``python3 utils/yfinance/refresh_leaps_rsi_from_yahoo.py``
_YFINANCE_UTILS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_YFINANCE_UTILS_DIR))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from utils.yfinance.yfinance_nifty_rsi import fetch_nifty_hourly_with_rsi  # noqa: E402

LIVE_SOURCE = "live_append"
REFRESH_SOURCE = "yahoo_refresh"
NSE_BAR_MINUTES = {(9, 15), (10, 15), (11, 15), (12, 15), (13, 15), (14, 15), (15, 15)}


def _normalize_ist_key(ts: str) -> str:
    s = str(ts or "").strip()
    if "T" in s:
        s = s.replace("T", " ")[:16]
    return s[:16] if len(s) >= 16 else s


def _float_or_none(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, 2)


def _load_history(path: str) -> Tuple[Dict[str, dict], List[dict]]:
    """Return (live_append by ist key, all other rows in file order)."""
    live: Dict[str, dict] = {}
    other: List[dict] = []
    if not os.path.isfile(path):
        return live, other
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = _normalize_ist_key(row.get("candle_timestamp_ist"))
            if not key:
                continue
            if str(row.get("source") or "") == LIVE_SOURCE:
                live[key] = row
            else:
                other.append(row)
    return live, other


def _is_nse_hourly_bar(dt_ist: pd.Timestamp) -> bool:
    if dt_ist.weekday() >= 5:
        return False
    return (int(dt_ist.hour), int(dt_ist.minute)) in NSE_BAR_MINUTES


def _yahoo_rows(
    *,
    period: str,
    symbol: str,
    timeframe: str,
    rsi_period: int,
) -> Dict[str, dict]:
    df = fetch_nifty_hourly_with_rsi(
        symbol=symbol,
        period=period,
        tail=None,
        rsi_period=rsi_period,
    )
    out: Dict[str, dict] = {}
    if df is None or df.empty:
        return out

    for _, row in df.iterrows():
        dt = row.get("Datetime_IST")
        if dt is None or (isinstance(dt, float) and pd.isna(dt)):
            continue
        dt_ist = pd.Timestamp(dt)
        if dt_ist.tzinfo is None:
            dt_ist = dt_ist.tz_localize("Asia/Kolkata")
        else:
            dt_ist = dt_ist.tz_convert("Asia/Kolkata")
        if not _is_nse_hourly_bar(dt_ist):
            continue
        key = dt_ist.strftime("%Y-%m-%d %H:%M")
        rsi = _float_or_none(row.get("RSI_14"))
        if rsi is None:
            continue
        prev = _float_or_none(row.get("PREV_RSI"))
        close = _float_or_none(row.get("Close"))
        if close is None:
            continue
        out[key] = {
            "symbol": "NIFTY",
            "timeframe": timeframe,
            "source": REFRESH_SOURCE,
            "candle_timestamp_ist": key,
            "close": close,
            "rsi": rsi,
            "prev_rsi": prev,
        }
    return out


def merge_history(
    live: Dict[str, dict],
    other: List[dict],
    yahoo: Dict[str, dict],
) -> List[dict]:
    if not yahoo:
        return sorted(
            list(live.values()) + other,
            key=lambda r: _normalize_ist_key(r.get("candle_timestamp_ist", "")),
        )

    yahoo_min = min(yahoo.keys())
    preserved: List[dict] = []
    for row in other:
        key = _normalize_ist_key(row.get("candle_timestamp_ist"))
        if key < yahoo_min:
            preserved.append(row)

    merged: Dict[str, dict] = {}
    for row in preserved:
        key = _normalize_ist_key(row.get("candle_timestamp_ist"))
        merged[key] = row
    for key, row in yahoo.items():
        if key in live:
            continue
        merged[key] = row
    for key, row in live.items():
        merged[key] = row

    return [merged[k] for k in sorted(merged.keys())]


def refresh_rsi_history_file(
    hist_path: str,
    *,
    period: str = "60d",
    symbol: str = "^NSEI",
    timeframe: str = "60",
    rsi_period: int = 14,
    dry_run: bool = False,
) -> dict:
    live, other = _load_history(hist_path)
    yahoo = _yahoo_rows(
        period=period,
        symbol=symbol,
        timeframe=timeframe,
        rsi_period=rsi_period,
    )
    if not yahoo:
        raise SystemExit(
            "Yahoo Finance returned no NSE hourly bars after filtering. "
            "Check: (1) network/DNS to query1.finance.yahoo.com, "
            "(2) pip install -U yfinance, "
            "(3) python3 utils/yfinance/yfinance_nifty_rsi.py shows rows, "
            "(4) --period long enough (e.g. 60d). File was not modified."
        )

    merged = merge_history(live, other, yahoo)
    yahoo_min = min(yahoo.keys())
    preserved_before = sum(
        1
        for r in other
        if _normalize_ist_key(r.get("candle_timestamp_ist")) < yahoo_min
    )

    stats = {
        "path": hist_path,
        "live_kept": len(live),
        "yahoo_bars": len(yahoo),
        "preserved_before_yahoo": preserved_before,
        "yahoo_from": yahoo_min,
        "yahoo_to": max(yahoo.keys()),
        "total_out": len(merged),
        "dry_run": dry_run,
    }

    if not dry_run:
        os.makedirs(os.path.dirname(hist_path), exist_ok=True)
        with open(hist_path, "w", encoding="utf-8") as f:
            for row in merged:
                f.write(json.dumps(row, default=str) + "\n")

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh LEAPS_RSI_rsi_history.log from Yahoo ^NSEI (keeps live_append rows)."
    )
    parser.add_argument(
        "--hist-path",
        default=os.path.join(_REPO_ROOT, "logs", "LEAPS_RSI", "LEAPS_RSI_rsi_history.log"),
        help="Path to LEAPS_RSI_rsi_history.log",
    )
    parser.add_argument(
        "--period",
        default="60d",
        help="yfinance history period (e.g. 30d, 60d, 730d)",
    )
    parser.add_argument("--symbol", default="^NSEI", help="Yahoo ticker")
    parser.add_argument("--timeframe", default="60", help="Logged timeframe label")
    parser.add_argument("--rsi-period", type=int, default=14)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute merge stats without writing the file",
    )
    args = parser.parse_args()

    hist_path = os.path.abspath(args.hist_path)
    stats = refresh_rsi_history_file(
        hist_path,
        period=args.period,
        symbol=args.symbol,
        timeframe=args.timeframe,
        rsi_period=args.rsi_period,
        dry_run=args.dry_run,
    )
    print(
        f"{'[dry-run] ' if stats['dry_run'] else ''}"
        f"live_append kept={stats['live_kept']} | "
        f"yahoo_refresh bars={stats['yahoo_bars']} "
        f"({stats['yahoo_from']} .. {stats['yahoo_to']}) | "
        f"preserved pre-yahoo={stats['preserved_before_yahoo']} | "
        f"total lines={stats['total_out']} -> {stats['path']}"
    )


if __name__ == "__main__":
    main()
