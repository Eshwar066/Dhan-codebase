#!/usr/bin/env python3
"""
Refresh shared crypto indicator history from Delta Exchange REST.

Default outputs (schema v2 JSONL, preserves ``live_append`` rows)::

    logs/indicators/BTCUSD/1/indicator_history.jsonl  — 1m market structure (RSIBreadAndButter entry TF)
    logs/indicators/BTCUSD/5/indicator_history.jsonl  — 5m market structure (signal TF)
    logs/indicators/BTCUSD/60/indicator_history.jsonl — 1h SuperTrend (DirectionalOptionSelling)

Usage (from repo root)::

    python utils/delta/refresh_crypto_indicator_history.py
    python utils/delta/refresh_crypto_indicator_history.py --dry-run
    python utils/delta/refresh_crypto_indicator_history.py --only 1 --days 14
    python utils/delta/refresh_crypto_indicator_history.py --symbol BTCUSD --only 5
    python utils/delta/refresh_crypto_indicator_history.py --symbol BTCUSD --only 60
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

_DELTA_UTILS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_DELTA_UTILS_DIR))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.data.sources.delta_source import DeltaSource  # noqa: E402
from core.strategies.crypto.RSIBreadAndButter.RSIBreadAndButter import (  # noqa: E402
    RSIBreadAndButter,
)
from core.strategies.crypto.DirectionalOptionSelling.DirectionalOptionSelling import (  # noqa: E402
    DirectionalOptionSelling,
)
from core.utils.indicator_history import (  # noqa: E402
    SCHEMA_VERSION,
    indicator_history_path,
    maybe_trim_indicator_history_file,
    normalize_ist_bar_key,
)
from core.data.candle_aggregator import _resolution_to_seconds  # noqa: E402
from core.utils.json_numeric import round_json_floats  # noqa: E402

LIVE_SOURCE = "live_append"
REFRESH_SOURCE = "delta_refresh"
IST = __import__("zoneinfo").ZoneInfo("Asia/Kolkata")


def _float_or_none(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, 6)


def _load_history(path: str) -> Tuple[Dict[str, dict], List[dict]]:
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
            key = normalize_ist_bar_key(row.get("candle_timestamp_ist"))
            if not key:
                continue
            if str(row.get("source") or "") == LIVE_SOURCE:
                live[key] = row
            else:
                other.append(row)
    return live, other


def _build_schema_row(
    *,
    symbol: str,
    timeframe: str,
    ts_utc: pd.Timestamp,
    o: float,
    h: float,
    l: float,
    c: float,
    volume: float,
    indicators: Dict[str, Any],
) -> dict:
    dt_ist = ts_utc.tz_convert(IST)
    ist_key = dt_ist.strftime("%Y-%m-%d %H:%M")
    ind_out: Dict[str, Any] = {}
    for k, v in indicators.items():
        fv = _float_or_none(v)
        if fv is not None:
            ind_out[k] = fv
        elif v is not None and not isinstance(v, float):
            ind_out[k] = v
    return {
        "schema": SCHEMA_VERSION,
        "symbol": str(symbol).upper(),
        "timeframe": str(timeframe),
        "source": REFRESH_SOURCE,
        "candle_timestamp_ist": ist_key,
        "ohlc": {
            "open": _float_or_none(o),
            "high": _float_or_none(h),
            "low": _float_or_none(l),
            "close": _float_or_none(c),
        },
        "volume": _float_or_none(volume) or 0.0,
        "indicators": ind_out,
    }


def _merge_history(
    live: Dict[str, dict],
    other: List[dict],
    refreshed: Dict[str, dict],
) -> List[dict]:
    if not refreshed:
        return sorted(
            list(live.values()) + other,
            key=lambda r: normalize_ist_bar_key(r.get("candle_timestamp_ist", "")),
        )
    refresh_min = min(refreshed.keys())
    preserved: List[dict] = []
    for row in other:
        key = normalize_ist_bar_key(row.get("candle_timestamp_ist"))
        # Refreshed REST bars are authoritative through the latest closed candle.
        # Drop non-live rows after that point: they can be startup snapshots of the
        # currently forming bar (for example, a one-tick OHLC row).
        if key < refresh_min:
            preserved.append(row)
    merged: Dict[str, dict] = {}
    for row in preserved:
        merged[normalize_ist_bar_key(row.get("candle_timestamp_ist"))] = row
    for key, row in refreshed.items():
        if key in live:
            continue
        merged[key] = row
    for key, row in live.items():
        merged[key] = row
    return [merged[k] for k in sorted(merged.keys())]


def _trim_forming_tail(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Drop the current open (forming) bar so refresh ends at last closed candle."""
    if df is None or df.empty or "timestamp" not in df.columns:
        return df
    tf_sec = max(60, int(_resolution_to_seconds(timeframe)))
    now_bucket = int(time.time()) - (int(time.time()) % tf_sec)
    tss = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    keep = []
    for ts in tss:
        if pd.isna(ts):
            keep.append(False)
            continue
        try:
            keep.append(int(ts.timestamp()) < now_bucket)
        except (OSError, OverflowError, ValueError):
            keep.append(False)
    return df.loc[keep].reset_index(drop=True)


def _fetch_delta_ohlc(
    source: DeltaSource,
    symbol: str,
    timeframe: str,
    days: int,
    *,
    ignore_cache: bool = False,
    force_refresh_tail: bool = True,
) -> pd.DataFrame:
    end_d = date.today()
    start_d = end_d - timedelta(days=max(3, int(days)))
    df = source.get_intraday(
        symbol=symbol,
        start_date=start_d.strftime("%Y-%m-%d"),
        end_date=end_d.strftime("%Y-%m-%d"),
        timeframe=timeframe,
        ignore_cache=ignore_cache,
        force_refresh_tail=force_refresh_tail,
    )
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
    out = out.dropna(subset=["timestamp"]).sort_values("timestamp")
    out = out.drop_duplicates(subset=["timestamp"], keep="last").reset_index(drop=True)
    out = _trim_forming_tail(out, timeframe)
    return out


