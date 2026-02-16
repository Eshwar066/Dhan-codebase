"""
Structured JSON logging per engine. One file per engine: logs/{engine_id}.log.
No print(); all events logged as one JSON object per line.
"""

import json
import os
import threading
from datetime import datetime
from typing import Any, Dict, Optional

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
            "timestamp": datetime.utcnow().isoformat() + "Z",
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

    def closed_candle_skip(self, symbol: str, reason: str) -> None:
        self.log("closed_candle_skip", message=reason, symbol=symbol)

    def eod_export(self, path: str, message: str = "EOD export written") -> None:
        self.log("eod_export", message=message, export_path=path)
