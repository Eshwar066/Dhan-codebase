"""
Structured JSON logging per engine. One file per engine: logs/{engine_id}.log.
Closed candles: logs/{engine_id}_candles.log (see candle_created).
No print(); all events logged as one JSON object per line.
Timestamps are in India/Bangalore (IST, UTC+5:30).
"""

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

try:
    from core.data.candle_aggregator import _resolution_to_seconds
except ImportError:
    _resolution_to_seconds = None  # type: ignore

IST = ZoneInfo("Asia/Kolkata")

LOGS_DIR = "logs"
REPORTS_DIR = "reports"


class EngineLogger:
    """
    Per-engine structured logger. Thread-safe. Writes JSON lines to logs/{engine_id}.log.
    """

    def __init__(self, engine_id: str, venue: str, strategy: str, log_dir: Optional[str] = None):
        self.engine_id = engine_id
        self.venue = venue
        self.strategy = strategy
        self._log_dir = (log_dir or LOGS_DIR)
        self._path = os.path.join(self._log_dir, f"{engine_id}.log")
        self._candles_path = os.path.join(self._log_dir, f"{engine_id}_candles.log")
        self._lock = threading.Lock()
        os.makedirs(self._log_dir, exist_ok=True)

    def _payload(
        self,
        event_type: str,
        message: str = "",
        symbol: Optional[str] = None,
        side: Optional[str] = None,
        qty: Optional[int] = None,
        price: Optional[float] = None,
        order_id: Optional[str] = None,
        intent_id: Optional[str] = None,
        **extra,
    ) -> Dict[str, Any]:
        base = {
            "engine_id": self.engine_id,
            "venue": self.venue,
            "strategy": self.strategy,
            "event_type": event_type,
            "timestamp": datetime.now(IST).isoformat(),
        }
        if message:
            base["message"] = message
        if symbol is not None:
            base["symbol"] = symbol
        if side is not None:
            base["side"] = side
        if qty is not None:
            base["qty"] = qty
        if price is not None:
            base["price"] = price
        if order_id is not None:
            base["order_id"] = order_id
        if intent_id is not None:
            base["intent_id"] = intent_id
        base.update(extra)
        return base

    def log(self, event_type: str, message: str = "", **kwargs) -> None:
        payload = self._payload(event_type, message=message, **kwargs)
        line = json.dumps(payload, default=str) + "\n"
        with self._lock:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line)

    @staticmethod
    def _bar_timestamp_to_ist_iso(ts: Any) -> Optional[str]:
        """
        Same bar instant as ``bar_timestamp``, expressed in Asia/Kolkata (IST) for logs.
        Naive datetimes are interpreted as UTC (same convention as LiveEngine candle timestamps).
        """
        if ts is None:
            return None
        try:
            if isinstance(ts, datetime):
                dt_ = ts
                if dt_.tzinfo is None:
                    dt_ = dt_.replace(tzinfo=timezone.utc)
                return dt_.astimezone(IST).isoformat()
            if isinstance(ts, (int, float)):
                sec = float(ts)
                if sec >= 1e15:
                    sec /= 1e6
                elif sec >= 1e12:
                    sec /= 1000.0
                return (
                    datetime.fromtimestamp(sec, tz=timezone.utc)
                    .astimezone(IST)
                    .isoformat()
                )
            s = str(ts).strip()
            if not s:
                return None
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            parsed = datetime.fromisoformat(s)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(IST).isoformat()
        except Exception:
            return None

    def candle_created(
        self,
        candle: Dict[str, Any],
        timeframe: Optional[str] = None,
        source: str = "live",
    ) -> None:
        """Append one JSON line per closed candle to logs/{engine_id}_candles.log."""
        ts = candle.get("timestamp")
        if isinstance(ts, datetime):
            ts_out = ts.isoformat()
        else:
            ts_out = ts
        bar_ts_ist = self._bar_timestamp_to_ist_iso(ts)
        tf_sec = None
        if _resolution_to_seconds is not None and timeframe is not None:
            try:
                tf_sec = int(_resolution_to_seconds(str(timeframe)))
            except Exception:
                tf_sec = None
        payload = self._payload(
            "candle_created",
            message="Closed candle",
            symbol=candle.get("symbol"),
            timeframe=timeframe,
            tf_sec=tf_sec,
            source=source,
            open=candle.get("open"),
            high=candle.get("high"),
            low=candle.get("low"),
            close=candle.get("close"),
            volume=candle.get("volume"),
            bucket_ts=candle.get("bucket_ts"),
            bar_timestamp=ts_out,
            bar_timestamp_ist=bar_ts_ist,
            exchange=candle.get("exchange"),
        )
        line = json.dumps(payload, default=str) + "\n"
        with self._lock:
            with open(self._candles_path, "a", encoding="utf-8") as f:
                f.write(line)

    def order_placed(self, symbol: str, side: str, qty: int, price: Optional[float], order_id: Optional[str], intent_id: Optional[str] = None) -> None:
        self.log("order_placed", message="Order placed", symbol=symbol, side=side, qty=qty, price=price, order_id=order_id, intent_id=intent_id)

    def order_filled(self, symbol: str, side: str, qty: int, price: float, order_id: Optional[str]) -> None:
        self.log("order_filled", message="Order filled", symbol=symbol, side=side, qty=qty, price=price, order_id=order_id)

    def exit_triggered(self, symbol: str, side: str, qty: int, reason: str = "") -> None:
        self.log("exit_triggered", message=reason or "Exit triggered", symbol=symbol, side=side, qty=qty)

    def risk_block(self, reason: str, symbol: Optional[str] = None) -> None:
        self.log("risk_block", message=reason, symbol=symbol)

    def reconciliation(self, message: str, details: Optional[Dict] = None) -> None:
        self.log("reconciliation", message=message, **(details or {}))

    def websocket_disconnect(self, message: str = "WebSocket disconnected") -> None:
        self.log("websocket_disconnect", message=message)

    def kill_switch(self, reason: str) -> None:
        self.log("kill_switch", message=reason)

    def latency(
        self,
        strategy_time_ms: Optional[float] = None,
        broker_latency_ms: Optional[float] = None,
        total_latency_ms: Optional[float] = None,
        **extra,
    ) -> None:
        self.log("latency", message="Latency metrics", strategy_time_ms=strategy_time_ms, broker_latency_ms=broker_latency_ms, total_latency_ms=total_latency_ms, **extra)

    def feed_health_warning(self, message: str, symbol: Optional[str] = None) -> None:
        self.log("feed_health_warning", message=message, symbol=symbol)

    def feed_health_recovered(self, message: str, symbol: Optional[str] = None) -> None:
        self.log("feed_health_recovered", message=message, symbol=symbol)

    def closed_candle_skip(self, symbol: str, reason: str, **extra: Any) -> None:
        """Log skip reason; pass ``diagnostics=`` or other fields for feed/timestamp debugging."""
        self.log("closed_candle_skip", message=reason, symbol=symbol, **extra)

    def eod_export(self, path: str, message: str = "EOD export written") -> None:
        self.log("eod_export", message=message, export_path=path)

    def engine_start(self, message: str = "Live engine started") -> None:
        self.log("engine_start", message=message)

    # ---------- Production safeguards ----------
    def order_state_mismatch(self, message: str, details: Optional[Dict] = None) -> None:
        self.log("order_state_mismatch", message=message, **(details or {}))

    def duplicate_signal_blocked(self, symbol: Optional[str] = None, signal_hash: Optional[str] = None) -> None:
        self.log("duplicate_signal_blocked", message="Duplicate signal skipped", symbol=symbol, signal_hash=signal_hash)

    def broker_circuit_breaker_triggered(self, reason: str) -> None:
        self.log("broker_circuit_breaker_triggered", message=reason)

    def max_positions_blocked(self, current_count: Optional[int] = None, max_allowed: Optional[int] = None) -> None:
        self.log("max_positions_blocked", message="Max open positions reached", current_count=current_count, max_allowed=max_allowed)

    def time_window_blocked(self, message: str = "Outside allowed trading hours") -> None:
        self.log("time_window_blocked", message=message)

    def high_slippage_warning(self, symbol: Optional[str] = None, expected_price: Optional[float] = None, fill_price: Optional[float] = None, slippage_pct: Optional[float] = None) -> None:
        self.log("high_slippage_warning", message="Slippage above threshold", symbol=symbol, expected_price=expected_price, fill_price=fill_price, slippage_pct=slippage_pct)

    def memory_pressure_warning(self, message: str, usage_percent: Optional[float] = None) -> None:
        self.log("memory_pressure_warning", message=message, usage_percent=usage_percent)

    def graceful_shutdown(self, message: str = "Graceful shutdown", snapshot_path: Optional[str] = None) -> None:
        self.log("graceful_shutdown", message=message, snapshot_path=snapshot_path)

    def candle_integrity_error(self, message: str, symbol: Optional[str] = None, details: Optional[Dict] = None) -> None:
        self.log("candle_integrity_error", message=message, symbol=symbol, **(details or {}))

    def symbol_paused(self, symbol: str, reason: str) -> None:
        self.log("symbol_paused", message=reason, symbol=symbol)

    def strategy_timeout(self, symbol: Optional[str] = None, elapsed_ms: Optional[float] = None, threshold_ms: Optional[float] = None) -> None:
        self.log("strategy_timeout", message="Strategy evaluation exceeded threshold", symbol=symbol, elapsed_ms=elapsed_ms, threshold_ms=threshold_ms)

    def latency_critical_pause(self, message: str = "Latency critical for N cycles; entries paused") -> None:
        self.log("latency_critical_pause", message=message)
