"""
Append-only CSV of open-position events from fills (paper + live) and broker-aligned
snapshots after reconciliation (live only). File: logs/{engine_id}_open_positions.csv
"""

from __future__ import annotations

import csv
import os
import threading
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

FIELDNAMES = [
    "timestamp",
    "engine_id",
    "venue",
    "run_mode",
    "source",
    "event",
    "symbol",
    "prev_qty",
    "net_qty",
    "avg_price",
    "strategy",
    "structure_id",
    "tag",
    "intent_id",
]


class OpenPositionsLogger:
    """
    - Fills (paper + live): one row per PositionManager.on_fill when qty changes.
    - Live only: after reconcile_with_broker, rows with source=broker_reconcile for each open leg.
    """

    def __init__(
        self,
        engine_id: str,
        venue: str,
        run_mode: Any,
        log_dir: str = "logs",
    ):
        self.engine_id = engine_id or "engine"
        self.venue = venue or ""
        self.run_mode = run_mode
        self._run_mode_str = (
            getattr(run_mode, "value", None) or str(run_mode) or ""
        )
        self._path = os.path.join(log_dir, f"{self.engine_id}_open_positions.csv")
        self._lock = threading.Lock()
        os.makedirs(log_dir, exist_ok=True)

    def _now(self) -> str:
        return datetime.now(IST).isoformat()

    def _append_row(self, row: dict) -> None:
        out = {k: row.get(k, "") for k in FIELDNAMES}
        with self._lock:
            write_header = not os.path.exists(self._path)
            with open(self._path, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=FIELDNAMES)
                if write_header:
                    w.writeheader()
                w.writerow(out)

    def record_fill(
        self,
        symbol: str,
        prev_qty: int,
        new_qty: int,
        avg_price: float,
        strategy: Optional[str],
        structure_id: Optional[str],
        tag: Optional[str],
        intent_id: Optional[str],
    ) -> None:
        if prev_qty == 0 and new_qty != 0:
            event = "OPEN"
        elif prev_qty != 0 and new_qty == 0:
            event = "CLOSE"
        else:
            event = "ADJUST"

        self._append_row(
            {
                "timestamp": self._now(),
                "engine_id": self.engine_id,
                "venue": self.venue,
                "run_mode": self._run_mode_str,
                "source": "fill",
                "event": event,
                "symbol": symbol,
                "prev_qty": prev_qty,
                "net_qty": new_qty,
                "avg_price": avg_price,
                "strategy": strategy or "",
                "structure_id": structure_id or "",
                "tag": tag or "",
                "intent_id": intent_id or "",
            }
        )

    def record_broker_reconcile_snapshot(self, position_manager: Any) -> None:
        """Live: one row per non-flat position after PM synced to broker."""
        for sym, pos in position_manager.positions.items():
            if pos.net_qty == 0:
                continue
            self._append_row(
                {
                    "timestamp": self._now(),
                    "engine_id": self.engine_id,
                    "venue": self.venue,
                    "run_mode": self._run_mode_str,
                    "source": "broker_reconcile",
                    "event": "SYNC",
                    "symbol": sym,
                    "prev_qty": "",
                    "net_qty": pos.net_qty,
                    "avg_price": pos.avg_price,
                    "strategy": getattr(pos, "strategy", "") or "",
                    "structure_id": getattr(pos, "structure_id", "") or "",
                    "tag": getattr(pos, "tag", "") or "",
                    "intent_id": getattr(pos, "intent_id", "") or "",
                }
            )
