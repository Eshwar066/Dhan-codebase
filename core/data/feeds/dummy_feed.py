"""
Dummy real-time feed for integration testing.

Use with LiveEngine + CandleAggregator in PAPER mode to validate:
- feed -> tick queue -> aggregator pipeline
- strategy execution on closed candles
- feed stall and tick-order edge cases

"""

from __future__ import annotations

import random
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

from core.data.feeds.base_feed import RealtimeFeed


class DummyRealtimeFeed(RealtimeFeed):
    """
    Deterministic synthetic feed that emits normalized ticks:
    {"symbol", "price", "volume", "timestamp"} where timestamp is Unix seconds.
    """
    is_dummy_feed = True

    def __init__(
        self,
        symbols: Iterable[str],
        tick_interval_ms: int = 200,
        seed: int = 42,
        *,
        start_datetime: Optional[datetime] = None,
        start_price: float = 23900,
        drift_min: float = -0.2,
        drift_max: float = 0.2,
        stall_after_ticks: Optional[int] = None,
        stall_for_seconds: float = 0.0,
        spike_at_tick: Optional[int] = None,
        spike_amount: float = 0.0,
        out_of_order_at_tick: Optional[int] = None,
        out_of_order_delay_seconds: float = 10.0,
    ) -> None:
        self.symbols: List[str] = [str(s).strip().upper() for s in symbols if str(s).strip()]
        if not self.symbols:
            raise ValueError("DummyRealtimeFeed requires at least one symbol")

        self.tick_interval = max(0.01, float(tick_interval_ms) / 1000.0)
        self._rng = random.Random(seed)
        if start_datetime is not None and start_datetime.tzinfo is None:
            start_datetime = start_datetime.replace(tzinfo=timezone.utc)
        self._start_datetime = start_datetime
        self._running = False
        self._connected = False
        self._thread: Optional[threading.Thread] = None
        self._tick_queue: Optional[Any] = None
        self._state_lock = threading.Lock()

        self._price: Dict[str, float] = {s: float(start_price) for s in self.symbols}
        self._last_ticker: Dict[str, Dict[str, Any]] = {}
        self._tick_count = 0

        self._drift_min = float(drift_min)
        self._drift_max = float(drift_max)
        self._stall_after_ticks = stall_after_ticks
        self._stall_for_seconds = max(0.0, float(stall_for_seconds))
        self._spike_at_tick = spike_at_tick
        self._spike_amount = float(spike_amount)
        self._out_of_order_at_tick = out_of_order_at_tick
        self._out_of_order_delay_seconds = max(0.0, float(out_of_order_delay_seconds))

    def set_tick_queue(self, queue: Any) -> None:
        self._tick_queue = queue

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        if self._tick_queue is None:
            raise ValueError("tick_queue not set. Call set_tick_queue() before start().")

        self._running = True
        self._connected = True
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="dummy_realtime_feed",
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def get_last_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        key = str(symbol or "").strip().upper()
        with self._state_lock:
            row = self._last_ticker.get(key)
            return dict(row) if row else None

    def get_last_candle(self, symbol: str, resolution: Optional[str] = None) -> Optional[Dict[str, Any]]:
        # CandleAggregator should be the source of candles in this integration mode.
        _ = resolution
        ticker = self.get_last_ticker(symbol)
        if not ticker:
            return None
        px = float(ticker["close"])
        ts = float(ticker["timestamp"])
        return {
            "symbol": ticker["symbol"],
            "open": px,
            "high": px,
            "low": px,
            "close": px,
            "volume": float(ticker.get("volume", 0.0)),
            "timestamp": ts,
        }

    def get_simulated_datetime_ist(self) -> Optional[datetime]:
        """Current simulated wall time in IST when ``start_datetime`` was set."""
        if self._start_datetime is None:
            return None
        with self._state_lock:
            tick_count = int(self._tick_count)
        sim_utc = self._start_datetime + timedelta(
            seconds=tick_count * self.tick_interval
        )
        return sim_utc.astimezone(ZoneInfo("Asia/Kolkata"))

    def _run(self) -> None:
        base_time = (
            self._start_datetime
            if self._start_datetime is not None
            else datetime.now(timezone.utc).replace(second=0, microsecond=0)
        )
        tick_count = 0

        while self._running:
            if (
                self._stall_after_ticks is not None
                and self._stall_for_seconds > 0
                and tick_count == self._stall_after_ticks
            ):
                time.sleep(self._stall_for_seconds)

            now = base_time + timedelta(seconds=tick_count * self.tick_interval)
            ts = now.timestamp()

            for symbol in self.symbols:
                price = self._next_price(symbol, tick_count)
                tick_ts = ts
                if (
                    self._out_of_order_at_tick is not None
                    and tick_count == self._out_of_order_at_tick
                ):
                    tick_ts -= self._out_of_order_delay_seconds

                tick = {
                    "symbol": symbol,
                    "price": price,
                    "volume": self._rng.randint(1, 10),
                    "timestamp": tick_ts,
                }

                try:
                    self._tick_queue.put_nowait(tick)  # type: ignore[union-attr]
                except Exception:
                    # Queue full or unavailable -> drop tick (non-blocking by design).
                    pass

                with self._state_lock:
                    self._last_ticker[symbol] = {
                        "symbol": symbol,
                        "close": price,
                        "volume": tick["volume"],
                        "timestamp": tick_ts,
                    }

            tick_count += 1
            with self._state_lock:
                self._tick_count = tick_count
            time.sleep(self.tick_interval)

    def _next_price(self, symbol: str, tick_count: int) -> float:
        drift = self._rng.uniform(self._drift_min, self._drift_max)
        px = self._price[symbol] + drift
        if self._spike_at_tick is not None and tick_count == self._spike_at_tick:
            px += self._spike_amount
        self._price[symbol] = max(0.01, round(px, 2))
        return self._price[symbol]

