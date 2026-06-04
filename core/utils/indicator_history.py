"""
Shared per-(symbol, timeframe) indicator history on disk (JSONL).

Path: logs/indicators/{SYMBOL}/{timeframe}/indicator_history.jsonl

Legacy LEAPS RSI files (logs/{strategy}/{strategy}_rsi_history.log) are read for bootstrap
when the shared file is missing or short.
"""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

IST = __import__("zoneinfo").ZoneInfo("Asia/Kolkata")
SCHEMA_VERSION = 2
DEFAULT_LOG_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "logs",
)


def indicator_history_path(
    symbol: str,
    timeframe: str,
    log_root: str = DEFAULT_LOG_ROOT,
) -> str:
    sym = str(symbol or "").strip().upper() or "UNKNOWN"
    tf = str(timeframe or "").strip() or "60"
    safe_sym = sym.replace("/", "_").replace("\\", "_")
    return os.path.join(log_root, "indicators", safe_sym, tf, "indicator_history.jsonl")


def legacy_rsi_history_path(strategy_id: str, log_root: str = DEFAULT_LOG_ROOT) -> str:
    sid = str(strategy_id or "GLOBAL").strip() or "GLOBAL"
    safe = sid.replace("/", "_").replace("\\", "_").replace(" ", "_")
    return os.path.join(log_root, safe, f"{safe}_rsi_history.log")


def parse_bar_timestamp_ist_to_aware(bar_ist: Any) -> Optional[datetime]:
    s = str(bar_ist).strip()
    if not s:
        return None
    try:
        if "T" in s:
            t = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=IST)
            return t.astimezone(IST).replace(second=0, microsecond=0)
        if len(s) >= 16 and s[4] == "-" and s[10] == " ":
            t = datetime.strptime(s[:16], "%Y-%m-%d %H:%M")
            return t.replace(tzinfo=IST)
    except Exception:
        return None
    return None


def normalize_ist_bar_key(bar_ist: Any) -> str:
    aware = parse_bar_timestamp_ist_to_aware(bar_ist)
    if aware is not None:
        return aware.strftime("%Y-%m-%d %H:%M")
    s = str(bar_ist).strip().replace("T", " ")[:16]
    return s


def _extract_indicators_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    ind = payload.get("indicators")
    if isinstance(ind, dict):
        return {k: v for k, v in ind.items()}
    out: Dict[str, Any] = {}
    for key in (
        "rsi",
        "prev_rsi",
        "ema_high",
        "ema_low",
        "bb_upper",
        "bb_mid",
        "bb_lower",
    ):
        if key in payload and payload[key] is not None:
            out[key] = payload[key]
    return out