def _rows_from_df(
    df: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    strategy: Any,
    min_rows: int,
) -> Dict[str, dict]:
    if df is None or df.empty:
        return {}
    enriched = strategy.prepare_indicators(df.copy())
    keys = strategy.persisted_indicator_keys()
    out: Dict[str, dict] = {}
    for _, row in enriched.iterrows():
        ts = row.get("timestamp")
        if ts is None or (isinstance(ts, float) and pd.isna(ts)):
            continue
        ts_utc = pd.Timestamp(ts)
        if ts_utc.tzinfo is None:
            ts_utc = ts_utc.tz_localize("UTC")
        else:
            ts_utc = ts_utc.tz_convert("UTC")
        ist_key = ts_utc.tz_convert(IST).strftime("%Y-%m-%d %H:%M")
        indicators = {k: row.get(k) for k in keys if k in row.index}
        if not indicators:
            continue
        out[ist_key] = _build_schema_row(
            symbol=symbol,
            timeframe=timeframe,
            ts_utc=ts_utc,
            o=float(row.get("open", row.get("close", 0)) or 0),
            h=float(row.get("high", row.get("close", 0)) or 0),
            l=float(row.get("low", row.get("close", 0)) or 0),
            c=float(row.get("close", 0) or 0),
            volume=float(row.get("volume", 0) or 0),
            indicators=indicators,
        )
    if len(out) < min_rows:
        return {}
    return out


def refresh_file(
    *,
    hist_path: str,
    symbol: str,
    timeframe: str,
    source: DeltaSource,
    strategy: Any,
    days: int,
    min_rows: int,
    dry_run: bool,
    ignore_cache: bool = False,
) -> dict:
    live, other = _load_history(hist_path)
    df = _fetch_delta_ohlc(
        source,
        symbol,
        timeframe,
        days,
        ignore_cache=ignore_cache,
        force_refresh_tail=True,
    )
    refreshed = _rows_from_df(
        df,
        symbol=symbol,
        timeframe=timeframe,
        strategy=strategy,
        min_rows=min_rows,
    )
    merged = _merge_history(live, other, refreshed)
    stats = {
        "path": hist_path,
        "symbol": symbol,
        "timeframe": timeframe,
        "fetched_bars": len(df),
        "refreshed_rows": len(refreshed),
        "live_preserved": len(live),
        "total_out": len(merged),
        "dry_run": dry_run,
        "ignore_cache": ignore_cache,
    }
    if df is not None and len(df) > 0:
        last_ts = pd.to_datetime(df["timestamp"].iloc[-1], utc=True)
        stats["last_bar_ist"] = last_ts.tz_convert(IST).strftime("%Y-%m-%d %H:%M")
    if not refreshed:
        stats["error"] = "insufficient_rows_after_indicators"
        return stats
    if not dry_run:
        os.makedirs(os.path.dirname(hist_path), exist_ok=True)
        with open(hist_path, "w", encoding="utf-8") as f:
            for row in merged:
                f.write(json.dumps(round_json_floats(row), default=str) + "\n")
        maybe_trim_indicator_history_file(hist_path)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh logs/indicators/{SYMBOL}/{tf}/indicator_history.jsonl from Delta REST."
    )
    parser.add_argument(
        "--log-root",
        default=os.path.join(_REPO_ROOT, "logs"),
        help="Logs root (default: repo logs/)",
    )
    parser.add_argument("--symbol", default="BTCUSD", help="Delta symbol (default: BTCUSD)")
    parser.add_argument(
        "--only",
        choices=("1", "5", "60"),
        default=None,
        help="Refresh only 1m, 5m, or 60m file (default: 1m and 5m)",
    )
    parser.add_argument("--days", type=int, default=30, help="Calendar days of history to fetch")
    parser.add_argument(
        "--min-rows",
        type=int,
        default=350,
        help="Minimum indicator rows required to write file",
    )
    parser.add_argument("--india", action="store_true", default=True, help="Delta India API")
    parser.add_argument("--global", dest="global_api", action="store_true", help="Delta global API")
    parser.add_argument("--testnet", action="store_true", help="Delta testnet")
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignore Delta intraday file cache (full REST refetch)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Compute stats without writing")
    args = parser.parse_args()

    log_root = os.path.abspath(args.log_root)
    symbol = str(args.symbol).strip().upper()
    modes = ["1", "5"] if not args.only else [args.only.strip()]
    india = not args.global_api
    delta = DeltaSource(testnet=bool(args.testnet), india=india, symbols=[symbol])
    strategies = {
        "1": RSIBreadAndButter(),
        "5": RSIBreadAndButter(),
        "60": DirectionalOptionSelling(),
    }

    all_stats: List[dict] = []
    for tf in modes:
        path = indicator_history_path(symbol, tf, log_root=log_root)
        stats = refresh_file(
            hist_path=path,
            symbol=symbol,
            timeframe=tf,
            source=delta,
            strategy=strategies[tf],
            days=args.days,
            min_rows=args.min_rows,
            dry_run=bool(args.dry_run),
            ignore_cache=bool(args.no_cache),
        )
        all_stats.append(stats)
        print(json.dumps(stats, indent=2))
        if stats.get("error"):
            raise SystemExit(
                f"Refresh failed for {symbol}/{tf}: {stats['error']} "
                f"(fetched={stats.get('fetched_bars')}, refreshed={stats.get('refreshed_rows')})"
            )


if __name__ == "__main__":
    main()
