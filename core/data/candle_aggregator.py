"""
Prop-grade Candle Aggregator: tick → 1m only; higher timeframes from closed 1m only.

- Lock-free: single state owner (processor loop); no locks. WebSocket must not mutate candles.
- O(1) per tick: integer bucket math only; no iteration over timeframes per tick.
- Closed candles immutable; never repaint. get_last_closed_candle returns only last closed bar.
- Broker-agnostic: same aggregator for Dhan and Delta; feed and candles feed multiple brokers
  by giving each engine its own aggregator instance (per-engine isolation).
"""
# Future upgrades:

# 1️⃣ Add optional gap-filling logic
# 2️⃣ Add timestamp monotonicity check
# 3️⃣ Add health counter (ticks processed)
# 4️⃣ Add late-tick rejection guard

from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from core.utils.dhan_tick_time import unix_epoch_to_ist_iso

# Supported timeframes: 1m base; higher from closed 1m only.
TIMEFRAME_SECONDS = {
    "1m": 60,
    "1": 60,
    "5m": 300,
    "5": 300,
    "15m": 900,
    "15": 900,
    "30m": 1800,
    "30": 1800,
    "1h": 3600,
    "60": 3600,
    "2h": 7200,
    "2": 7200,
    "4h": 14400,
    "4": 14400,
    "1d": 86400,
    "d": 86400,
}
SECONDS_1M = 60
MAX_CLOSED_LEN = 300
IST_TZ = timezone(timedelta(hours=5, minutes=30))

# MCX regular session (Asia/Kolkata), aligned with core/utils/session/market_calendar.MARKET_SESSIONS["MCX"].
MCX_DEFAULT_SESSION_START_SEC = 9 * 3600
MCX_DEFAULT_SESSION_END_SEC = (23 * 3600) + (30 * 60)


def _resolution_to_seconds(resolution: Optional[str]) -> int:
    if resolution is None:
        return SECONDS_1M
    r = str(resolution).strip().lower()
    return TIMEFRAME_SECONDS.get(r, TIMEFRAME_SECONDS.get("1m", 60))


