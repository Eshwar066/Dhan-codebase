"""
Append-only CSV of open-position events from fills (paper + live) and broker-aligned
snapshots after reconciliation (live only). File: logs/{engine_id}_open_positions.csv
"""

from __future__ import annotations

import csv
import json
import os
import threading
from datetime import datetime
from typing import Any, Dict, Optional
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
    "strategy_meta",
]


def load_position_metadata_from_csv(csv_path: str) -> Dict[str, Dict[str, Any]]:
    """
    Replay {engine_id}_open_positions.csv and return trading_symbol -> metadata dict
    (strategy, structure_id, tag, intent_id, strategy_meta) for legs that are still
    open at end of log. Only ``source=fill`` rows drive open/close state; SYNC rows
    optional enrich when they have structure_id or strategy_meta.
    """
    if not csv_path or not os.path.isfile(csv_path):
        return {}

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return {}
        rows = list(reader)

    state: Dict[str, Optional[Dict[str, Any]]] = {}

    def _parse_net_qty(raw: str) -> int:
        if raw is None or str(raw).strip() == "":
            return 0
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return 0

    def _row_to_meta(row: dict) -> Dict[str, Any]:
        meta: Dict[str, Any] = {
            "strategy": (row.get("strategy") or "").strip() or None,
            "structure_id": (row.get("structure_id") or "").strip() or None,
            "tag": (row.get("tag") or "").strip() or None,
            "intent_id": (row.get("intent_id") or "").strip() or None,
        }
        sm = (row.get("strategy_meta") or "").strip()
        if sm:
            try:
                meta["strategy_meta"] = json.loads(sm)
            except json.JSONDecodeError:
                meta["strategy_meta"] = None
        else:
            meta["strategy_meta"] = None
        return {k: v for k, v in meta.items() if v is not None}

    for row in rows:
        sym = (row.get("symbol") or "").strip()
        if not sym:
            continue
        src = (row.get("source") or "").strip()

        if src == "fill":
            ev = (row.get("event") or "").strip()
            nq = _parse_net_qty(row.get("net_qty", ""))
            if ev == "CLOSE" or nq == 0:
                state[sym] = None
            else:
                m = _row_to_meta(row)
                if m:
                    state[sym] = m
        elif src == "broker_reconcile":
            m = _row_to_meta(row)
            if not m.get("structure_id") and not m.get("strategy_meta"):
                continue
            cur = dict(state.get(sym) or {}) if state.get(sym) else {}
            for k, v in m.items():
                if v not in (None, ""):
                    cur[k] = v
            if cur:
                state[sym] = cur

    out: Dict[str, Dict[str, Any]] = {}
    for sym, m in state.items():
        if m:
            out[sym] = m
    return out


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
        self._ensure_csv_has_strategy_meta_column()

    def _ensure_csv_has_strategy_meta_column(self) -> None:
        """One-time migrate older CSVs missing strategy_meta (rewrite in place)."""
        if not os.path.exists(self._path) or os.path.getsize(self._path) == 0:
            return
        with open(self._path, newline="", encoding="utf-8") as f:
            first = f.readline()
        if "strategy_meta" in first:
            return
        with open(self._path, newline="", encoding="utf-8") as f:
            old_rows = list(csv.DictReader(f))
        with open(self._path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDNAMES)
            w.writeheader()
            for r in old_rows:
                w.writerow({k: r.get(k, "") for k in FIELDNAMES})

    def _now(self) -> str:
        return datetime.now(IST).isoformat()

    def _append_row(self, row: dict) -> None:
        out = {k: row.get(k, "") for k in FIELDNAMES}
        sm = out.get("strategy_meta")
        if sm is not None and not isinstance(sm, str):
            out["strategy_meta"] = json.dumps(sm, default=str)
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
        strategy_meta: Optional[dict] = None,
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
                "strategy_meta": strategy_meta if strategy_meta is not None else "",
            }
        )

    def record_broker_reconcile_snapshot(self, position_manager: Any) -> None:
        """Live: one row per non-flat position after PM synced to broker."""
        for sym, pos in position_manager.positions.items():
            if pos.net_qty == 0:
                continue
            pm_bucket = getattr(position_manager, "position_metadata", {}).get(
                sym, {}
            ) or {}
            sm = pm_bucket.get("strategy_meta")
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
                    "strategy": (getattr(pos, "strategy", "") or pm_bucket.get("strategy") or ""),
                    "structure_id": getattr(pos, "structure_id", "")
                    or pm_bucket.get("structure_id")
                    or "",
                    "tag": getattr(pos, "tag", "") or pm_bucket.get("tag") or "",
                    "intent_id": getattr(pos, "intent_id", "")
                    or pm_bucket.get("intent_id")
                    or "",
                    "strategy_meta": sm if sm is not None else "",
                }
            )
