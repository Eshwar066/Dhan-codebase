"""
Optional lag diagnostics (see repo ``cursor.md``).

Enable with environment variable::

    ALGO_LAG_DIAG=1

WebSocket tick lines (``Tick time`` / ``Now IST``) also enable with::

    ALGO_WS_TICK_DIAG=1

(so you can trace ticks without turning on full engine lag prints).

Prints data lag (candle time vs wall clock), strategy runtime, and API batch time.

WebSocket raw tick (Delta ``v2/ticker``): compares exchange tick time vs ``Now IST``
(throttled, default 2s). If tick time ≈ now → feed is real-time; large gap points to
candle builder / aggregation delay instead.

**Stale tick filter** (see ``cursor.md``): set ``ALGO_WS_MAX_TICK_LAG_SEC=5`` to drop
ticks whose exchange timestamp is more than 5s behind UTC now (avoids snapshot/old
data polluting candles). Disable with ``ALGO_WS_MAX_TICK_LAG_SEC=0`` or ``off``.
"""

from __future__ import annotations

import os
import time as time_module
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pandas as pd

IST = timezone(timedelta(hours=5, minutes=30))

# Throttle WS tick prints (high message rate)
_ws_tick_last_print: float = 0.0
# One-shot warning when lag suggests snapshot replay (cursor.md)
_snapshot_data_warned: bool = False


def lag_diag_enabled() -> bool:
    return os.environ.get("ALGO_LAG_DIAG", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def ws_tick_diag_enabled() -> bool:
    """Tick-time vs IST prints (WebSocket); on if LAG_DIAG or WS_TICK_DIAG is set."""
    if lag_diag_enabled():
        return True
    return os.environ.get("ALGO_WS_TICK_DIAG", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def print_data_check(candle: dict) -> None:
    """
    Step 1: verify data delay (exchange → you) before strategy runs.
    ``candle['timestamp']`` may be naive UTC, tz-aware, or epoch seconds/ms.
    """
    if not lag_diag_enabled():
        return
    ts_raw = candle.get("timestamp")
    try:
        ts = pd.Timestamp(ts_raw)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        ts_ist = ts.tz_convert(IST)
    except Exception as e:
        print("📊 DATA CHECK (parse error):", e, "| raw:", ts_raw)
        return

    now_ist = datetime.now(IST)
    lag_sec = (now_ist - ts_ist.to_pydatetime()).total_seconds()
    print("📊 DATA CHECK")
    print("Candle IST:", ts_ist)
    print("Now IST:", now_ist)
    print("Data lag (sec):", lag_sec)
    # Shortcut line from cursor.md
    print("Lag:", lag_sec)


def print_ws_tick_vs_now(tick: dict, min_interval_sec: float = 2.0) -> None:
    """
    Inside WebSocket handler (raw ticker dict): compare exchange time vs wall clock.

    Delta uses ``timestamp`` / ``generated_at`` (microseconds); ``time`` if present.
    """
    global _ws_tick_last_print
    if not ws_tick_diag_enabled():
        return
    now_mono = time_module.time()
    if now_mono - _ws_tick_last_print < min_interval_sec:
        return
    _ws_tick_last_print = now_mono

    tick_time = (
        tick.get("time")
        or tick.get("timestamp")
        or tick.get("generated_at")
        or tick.get("candle_start_time")
    )
    print("Tick time:", tick_time)
    print("Now IST:", datetime.now(IST))


def ws_max_tick_lag_sec() -> Optional[float]:
    """
    Max allowed lag (exchange tick time → UTC now) before dropping a WS tick.
    Unset / 0 / off → filter disabled.
    """
    v = os.environ.get("ALGO_WS_MAX_TICK_LAG_SEC", "").strip()
    if not v or v.lower() in ("off", "0", "false", "no", "none"):
        return None
    try:
        x = float(v)
        return x if x > 0 else None
    except ValueError:
        return 5.0


def parse_tick_time_value(tick_time: Any) -> Optional[datetime]:
    """Parse exchange time: int/float epoch or microseconds, or ISO string (cursor.md)."""
    if tick_time is None:
        return None
    if isinstance(tick_time, datetime):
        if tick_time.tzinfo is None:
            tick_time = tick_time.replace(tzinfo=timezone.utc)
        return tick_time.astimezone(timezone.utc)
    if isinstance(tick_time, (int, float)):
        v = float(tick_time)
        # Align with ``delta_websocket`` ticker path (microseconds when large)
        if v > 1e12:
            v = v / 1e6
        return datetime.fromtimestamp(v, tz=timezone.utc)
    if isinstance(tick_time, str):
        s = tick_time.strip()
        if not s:
            return None
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def parse_tick_exchange_time_from_message(tick: dict) -> Optional[datetime]:
    """Best-effort exchange time from Delta-style ticker/candle WS payload."""
    for key in ("time", "timestamp", "generated_at", "candle_start_time"):
        raw = tick.get(key)
        if raw is not None:
            dt = parse_tick_time_value(raw)
            if dt is not None:
                return dt
    return None


def ws_tick_should_drop_stale(
    tick: dict,
    *,
    snapshot_warn_sec: float = 60.0,
) -> bool:
    """
    If ``ALGO_WS_MAX_TICK_LAG_SEC`` is set, drop ticks older than that many seconds
    vs UTC now. Returns True if this message should be ignored (no on_tick / no cache).
    """
    global _snapshot_data_warned
    max_lag = ws_max_tick_lag_sec()
    if max_lag is None:
        return False
    tick_dt = parse_tick_exchange_time_from_message(tick)
    if tick_dt is None:
        return False
    now = datetime.now(timezone.utc)
    lag = (now - tick_dt).total_seconds()
    if lag > snapshot_warn_sec and not _snapshot_data_warned:
        print("⚠️ Snapshot data detected")
        _snapshot_data_warned = True
    if lag > max_lag:
        print(f"❌ DROPPED stale tick | lag={lag:.1f}s | time={tick_dt}")
        return True
    return False