def _bucket_ts(
    ts_sec: float,
    tf_seconds: int,
    *,
    session_start_sec: Optional[int] = None,
    session_end_sec: Optional[int] = None,
) -> Optional[int]:
    """
    Integer bucket boundary.

    - Default: wall-clock epoch bucketing.
    - Session mode: if session boundaries are provided, reject timestamps outside the
      session for intraday TFs and anchor >=1h buckets to session start.
    """
    t = int(ts_sec)
    if tf_seconds <= 0:
        return None

    if (
        session_start_sec is not None
        and session_end_sec is not None
        and 60 <= tf_seconds < 86400
    ):
        dt_ist = datetime.fromtimestamp(t, IST_TZ)
        sec_of_day = dt_ist.hour * 3600 + dt_ist.minute * 60 + dt_ist.second
        if sec_of_day < session_start_sec or sec_of_day >= session_end_sec:
            return None

        # For hourly+ bars, anchor buckets to market open (e.g., 09:15 for NSE/BSE).
        if tf_seconds >= 3600:
            offset = sec_of_day - session_start_sec
            bucket_start_sec = session_start_sec + (offset // tf_seconds) * tf_seconds
            day_start_ist = dt_ist.replace(hour=0, minute=0, second=0, microsecond=0)
            bucket_dt_ist = day_start_ist + timedelta(seconds=bucket_start_sec)
            return int(bucket_dt_ist.astimezone(timezone.utc).timestamp())

    return t - (t % tf_seconds)


def _candle_to_dict(symbol: str, open_p: float, high: float, low: float, close: float, volume: float, bucket_ts: int) -> Dict[str, Any]:
    return {
        "symbol": symbol,
        "open": open_p,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "timestamp": bucket_ts,
        "bucket_ts": bucket_ts,
    }


class CandleAggregator:
    """
    Lock-free candle engine. Ticks update only 1m current; when 1m bucket changes,
    close 1m → append to closed deque → propagate to higher TFs from closed 1m only.
    Single state owner: only the processor loop that calls on_tick() mutates state.
    """

    def __init__(
        self,
        max_closed_per_tf: int = MAX_CLOSED_LEN,
        session_start_sec: Optional[int] = None,
        session_end_sec: Optional[int] = None,
        engine_logger: Optional[Any] = None,
        debug_mode: bool = False,
    ):
        self._max_closed = max(1, min(max_closed_per_tf, 500))
        self._session_start_sec = session_start_sec
        self._session_end_sec = session_end_sec
        self._engine_logger = engine_logger
        self._debug_mode = bool(debug_mode)
        # symbol -> timeframe_seconds -> {"current": dict | None, "closed": deque}
        self._state: Dict[str, Dict[int, Dict[str, Any]]] = {}
        # Ordered list of higher TF seconds (excluding 1m) for propagation
        self._higher_tf_seconds: List[int] = [300, 900, 1800, 3600, 7200, 14400, 86400]
        self._last_tick_ts_by_symbol: Dict[str, float] = {}
        self._tick_count_by_symbol_bucket: Dict[str, int] = {}
        # symbol|YYYY-MM-DD (IST): session-end flush already applied for that local day.
        self._mcx_session_flush_done: set[str] = set()

    def _prune_mcx_session_flush_keys(self, dt_ist: datetime) -> None:
        if len(self._mcx_session_flush_done) <= 400:
            return
        cutoff = (dt_ist.date() - timedelta(days=14)).isoformat()
        stale = [k for k in self._mcx_session_flush_done if k.rsplit("|", 1)[-1] < cutoff]
        for k in stale:
            self._mcx_session_flush_done.discard(k)

    def flush_mcx_session_end(self, symbol: str, now_unix: float) -> bool:
        """
        After MCX cash-session close (IST), finalize in-flight candles without waiting for a
        post-session tick. Required because the last 1h bar may otherwise stay in ``current``
        until the next bucket's first tick (often next session).

        Idempotent per symbol per IST calendar day (23:30–23:59 same day). Marks finalized
        rows with ``session_close_partial`` when the bar was forced at session end.
        """
        if self._session_start_sec is None or self._session_end_sec is None:
            return False
        sym = str(symbol).strip()
        if not sym:
            return False
        dt_ist = datetime.fromtimestamp(now_unix, IST_TZ)
        sod = dt_ist.hour * 3600 + dt_ist.minute * 60 + dt_ist.second
        if sod < self._session_end_sec:
            return False
        day_key = dt_ist.strftime("%Y-%m-%d")
        cache_key = f"{sym}|{day_key}"
        if cache_key in self._mcx_session_flush_done:
            return False

        self._prune_mcx_session_flush_keys(dt_ist)

        did_any = False
        cell_1m = self._state.get(sym, {}).get(SECONDS_1M)
        if cell_1m and cell_1m.get("current"):
            closed_1m = dict(cell_1m["current"])
            closed_1m["session_close_partial"] = True
            cell_1m["closed"].append(closed_1m)
            cell_1m["current"] = None
            old_key = f"{sym}|{closed_1m.get('bucket_ts')}"
            if old_key in self._tick_count_by_symbol_bucket:
                del self._tick_count_by_symbol_bucket[old_key]
            self._propagate_from_closed_1m(sym, closed_1m)
            did_any = True

        for tf_sec in self._higher_tf_seconds:
            cell = self._state.get(sym, {}).get(tf_sec)
            if not cell or not cell.get("current"):
                continue
            cur = dict(cell["current"])
            cur["session_close_partial"] = True
            cell["closed"].append(cur)
            cell["current"] = None
            did_any = True

        self._mcx_session_flush_done.add(cache_key)
        if did_any and self._engine_logger:
            self._engine_logger.log(
                "mcx_session_candle_flush",
                f"Session-end candle flush symbol={sym} ist_day={day_key}",
                symbol=sym,
                ist_day=day_key,
            )
        return did_any

    def _ensure_symbol_tf(self, symbol: str, tf_seconds: int) -> Dict[str, Any]:
        if symbol not in self._state:
            self._state[symbol] = {}
        if tf_seconds not in self._state[symbol]:
            self._state[symbol][tf_seconds] = {
                "current": None,
                "closed": deque(maxlen=self._max_closed),
            }
        return self._state[symbol][tf_seconds]

    def on_tick(self, symbol: str, price: float, volume: float, timestamp_sec: float) -> None:
        """
        Process one tick. O(1). Updates only 1m current; closes 1m and propagates when bucket changes.
        """
        symbol = str(symbol).strip()
        if not symbol:
            return
        try:
            price = float(price)
        except (TypeError, ValueError):
            return
        volume = float(volume) if volume is not None else 0.0
        ts = float(timestamp_sec)
        prev_tick_ts = float(self._last_tick_ts_by_symbol.get(symbol, 0.0) or 0.0)
        if prev_tick_ts > 0:
            gap_sec = ts - prev_tick_ts
            if gap_sec > 60.0 and self._engine_logger:
                self._engine_logger.log(
                    "tick_gap_detected",
                    f"Tick gap detected symbol={symbol} gap_sec={gap_sec:.2f}",
                    symbol=symbol,
                    gap_sec=round(gap_sec, 3),
                    prev_tick_ts=prev_tick_ts,
                    tick_timestamp=ts,
                    prev_tick_ts_ist=unix_epoch_to_ist_iso(prev_tick_ts),
                    tick_timestamp_ist=unix_epoch_to_ist_iso(ts),
                )
        self._last_tick_ts_by_symbol[symbol] = ts

        cell_1m = self._ensure_symbol_tf(symbol, SECONDS_1M)
        cur = cell_1m["current"]
        bucket_1m = _bucket_ts(
            ts,
            SECONDS_1M,
            session_start_sec=self._session_start_sec,
            session_end_sec=self._session_end_sec,
        )

        # Outside configured intraday session: finalize any in-progress candle and stop.
        if bucket_1m is None:
            if cur is not None:
                closed_1m = cur
                cell_1m["closed"].append(closed_1m)
                cell_1m["current"] = None
                self._propagate_from_closed_1m(symbol, closed_1m)
            return

        if cur is None:
            cell_1m["current"] = _candle_to_dict(symbol, price, price, price, price, volume, bucket_1m)
            self._tick_count_by_symbol_bucket[f"{symbol}|{bucket_1m}"] = 1
            if self._engine_logger and self._debug_mode:
                self._engine_logger.log(
                    "candle_building",
                    f"Candle building started symbol={symbol} bucket={bucket_1m}",
                    symbol=symbol,
                    bucket_ts=bucket_1m,
                    tick_count=1,
                    timeframe="1m",
                )
            return

        if cur["bucket_ts"] == bucket_1m:
            # Same 1m bucket: update current only
            high = max(cur["high"], price)
            low = min(cur["low"], price)
            cell_1m["current"] = _candle_to_dict(
                symbol, cur["open"], high, low, price, cur["volume"] + volume, bucket_1m
            )
            key = f"{symbol}|{bucket_1m}"
            tick_count = int(self._tick_count_by_symbol_bucket.get(key, 0)) + 1
            self._tick_count_by_symbol_bucket[key] = tick_count
            if self._engine_logger and (tick_count == 2 or tick_count % 10 == 0) and self._debug_mode:
                self._engine_logger.log(
                    "candle_building",
                    f"Candle building symbol={symbol} bucket={bucket_1m} ticks={tick_count}",
                    symbol=symbol,
                    bucket_ts=bucket_1m,
                    tick_count=tick_count,
                    timeframe="1m",
                )
            return

        # Bucket changed: close previous 1m, append to closed, then propagate
        closed_1m = cur
        cell_1m["closed"].append(closed_1m)
        old_key = f"{symbol}|{cur['bucket_ts']}"
        if old_key in self._tick_count_by_symbol_bucket:
            del self._tick_count_by_symbol_bucket[old_key]
        cell_1m["current"] = _candle_to_dict(symbol, price, price, price, price, volume, bucket_1m)
        self._tick_count_by_symbol_bucket[f"{symbol}|{bucket_1m}"] = 1
        if self._engine_logger and self._debug_mode:
            self._engine_logger.log(
                "candle_building",
                f"Candle building started symbol={symbol} bucket={bucket_1m}",
                symbol=symbol,
                bucket_ts=bucket_1m,
                tick_count=1,
                timeframe="1m",
            )
        self._propagate_from_closed_1m(symbol, closed_1m)

    def _propagate_from_closed_1m(self, symbol: str, closed_1m: Dict[str, Any]) -> None:
        """Aggregate closed 1m into higher TFs; close only when bucket boundary aligns."""
        bucket_1m = closed_1m["bucket_ts"]
        for tf_sec in self._higher_tf_seconds:
            cell = self._ensure_symbol_tf(symbol, tf_sec)
            target_bucket = _bucket_ts(
                bucket_1m,
                tf_sec,
                session_start_sec=self._session_start_sec,
                session_end_sec=self._session_end_sec,
            )
            if target_bucket is None:
                # Intraday out-of-session / invalid bucket for this TF.
                continue
            cur = cell["current"]

            if cur is None:
                cell["current"] = _candle_to_dict(
                    symbol,
                    closed_1m["open"],
                    closed_1m["high"],
                    closed_1m["low"],
                    closed_1m["close"],
                    closed_1m["volume"],
                    target_bucket,
                )
                continue

            if cur["bucket_ts"] == target_bucket:
                high = max(cur["high"], closed_1m["high"])
                low = min(cur["low"], closed_1m["low"])
                cell["current"] = _candle_to_dict(
                    symbol,
                    cur["open"],
                    high,
                    low,
                    closed_1m["close"],
                    cur["volume"] + closed_1m["volume"],
                    target_bucket,
                )
                continue

            # Boundary crossed: close this TF candle
            cell["closed"].append(cur)
            cell["current"] = _candle_to_dict(
                symbol,
                closed_1m["open"],
                closed_1m["high"],
                closed_1m["low"],
                closed_1m["close"],
                closed_1m["volume"],
                target_bucket,
            )

    def get_last_closed_candle(self, symbol: str, resolution: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Return the last CLOSED candle only. Never returns forming candle; no repainting.
        resolution: e.g. "1m", "5m", "15m", "30m", "1h", "2h", "4h", "1d" or "1", "5", "60", etc.
        """
        symbol = str(symbol).strip()
        tf_sec = _resolution_to_seconds(resolution)
        cell = self._state.get(symbol, {}).get(tf_sec)
        if not cell or not cell["closed"]:
            return None
        out = dict(cell["closed"][-1])
        out["timestamp"] = out.get("bucket_ts", out["timestamp"])
        return out

    def get_all_closed_for_resolution(self, symbol: str, resolution: Optional[str], max_bars: int = 300) -> List[Dict[str, Any]]:
        """Return up to max_bars last closed candles for symbol/resolution (newest last)."""
        symbol = str(symbol).strip()
        tf_sec = _resolution_to_seconds(resolution)
        cell = self._state.get(symbol, {}).get(tf_sec)
        if not cell or not cell["closed"]:
            return []
        closed = cell["closed"]
        n = min(max_bars, len(closed))
        return [dict(closed[-n + i]) for i in range(n)]

    def symbols_with_data(self) -> List[str]:
        """Symbols that have at least some state (for health checks)."""
        return list(self._state.keys())