def load_indicator_history_rows(
    symbol: str,
    timeframe: str,
    *,
    max_rows: int = 500,
    log_root: str = DEFAULT_LOG_ROOT,
    strategy_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Load merged rows (one per bar timestamp) with keys:
    timestamp (UTC aware), open, high, low, close, volume, symbol, exchange, indicators.
    """
    sym_u = str(symbol or "").strip().upper()
    tf_s = str(timeframe or "").strip()
    by_ist: Dict[str, Dict[str, Any]] = {}

    def _ingest_file(path: str, is_legacy: bool) -> None:
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if not s:
                        continue
                    try:
                        payload = json.loads(s)
                    except json.JSONDecodeError:
                        continue
                    if str(payload.get("symbol") or "").strip().upper() != sym_u:
                        continue
                    if str(payload.get("timeframe") or "").strip() != tf_s:
                        continue
                    ist_key = normalize_ist_bar_key(
                        payload.get("candle_timestamp_ist")
                    )
                    if not ist_key:
                        continue
                    bar_dt = parse_bar_timestamp_ist_to_aware(ist_key)
                    if bar_dt is None:
                        continue
                    try:
                        close = float(payload.get("close"))
                        if math.isnan(close):
                            continue
                    except (TypeError, ValueError):
                        continue
                    ohlc = payload.get("ohlc") if isinstance(payload.get("ohlc"), dict) else {}
                    o = float(ohlc.get("open", close) if ohlc else payload.get("open", close))
                    h = float(ohlc.get("high", close) if ohlc else payload.get("high", close))
                    l = float(ohlc.get("low", close) if ohlc else payload.get("low", close))
                    ind = _extract_indicators_from_payload(payload)
                    prev = by_ist.get(ist_key, {})
                    prev_ind = dict(prev.get("indicators") or {})
                    prev_ind.update(ind)
                    by_ist[ist_key] = {
                        "timestamp": bar_dt.astimezone(timezone.utc),
                        "open": o,
                        "high": h,
                        "low": l,
                        "close": close,
                        "volume": float(payload.get("volume") or 0),
                        "symbol": sym_u,
                        "exchange": str(
                            payload.get("exchange") or prev.get("exchange") or "INDEX"
                        ),
                        "indicators": prev_ind,
                        "source": payload.get("source") or ("legacy_rsi" if is_legacy else ""),
                    }
        except OSError:
            logger.exception("Failed reading indicator history: %s", path)

    path = indicator_history_path(sym_u, tf_s, log_root=log_root)
    _ingest_file(path, is_legacy=False)
    if strategy_id:
        _ingest_file(legacy_rsi_history_path(strategy_id, log_root=log_root), is_legacy=True)

    rows = list(by_ist.values())
    rows.sort(key=lambda r: r["timestamp"])
    if len(rows) > max_rows:
        rows = rows[-max_rows:]
    return rows


def hydrate_session_keys_from_disk(
    symbol: str,
    timeframe: str,
    strategy_id: Optional[str],
    logged_keys: set,
    seeded_streams: set,
    *,
    log_root: str = DEFAULT_LOG_ROOT,
) -> int:
    """Populate dedupe keys and mark stream seeded if history exists."""
    stream_key = (symbol, timeframe)
    if stream_key in seeded_streams:
        return 0
    count = 0
    sym_u = str(symbol or "").strip().upper()
    tf_s = str(timeframe or "").strip()
    paths = [indicator_history_path(sym_u, tf_s, log_root=log_root)]
    if strategy_id:
        paths.append(legacy_rsi_history_path(strategy_id, log_root=log_root))
    for path in paths:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if not s:
                        continue
                    try:
                        payload = json.loads(s)
                    except json.JSONDecodeError:
                        continue
                    if str(payload.get("symbol") or "").strip().upper() != sym_u:
                        continue
                    if str(payload.get("timeframe") or "").strip() != tf_s:
                        continue
                    ist_ts = normalize_ist_bar_key(payload.get("candle_timestamp_ist"))
                    if not ist_ts:
                        continue
                    source = str(payload.get("source") or "historical_seed")
                    key = (sym_u, tf_s, ist_ts, source)
                    logged_keys.add(key)
                    count += 1
        except OSError:
            logger.exception("Failed hydrating indicator session: %s", path)
    if count > 0:
        seeded_streams.add(stream_key)
    return count


def append_indicator_history_row(
    symbol: str,
    timeframe: str,
    row: Any,
    indicator_keys: List[str],
    *,
    source: str = "live_append",
    log_root: str = DEFAULT_LOG_ROOT,
    logged_keys: Optional[set] = None,
    round_fn: Any = None,
) -> None:
    """Append one JSONL line; indicator_keys selects columns from row (Series/dict)."""
    if not indicator_keys:
        return
    ts = row.get("timestamp") if hasattr(row, "get") else None
    if ts is None:
        return
    if hasattr(ts, "to_pydatetime"):
        ts = ts.to_pydatetime()
    ist_ts = normalize_ist_bar_key(
        ts.astimezone(IST).strftime("%Y-%m-%d %H:%M") if hasattr(ts, "astimezone") else ts
    )
    if not ist_ts:
        return
    sym_u = str(symbol or "").strip().upper()
    tf_s = str(timeframe or "").strip()
    dedupe_key = (sym_u, tf_s, ist_ts, source)
    if logged_keys is not None:
        if dedupe_key in logged_keys:
            return
        logged_keys.add(dedupe_key)

    indicators: Dict[str, Any] = {}
    for key in indicator_keys:
        if key in ("timestamp", "symbol", "exchange", "open", "high", "low", "close", "volume"):
            continue
        try:
            val = row[key] if hasattr(row, "__getitem__") else getattr(row, key, None)
        except (KeyError, TypeError):
            val = None
        if val is None:
            continue
        try:
            if isinstance(val, float) and math.isnan(val):
                continue
        except Exception:
            pass
        indicators[key] = val

    if not indicators and source == "live_append":
        return

    path = indicator_history_path(sym_u, tf_s, log_root=log_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload: Dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "symbol": sym_u,
        "timeframe": tf_s,
        "source": source,
        "candle_timestamp_ist": ist_ts,
        "ohlc": {
            "open": row.get("open"),
            "high": row.get("high"),
            "low": row.get("low"),
            "close": row.get("close"),
        },
        "indicators": indicators,
    }
    try:
        pl = round_fn(payload) if round_fn is not None else payload
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(pl, default=str) + "\n")
    except OSError:
        logger.exception("Failed writing indicator history: %s", path)
