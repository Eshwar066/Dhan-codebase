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
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

IST = __import__("zoneinfo").ZoneInfo("Asia/Kolkata")
SCHEMA_VERSION = 2

# NSE cash index hourly bar opens (IST).
NSE_60_BAR_MINUTES = frozenset(
    {(9, 15), (10, 15), (11, 15), (12, 15), (13, 15), (14, 15), (15, 15)}
)
NSE_INDEX_SYMBOLS = frozenset(
    {"NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "MIDCPNIFTY", "^NSEI", "NSEI"}
)
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


def is_nse_60m_bar_ist(dt_ist: datetime) -> bool:
    """True when ``dt_ist`` is an NSE cash-session hourly bar open (weekday, :15)."""
    if dt_ist.weekday() >= 5:
        return False
    return (int(dt_ist.hour), int(dt_ist.minute)) in NSE_60_BAR_MINUTES


def bucket_ts_is_nse_60m_bar(bucket_ts: Any) -> bool:
    """True when unix bucket start maps to an NSE hourly bar open in IST."""
    try:
        bt = int(float(bucket_ts))
    except (TypeError, ValueError):
        return False
    try:
        dt_ist = datetime.fromtimestamp(bt, IST)
    except (OSError, OverflowError, ValueError):
        return False
    return is_nse_60m_bar_ist(dt_ist)


def nse_60m_bar_close_eval_window(
    candle: Any,
    *,
    grace_minutes: int = 8,
    now_unix: Optional[float] = None,
) -> bool:
    """
    True only within a short window after an NSE hourly bar closes.

    Used by LEAPS (60m RSI) so indicator history, candle logs, and strategy eval
    run once per closed bar — not on forming or stale replay bars.
    """
    session_partial = False
    if isinstance(candle, dict):
        bucket = candle.get("bucket_ts")
        session_partial = bool(candle.get("session_close_partial"))
    else:
        bucket = candle
    if bucket is None or not bucket_ts_is_nse_60m_bar(bucket):
        return False
    try:
        bar_open_unix = int(float(bucket))
    except (TypeError, ValueError):
        return False
    if session_partial:
        from core.utils.session.session_manager import SessionManager

        partial_close = SessionManager.session_end_unix_for_bar(bar_open_unix, "INDEX")
        bar_close_unix = (
            partial_close if partial_close is not None else bar_open_unix + 3600
        )
    else:
        bar_close_unix = bar_open_unix + 3600
    now = int(now_unix if now_unix is not None else time.time())
    grace_sec = max(60, int(grace_minutes) * 60)
    return bar_close_unix <= now <= (bar_close_unix + grace_sec)


def is_nse_index_context(symbol: str, exchange: Optional[str] = None) -> bool:
    sym = str(symbol or "").strip().upper()
    ex = str(exchange or "").strip().upper()
    if ex in ("INDEX", "NSE_INDEX", "NSE"):
        return True
    return sym in NSE_INDEX_SYMBOLS


def row_timestamp_to_ist(row_ts: Any) -> Optional[datetime]:
    if row_ts is None:
        return None
    if hasattr(row_ts, "to_pydatetime"):
        row_ts = row_ts.to_pydatetime()
    if hasattr(row_ts, "astimezone"):
        try:
            if row_ts.tzinfo is None:
                return row_ts.replace(tzinfo=IST)
            return row_ts.astimezone(IST).replace(second=0, microsecond=0)
        except Exception:
            return None
    if isinstance(row_ts, datetime):
        if row_ts.tzinfo is None:
            return row_ts.replace(tzinfo=IST)
        return row_ts.astimezone(IST).replace(second=0, microsecond=0)
    return parse_bar_timestamp_ist_to_aware(row_ts)


def timeframe_grace_seconds(timeframe: str) -> int:
    """Bar-length grace when rejecting future indicator-history rows."""
    tf = str(timeframe or "").strip().lower()
    if not tf:
        return 120
    if tf.endswith("h"):
        try:
            return max(3600, int(tf[:-1]) * 3600) + 60
        except ValueError:
            return 3660
    if tf in ("1h",):
        return 3660
    if tf in ("1d", "day"):
        return 86460
    try:
        return max(60, int(tf) * 60) + 60
    except ValueError:
        return 120


def bar_timestamp_is_future(
    row_timestamp: Any,
    timeframe: str,
    *,
    grace_seconds: Optional[float] = None,
) -> bool:
    """True when bar open is ahead of wall clock (corrupt seed / TZ bug)."""
    dt_ist = row_timestamp_to_ist(row_timestamp)
    if dt_ist is None:
        return False
    grace = float(grace_seconds if grace_seconds is not None else timeframe_grace_seconds(timeframe))
    try:
        bar_utc = dt_ist.astimezone(timezone.utc).timestamp()
    except (OSError, OverflowError, ValueError):
        return False
    return bar_utc > time.time() + grace


def should_append_live_indicator_row(
    symbol: str,
    timeframe: str,
    row_timestamp: Any,
    *,
    exchange: Optional[str] = None,
) -> bool:
    """
    Gate ``live_append`` rows: for NSE index 60m history only accept session hourly opens.
    Other symbols/timeframes pass through unchanged.
    """
    tf = str(timeframe or "").strip().lower()
    if tf not in ("60", "1h"):
        return True
    if not is_nse_index_context(symbol, exchange):
        return True
    dt_ist = row_timestamp_to_ist(row_timestamp)
    if dt_ist is None:
        return False
    return is_nse_60m_bar_ist(dt_ist)


def _ohlc_close_from_payload(payload: Dict[str, Any]) -> float:
    """Schema v2 stores OHLC under ``ohlc``; legacy rows may use top-level fields."""
    ohlc = payload.get("ohlc") if isinstance(payload.get("ohlc"), dict) else {}
    if ohlc and ohlc.get("close") is not None:
        close = float(ohlc["close"])
    elif payload.get("close") is not None:
        close = float(payload["close"])
    else:
        raise TypeError("missing close")
    if math.isnan(close):
        raise ValueError("nan close")
    return close


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
                    if bar_timestamp_is_future(bar_dt, tf_s):
                        continue
                    ohlc = payload.get("ohlc") if isinstance(payload.get("ohlc"), dict) else {}
                    try:
                        close = _ohlc_close_from_payload(payload)
                    except (TypeError, ValueError):
                        continue
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
    exchange: Optional[str] = None,
) -> None:
    """Append one JSONL line; indicator_keys selects columns from row (Series/dict)."""
    if not indicator_keys:
        return
    ts = row.get("timestamp") if hasattr(row, "get") else None
    if ts is None:
        return
    if source == "live_append" and not should_append_live_indicator_row(
        symbol, timeframe, ts, exchange=exchange
    ):
        return
    if hasattr(ts, "to_pydatetime"):
        ts = ts.to_pydatetime()
    ist_ts = normalize_ist_bar_key(
        ts.astimezone(IST).strftime("%Y-%m-%d %H:%M") if hasattr(ts, "astimezone") else ts
    )
    if not ist_ts:
        return
    if bar_timestamp_is_future(ts, timeframe):
        if source in ("historical_seed", "delta_refresh", "yahoo_refresh"):
            logger.debug(
                "Reject future indicator row symbol=%s tf=%s source=%s ist=%s",
                symbol,
                timeframe,
                source,
                ist_ts,
            )
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
