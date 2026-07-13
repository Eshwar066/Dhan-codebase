#!/usr/bin/env python3
"""
Refresh shared NIFTY ``logs/indicators/{SYMBOL}/{tf}/`` history from Yahoo ^NSEI.

Used by LEAPS RSI, NiftySMA9Weekly, and any strategy that bootstraps from the
shared indicator JSONL (preserves ``live_append`` rows).

Default outputs (schema v2 JSONL)::

    logs/indicators/NIFTY/60/indicator_history.jsonl   — RSI(14) + EMA8 high/low on 60m bars
    logs/indicators/NIFTY/15/indicator_history.jsonl   — Bollinger(20,2) on 15m bars
    logs/indicators/NIFTY/120/indicator_history.jsonl  — SMA(9) on 120m bars

Backfill EMA on an existing 60m file (uses OHLC already in the file)::

    python3 utils/yfinance/refresh_nifty_indicator_history.py --backfill-ema --only 60

Legacy ``logs/LEAPS_RSI/LEAPS_RSI_rsi_history.log`` is no longer written; migrate with
``--also-legacy-60`` if you still need the old file.

Usage (from repo root, with venv + yfinance + TA-Lib)::

    python3 utils/yfinance/refresh_nifty_indicator_history.py
    python3 utils/yfinance/refresh_nifty_indicator_history.py --period 60d --dry-run
    python3 utils/yfinance/refresh_nifty_indicator_history.py --only 60
    python3 utils/yfinance/refresh_nifty_indicator_history.py --only 15
    python3 utils/yfinance/refresh_nifty_indicator_history.py --only 120

cd /root/Dhan-codebase
source .venv/bin/activate

# Preview
python3 utils/yfinance/refresh_nifty_indicator_history.py --dry-run --period 60d

# Write both 60m + 15m indicator history files
python3 utils/yfinance/refresh_nifty_indicator_history.py --period 60d

# Only one timeframe
python3 utils/yfinance/refresh_nifty_indicator_history.py --only 60 --period 60d
python3 utils/yfinance/refresh_nifty_indicator_history.py --only 15 --period 60d
python3 utils/yfinance/refresh_nifty_indicator_history.py --only 120 --period 60d

# Optional legacy flat RSI log (backward compat)
python3 utils/yfinance/refresh_nifty_indicator_history.py --period 60d --also-legacy-60
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

_YFINANCE_UTILS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_YFINANCE_UTILS_DIR))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.strategies.indicator_helpers import add_ema_high_low  # noqa: E402
from core.utils.indicator_history import (  # noqa: E402
    SCHEMA_VERSION,
    indicator_history_path,
    is_nse_60m_bar_ist,
    legacy_rsi_history_path,
)
from utils.yfinance.nifty_yahoo import (  # noqa: E402
    fetch_nifty_120m_with_sma,
    fetch_nifty_15m_with_bollinger,
    fetch_nifty_hourly_with_rsi,
)

LIVE_SOURCE = "live_append"
REFRESH_SOURCE = "yahoo_refresh"


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


def _row_to_schema_v2(row: dict) -> dict:
    """Normalize legacy flat or schema-2 row to schema v2."""
    if int(row.get("schema") or 0) == SCHEMA_VERSION and isinstance(
        row.get("indicators"), dict
    ):
        out = dict(row)
        out["schema"] = SCHEMA_VERSION
        return out

    indicators: Dict[str, Any] = {}
    if isinstance(row.get("indicators"), dict):
        indicators.update(row["indicators"])
    for key in (
        "rsi",
        "prev_rsi",
        "ema_high",
        "ema_low",
        "bb_upper",
        "bb_mid",
        "bb_lower",
        "sma",
        "prev_sma",
        "sma9",
        "prev_sma9",
        "prev_close",
    ):
        if key in row and row[key] is not None:
            indicators[key] = row[key]

    ohlc = row.get("ohlc") if isinstance(row.get("ohlc"), dict) else {}
    close = _float_or_none(ohlc.get("close") if ohlc else row.get("close"))
    return {
        "schema": SCHEMA_VERSION,
        "symbol": str(row.get("symbol") or "NIFTY").upper(),
        "timeframe": str(row.get("timeframe") or ""),
        "source": str(row.get("source") or ""),
        "candle_timestamp_ist": _normalize_ist_key(row.get("candle_timestamp_ist")),
        "ohlc": {
            "open": _float_or_none(ohlc.get("open") if ohlc else row.get("open")) or close,
            "high": _float_or_none(ohlc.get("high") if ohlc else row.get("high")) or close,
            "low": _float_or_none(ohlc.get("low") if ohlc else row.get("low")) or close,
            "close": close,
        },
        "indicators": indicators,
    }


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
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            row = _row_to_schema_v2(raw)
            key = _normalize_ist_key(row.get("candle_timestamp_ist"))
            if not key:
                continue
            if str(row.get("source") or "") == LIVE_SOURCE:
                live[key] = row
            else:
                other.append(row)
    return live, other


def _is_nse_60m_bar(dt_ist: pd.Timestamp) -> bool:
    if hasattr(dt_ist, "to_pydatetime"):
        dt_ist = dt_ist.to_pydatetime()
    if dt_ist.tzinfo is None:
        dt_ist = dt_ist.replace(tzinfo=__import__("zoneinfo").ZoneInfo("Asia/Kolkata"))
    return is_nse_60m_bar_ist(dt_ist)


def _is_nse_15m_bar(dt_ist: pd.Timestamp) -> bool:
    if dt_ist.weekday() >= 5:
        return False
    h, m = int(dt_ist.hour), int(dt_ist.minute)
    if h < 9 or h > 15:
        return False
    if h == 9 and m < 15:
        return False
    if h == 15 and m > 30:
        return False
    return m in (0, 15, 30, 45)


def _display_symbol(symbol: str) -> str:
    s = str(symbol or "NIFTY").strip().upper()
    if s in ("^NSEI", "NSEI"):
        return "NIFTY"
    return s


def _build_schema_row(
    *,
    symbol: str,
    timeframe: str,
    ist_key: str,
    o: Optional[float],
    h: Optional[float],
    l: Optional[float],
    c: Optional[float],
    indicators: Dict[str, Any],
    source: str = REFRESH_SOURCE,
) -> dict:
    close = c if c is not None else o
    return {
        "schema": SCHEMA_VERSION,
        "symbol": _display_symbol(symbol),
        "timeframe": timeframe,
        "source": source,
        "candle_timestamp_ist": ist_key,
        "ohlc": {
            "open": o if o is not None else close,
            "high": h if h is not None else close,
            "low": l if l is not None else close,
            "close": close,
        },
        "indicators": {k: v for k, v in indicators.items() if v is not None},
    }


def _ohlc_from_row(row: Any, field: str) -> Optional[float]:
    """Read OHLC from a row that may use ``Open``/``Close`` or ``open``/``close``."""
    key = str(field or "").strip().lower()
    if not key:
        return None
    titled = key.capitalize()
    for col in (key, titled, key.upper()):
        val = _float_or_none(row.get(col) if hasattr(row, "get") else None)
        if val is not None:
            return val
    return None


def _yahoo_rows_60(
    *,
    period: str,
    symbol: str,
    timeframe: str,
    rsi_period: int,
    ema_period: int = 8,
) -> Tuple[Dict[str, dict], Dict[str, int]]:
    df = fetch_nifty_hourly_with_rsi(
        symbol=symbol,
        period=period,
        tail=None,
        rsi_period=rsi_period,
    )
    out: Dict[str, dict] = {}
    stats = {"fetched": 0, "skipped_nse_time": 0, "skipped_rsi": 0, "skipped_close": 0}
    if df is None or df.empty:
        return out, stats

    work = df.rename(
        columns={"Open": "open", "High": "high", "Low": "low", "Close": "close"}
    )
    work = add_ema_high_low(work, period=ema_period)
    stats["fetched"] = len(work)

    for _, row in work.iterrows():
        dt = row.get("Datetime_IST")
        if dt is None or (isinstance(dt, float) and pd.isna(dt)):
            continue
        dt_ist = pd.Timestamp(dt)
        if dt_ist.tzinfo is None:
            dt_ist = dt_ist.tz_localize("Asia/Kolkata")
        else:
            dt_ist = dt_ist.tz_convert("Asia/Kolkata")
        if not _is_nse_60m_bar(dt_ist):
            stats["skipped_nse_time"] += 1
            continue
        key = dt_ist.strftime("%Y-%m-%d %H:%M")
        rsi = _float_or_none(row.get("RSI_14"))
        if rsi is None:
            stats["skipped_rsi"] += 1
            continue
        prev = _float_or_none(row.get("PREV_RSI"))
        close = _ohlc_from_row(row, "close")
        if close is None:
            stats["skipped_close"] += 1
            continue
        indicators: Dict[str, Any] = {"rsi": rsi, "prev_rsi": prev}
        ema_h = _float_or_none(row.get("ema_high"))
        ema_l = _float_or_none(row.get("ema_low"))
        if ema_h is not None:
            indicators["ema_high"] = ema_h
        if ema_l is not None:
            indicators["ema_low"] = ema_l
        out[key] = _build_schema_row(
            symbol=symbol,
            timeframe=timeframe,
            ist_key=key,
            o=_ohlc_from_row(row, "open"),
            h=_ohlc_from_row(row, "high"),
            l=_ohlc_from_row(row, "low"),
            c=close,
            indicators=indicators,
        )
    return out, stats


def _yahoo_rows_120(
    *,
    period: str,
    symbol: str,
    timeframe: str = "120",
    sma_period: int = 9,
) -> Tuple[Dict[str, dict], Dict[str, int]]:
    """Yahoo 60m → NSE 120m + SMA for NiftySMA9Weekly."""
    df = fetch_nifty_120m_with_sma(
        symbol=symbol,
        period=period,
        tail=None,
        sma_period=sma_period,
    )
    out: Dict[str, dict] = {}
    stats = {
        "fetched": 0,
        "skipped_sma": 0,
        "skipped_close": 0,
    }
    if df is None or df.empty:
        return out, stats

    stats["fetched"] = len(df)
    for _, row in df.iterrows():
        dt = row.get("Datetime_IST")
        if dt is None or (isinstance(dt, float) and pd.isna(dt)):
            continue
        dt_ist = pd.Timestamp(dt)
        if dt_ist.tzinfo is None:
            dt_ist = dt_ist.tz_localize("Asia/Kolkata")
        else:
            dt_ist = dt_ist.tz_convert("Asia/Kolkata")
        key = dt_ist.strftime("%Y-%m-%d %H:%M")
        sma_col = f"sma{int(sma_period)}"
        prev_sma_col = f"prev_sma{int(sma_period)}"
        sma = _float_or_none(row.get(sma_col))
        if sma is None:
            stats["skipped_sma"] += 1
            continue
        close = _ohlc_from_row(row, "close")
        if close is None:
            stats["skipped_close"] += 1
            continue
        indicators: Dict[str, Any] = {
            sma_col: sma,
            prev_sma_col: _float_or_none(row.get(prev_sma_col)),
            "prev_close": _float_or_none(row.get("prev_close")),
        }
        out[key] = _build_schema_row(
            symbol=symbol,
            timeframe=timeframe,
            ist_key=key,
            o=_ohlc_from_row(row, "open"),
            h=_ohlc_from_row(row, "high"),
            l=_ohlc_from_row(row, "low"),
            c=close,
            indicators=indicators,
        )
    return out, stats


def backfill_ema_on_indicator_history(
    hist_path: str,
    *,
    ema_period: int = 8,
    dry_run: bool = False,
) -> dict:
    """
    Add ``ema_high`` / ``ema_low`` to each row using OHLC already stored in the JSONL file.
    Preserves existing ``rsi`` / ``prev_rsi`` and other indicator keys.
    """
    if not os.path.isfile(hist_path):
        raise SystemExit(f"File not found: {hist_path}")

    parsed: List[dict] = []
    with open(hist_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                parsed.append(_row_to_schema_v2(json.loads(line)))
            except json.JSONDecodeError:
                continue

    if not parsed:
        return {"path": hist_path, "rows": 0, "ema_filled": 0, "dry_run": dry_run}

    records: List[dict] = []
    for row in parsed:
        ohlc = row.get("ohlc") if isinstance(row.get("ohlc"), dict) else {}
        ist_key = _normalize_ist_key(row.get("candle_timestamp_ist"))
        records.append(
            {
                "ist_key": ist_key,
                "open": _float_or_none(ohlc.get("open")),
                "high": _float_or_none(ohlc.get("high")),
                "low": _float_or_none(ohlc.get("low")),
                "close": _float_or_none(ohlc.get("close")),
            }
        )

    df = pd.DataFrame(records)
    df = df[df["ist_key"].astype(str).str.len() > 0].sort_values("ist_key")
    df = add_ema_high_low(df, period=ema_period)
    ema_by_key: Dict[str, Tuple[Optional[float], Optional[float]]] = {}
    for _, r in df.iterrows():
        ema_by_key[str(r["ist_key"])] = (
            _float_or_none(r.get("ema_high")),
            _float_or_none(r.get("ema_low")),
        )

    filled = 0
    for row in parsed:
        key = _normalize_ist_key(row.get("candle_timestamp_ist"))
        pair = ema_by_key.get(key)
        if not pair:
            continue
        ind = dict(row.get("indicators") or {})
        eh, el = pair
        if eh is not None:
            ind["ema_high"] = eh
        if el is not None:
            ind["ema_low"] = el
        if eh is not None or el is not None:
            filled += 1
        row["indicators"] = ind
        row["symbol"] = _display_symbol(row.get("symbol") or "NIFTY")

    stats = {
        "path": hist_path,
        "mode": "backfill_ema",
        "rows": len(parsed),
        "ema_filled": filled,
        "ema_period": ema_period,
        "dry_run": dry_run,
    }

    if not dry_run:
        os.makedirs(os.path.dirname(hist_path), exist_ok=True)
        with open(hist_path, "w", encoding="utf-8") as f:
            for row in sorted(
                parsed, key=lambda r: _normalize_ist_key(r.get("candle_timestamp_ist"))
            ):
                f.write(json.dumps(row, default=str) + "\n")

    return stats


def _yahoo_rows_15(
    *,
    period: str,
    symbol: str,
    timeframe: str,
    bb_period: int,
    bb_std: float,
) -> Dict[str, dict]:
    df = fetch_nifty_15m_with_bollinger(
        symbol=symbol,
        period=period,
        tail=None,
        bb_period=bb_period,
        bb_std=bb_std,
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
        if not _is_nse_15m_bar(dt_ist):
            continue
        key = dt_ist.strftime("%Y-%m-%d %H:%M")
        close = _float_or_none(row.get("Close"))
        if close is None:
            continue
        bb_u = _float_or_none(row.get("bb_upper"))
        bb_m = _float_or_none(row.get("bb_mid"))
        bb_l = _float_or_none(row.get("bb_lower"))
        if bb_u is None and bb_m is None and bb_l is None:
            continue
        out[key] = _build_schema_row(
            symbol=symbol,
            timeframe=timeframe,
            ist_key=key,
            o=_float_or_none(row.get("Open")),
            h=_float_or_none(row.get("High")),
            l=_float_or_none(row.get("Low")),
            c=close,
            indicators={
                "bb_upper": bb_u,
                "bb_mid": bb_m,
                "bb_lower": bb_l,
            },
        )
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


def refresh_indicator_history_file(
    hist_path: str,
    *,
    mode: str,
    period: str = "60d",
    symbol: str = "NIFTY",
    timeframe: str = "60",
    rsi_period: int = 14,
    ema_period: int = 8,
    bb_period: int = 20,
    bb_std: float = 2.0,
    sma_period: int = 9,
    dry_run: bool = False,
) -> dict:
    live, other = _load_history(hist_path)
    yahoo_stats: Dict[str, int] = {}
    if mode == "15":
        yahoo = _yahoo_rows_15(
            period=period,
            symbol="^NSEI" if symbol.upper() == "NIFTY" else symbol,
            timeframe=timeframe,
            bb_period=bb_period,
            bb_std=bb_std,
        )
        label = "bollinger"
    elif mode == "120":
        yahoo, yahoo_stats = _yahoo_rows_120(
            period=period,
            symbol="^NSEI" if symbol.upper() in ("NIFTY", "^NSEI") else symbol,
            timeframe=timeframe,
            sma_period=sma_period,
        )
        label = "sma9"
    else:
        yahoo, yahoo_stats = _yahoo_rows_60(
            period=period,
            symbol="^NSEI" if symbol.upper() in ("NIFTY", "^NSEI") else symbol,
            timeframe=timeframe,
            rsi_period=rsi_period,
            ema_period=ema_period,
        )
        label = "rsi"

    if not yahoo:
        if mode == "60" and yahoo_stats.get("fetched", 0) == 0:
            raise SystemExit(
                "Yahoo Finance returned no hourly OHLC data for ^NSEI "
                f"(period={period}). This is usually a network/blocking issue "
                "(DNS/ad-block on fc.yahoo.com) or transient Yahoo rate limits — "
                "not the NSE bar-time filter. "
                f"File was not modified: {hist_path}"
            )
        if mode == "60":
            raise SystemExit(
                "Yahoo hourly data was fetched but produced 0 NSE 60m indicator rows "
                f"(fetched={yahoo_stats.get('fetched', 0)} "
                f"skipped_nse_time={yahoo_stats.get('skipped_nse_time', 0)} "
                f"skipped_rsi={yahoo_stats.get('skipped_rsi', 0)} "
                f"skipped_close={yahoo_stats.get('skipped_close', 0)}). "
                f"File was not modified: {hist_path}"
            )
        if mode == "120" and yahoo_stats.get("fetched", 0) == 0:
            raise SystemExit(
                "Yahoo Finance returned no hourly OHLC to resample into 120m "
                f"(period={period}). File was not modified: {hist_path}"
            )
        if mode == "120":
            raise SystemExit(
                "Yahoo 60m→120m resample produced 0 SMA rows "
                f"(fetched={yahoo_stats.get('fetched', 0)} "
                f"skipped_sma={yahoo_stats.get('skipped_sma', 0)} "
                f"skipped_close={yahoo_stats.get('skipped_close', 0)}). "
                f"File was not modified: {hist_path}"
            )
        raise SystemExit(
            f"Yahoo Finance returned no NSE {timeframe}m bars for {label} after filtering. "
            "Check network, yfinance install, and --period (e.g. 60d). File was not modified: "
            f"{hist_path}"
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
        "mode": mode,
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


def _default_paths(log_root: str) -> Dict[str, str]:
    return {
        "60": indicator_history_path("NIFTY", "60", log_root=log_root),
        "15": indicator_history_path("NIFTY", "15", log_root=log_root),
        "120": indicator_history_path("NIFTY", "120", log_root=log_root),
    }


def refresh_all_default(
    *,
    log_root: str,
    period: str,
    only: Optional[str],
    dry_run: bool,
    also_legacy_60: bool,
    rsi_period: int,
    ema_period: int,
    bb_period: int,
    bb_std: float,
    sma_period: int = 9,
) -> List[dict]:
    paths = _default_paths(log_root)
    # Default still 60+15 (LEAPS / BB). Use --only 120 for SMA9 weekly.
    modes = ["60", "15"]
    if only:
        modes = [only.strip()]
    all_stats: List[dict] = []
    for mode in modes:
        path = paths.get(mode)
        if not path:
            raise SystemExit(f"Unknown --only value: {only!r} (use 60, 15, or 120)")
        stats = refresh_indicator_history_file(
            path,
            mode=mode,
            period=period,
            symbol="NIFTY",
            timeframe=mode,
            rsi_period=rsi_period,
            ema_period=ema_period,
            bb_period=bb_period,
            bb_std=bb_std,
            sma_period=sma_period,
            dry_run=dry_run,
        )
        all_stats.append(stats)

    if also_legacy_60 and not dry_run and "60" in modes:
        legacy = legacy_rsi_history_path("LEAPS_RSI", log_root=log_root)
        n = _write_legacy_rsi_from_v2(paths["60"], legacy)
        all_stats.append({"path": legacy, "mode": "legacy60", "total_out": n})

    return all_stats


def _write_legacy_rsi_from_v2(v2_path: str, legacy_path: str) -> int:
    """Mirror NIFTY/60 indicator_history.jsonl to flat LEAPS_RSI_rsi_history.log."""
    if not os.path.isfile(v2_path):
        return 0
    os.makedirs(os.path.dirname(legacy_path), exist_ok=True)
    count = 0
    with open(v2_path, encoding="utf-8") as fin, open(
        legacy_path, "w", encoding="utf-8"
    ) as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            row = _row_to_schema_v2(json.loads(line))
            ind = row.get("indicators") or {}
            ohlc = row.get("ohlc") or {}
            flat = {
                "symbol": row.get("symbol") or "NIFTY",
                "timeframe": row.get("timeframe") or "60",
                "source": row.get("source"),
                "candle_timestamp_ist": row.get("candle_timestamp_ist"),
                "close": ohlc.get("close"),
                "rsi": ind.get("rsi"),
                "prev_rsi": ind.get("prev_rsi"),
            }
            fout.write(json.dumps(flat, default=str) + "\n")
            count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh logs/indicators/NIFTY/{60,15,120}/indicator_history.jsonl from Yahoo ^NSEI "
            "(keeps live_append rows)."
        )
    )
    parser.add_argument(
        "--log-root",
        default=os.path.join(_REPO_ROOT, "logs"),
        help="Logs root (default: repo logs/)",
    )
    parser.add_argument(
        "--hist-path",
        default=None,
        help="Single file override (implies --only 60 unless --only set)",
    )
    parser.add_argument(
        "--only",
        choices=("60", "15", "120"),
        default=None,
        help="Refresh only NIFTY/60, NIFTY/15, or NIFTY/120 (default: 60+15)",
    )
    parser.add_argument(
        "--period",
        default="60d",
        help="yfinance history period (e.g. 30d, 60d, 730d)",
    )
    parser.add_argument("--symbol", default="^NSEI", help="Yahoo ticker")
    parser.add_argument("--rsi-period", type=int, default=14)
    parser.add_argument(
        "--ema-period",
        type=int,
        default=8,
        help="EMA span for ema_high/ema_low on 60m (FuturesEMAHighLow default)",
    )
    parser.add_argument(
        "--sma-period",
        type=int,
        default=9,
        help="SMA length for --only 120 (NiftySMA9Weekly default 9)",
    )
    parser.add_argument(
        "--backfill-ema",
        action="store_true",
        help="Add ema_high/ema_low to existing 60m JSONL from stored OHLC (no Yahoo fetch)",
    )
    parser.add_argument("--bb-period", type=int, default=20)
    parser.add_argument("--bb-std", type=float, default=2.0)
    parser.add_argument(
        "--also-legacy-60",
        action="store_true",
        help="Also write legacy logs/LEAPS_RSI/LEAPS_RSI_rsi_history.log (flat RSI rows)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute merge stats without writing files",
    )
    args = parser.parse_args()

    log_root = os.path.abspath(args.log_root)

    if args.backfill_ema:
        paths = _default_paths(log_root)
        target = paths.get(args.only or "60")
        if not target:
            raise SystemExit("--backfill-ema requires --only 60 (or default 60m file)")
        stats = backfill_ema_on_indicator_history(
            target,
            ema_period=args.ema_period,
            dry_run=args.dry_run,
        )
        all_stats = [stats]
    elif args.hist_path:
        mode = args.only or "60"
        tf = mode
        stats = refresh_indicator_history_file(
            os.path.abspath(args.hist_path),
            mode=mode,
            period=args.period,
            symbol=args.symbol,
            timeframe=tf,
            rsi_period=args.rsi_period,
            ema_period=args.ema_period,
            bb_period=args.bb_period,
            bb_std=args.bb_std,
            sma_period=args.sma_period,
            dry_run=args.dry_run,
        )
        all_stats = [stats]
    else:
        all_stats = refresh_all_default(
            log_root=log_root,
            period=args.period,
            only=args.only,
            dry_run=args.dry_run,
            also_legacy_60=args.also_legacy_60,
            rsi_period=args.rsi_period,
            ema_period=args.ema_period,
            bb_period=args.bb_period,
            bb_std=args.bb_std,
            sma_period=args.sma_period,
        )

    for stats in all_stats:
        if stats.get("mode") == "backfill_ema":
            print(
                f"{'[dry-run] ' if stats.get('dry_run') else ''}"
                f"[backfill_ema] rows={stats.get('rows')} | "
                f"ema_filled={stats.get('ema_filled')} | "
                f"ema_period={stats.get('ema_period')} -> {stats.get('path')}"
            )
        else:
            print(
                f"{'[dry-run] ' if stats.get('dry_run') else ''}"
                f"[{stats.get('mode', '?')}] "
                f"live_append kept={stats.get('live_kept', '—')} | "
                f"yahoo_refresh bars={stats.get('yahoo_bars', stats.get('total_out', '—'))} "
                f"({stats.get('yahoo_from', '—')} .. {stats.get('yahoo_to', '—')}) | "
                f"preserved pre-yahoo={stats.get('preserved_before_yahoo', '—')} | "
                f"total lines={stats.get('total_out', '—')} -> {stats.get('path')}"
            )


if __name__ == "__main__":
    main()
