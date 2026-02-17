"""
Prop-grade Candle Aggregator: tick → 1m only; higher timeframes from closed 1m only.

- Lock-free: single state owner (processor loop); no locks. WebSocket must not mutate candles.
- O(1) per tick: integer bucket math only; no iteration over timeframes per tick.
- Closed candles immutable; never repaint. get_last_closed_candle returns only last closed bar.
- Broker-agnostic: same aggregator for Dhan and Delta; feed and candles feed multiple brokers
  by giving each engine its own aggregator instance (per-engine isolation).
"""

from collections import deque
from typing import Any, Dict, List, Optional

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


def _resolution_to_seconds(resolution: Optional[str]) -> int:
    if resolution is None:
        return SECONDS_1M
    r = str(resolution).strip().lower()
    return TIMEFRAME_SECONDS.get(r, TIMEFRAME_SECONDS.get("1m", 60))


def _bucket_ts(ts_sec: float, tf_seconds: int) -> int:
    """Integer bucket boundary. ts_sec in Unix seconds; tf_seconds e.g. 60, 300."""
    t = int(ts_sec)
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

    def __init__(self, max_closed_per_tf: int = MAX_CLOSED_LEN):
        self._max_closed = max(1, min(max_closed_per_tf, 500))
        # symbol -> timeframe_seconds -> {"current": dict | None, "closed": deque}
        self._state: Dict[str, Dict[int, Dict[str, Any]]] = {}
        # Ordered list of higher TF seconds (excluding 1m) for propagation
        self._higher_tf_seconds: List[int] = [300, 900, 1800, 3600, 7200, 14400, 86400]

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

        bucket_1m = _bucket_ts(ts, SECONDS_1M)
        cell_1m = self._ensure_symbol_tf(symbol, SECONDS_1M)
        cur = cell_1m["current"]

        if cur is None:
            cell_1m["current"] = _candle_to_dict(symbol, price, price, price, price, volume, bucket_1m)
            return

        if cur["bucket_ts"] == bucket_1m:
            # Same 1m bucket: update current only
            high = max(cur["high"], price)
            low = min(cur["low"], price)
            cell_1m["current"] = _candle_to_dict(
                symbol, cur["open"], high, low, price, cur["volume"] + volume, bucket_1m
            )
            return

        # Bucket changed: close previous 1m, append to closed, then propagate
        closed_1m = cur
        cell_1m["closed"].append(closed_1m)
        cell_1m["current"] = _candle_to_dict(symbol, price, price, price, price, volume, bucket_1m)
        self._propagate_from_closed_1m(symbol, closed_1m)

    def _propagate_from_closed_1m(self, symbol: str, closed_1m: Dict[str, Any]) -> None:
        """Aggregate closed 1m into higher TFs; close only when bucket boundary aligns."""
        bucket_1m = closed_1m["bucket_ts"]
        for tf_sec in self._higher_tf_seconds:
            cell = self._ensure_symbol_tf(symbol, tf_sec)
            target_bucket = _bucket_ts(bucket_1m, tf_sec)
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
