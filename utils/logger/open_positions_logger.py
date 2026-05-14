"""
CSV snapshot of currently open positions only (fills + live broker reconcile).
Closed legs are removed when net qty reaches zero; file is rewritten on each update.
File: logs/{engine_id}_open_positions.csv
"""

from __future__ import annotations

import csv
import json
import os
import threading
from datetime import datetime
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

try:
    from core.utils.json_numeric import round_json_floats
except ImportError:
    round_json_floats = None  # type: ignore

IST = ZoneInfo("Asia/Kolkata")

def _parse_net_qty(raw: Optional[str]) -> int:
    if raw is None or str(raw).strip() == "":
        return 0
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return 0


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
    "magicalLine",
    "level",
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
            nq = _parse_net_qty(str(row.get("net_qty", "") or ""))
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
    - Fills (paper + live): updates that symbol's row when qty changes; removes the row on full exit.
    - Live only: after reconcile_with_broker, replaces the file with one broker_reconcile row per open leg.
    """

    def __init__(
        self,
        engine_id: str,
        venue: str,
        run_mode: Any,
        strategy: Optional[str] = None,
        log_dir: str = "logs",
    ):
        self.engine_id = engine_id or "engine"
        self.venue = venue or ""
        self.strategy = strategy or "GLOBAL"
        self._base_log_root = log_dir
        self.run_mode = run_mode
        self._run_mode_str = (
            getattr(run_mode, "value", None) or str(run_mode) or ""
        )
        safe_strategy = str(self.strategy).replace("/", "_").replace("\\", "_").replace(" ", "_")
        strategy_dir = os.path.join(log_dir, safe_strategy)
        os.makedirs(strategy_dir, exist_ok=True)
        self._path = os.path.join(strategy_dir, f"{self.engine_id}_open_positions.csv")
        self._lock = threading.Lock()
        os.makedirs(log_dir, exist_ok=True)
        self._ensure_csv_schema()
        self._compact_legacy_to_snapshot()

    @staticmethod
    def _safe_strategy_name(name: Optional[str]) -> str:
        return str(name or "GLOBAL").replace("/", "_").replace("\\", "_").replace(" ", "_")

    def _path_for_strategy(self, strategy: Optional[str]) -> str:
        safe_strategy = self._safe_strategy_name(strategy)
        strategy_dir = os.path.join(self._base_log_root, safe_strategy)
        os.makedirs(strategy_dir, exist_ok=True)
        return os.path.join(strategy_dir, f"{self.engine_id}_open_positions.csv")

    def _compact_legacy_to_snapshot(self) -> None:
        """On startup, collapse older append-only logs to one row per still-open symbol."""
        if not os.path.exists(self._path) or os.path.getsize(self._path) == 0:
            return
        with self._lock:
            snap = self._read_open_snapshot()
            self._write_snapshot(snap)

    def _ensure_csv_schema(self) -> None:
        """One-time migrate older CSVs when new columns are introduced (rewrite in place)."""
        if not os.path.exists(self._path) or os.path.getsize(self._path) == 0:
            return
        with open(self._path, newline="", encoding="utf-8") as f:
            first = f.readline()
        if all(col in first for col in ("strategy_meta", "magicalLine", "level")):
            return
        with open(self._path, newline="", encoding="utf-8") as f:
            old_rows = list(csv.DictReader(f))
        with open(self._path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDNAMES)
            w.writeheader()
            for r in old_rows:
                row = {k: r.get(k, "") for k in FIELDNAMES}
                if not str(row.get("magicalLine", "")).strip() and r.get("ml1"):
                    row["magicalLine"] = r["ml1"]
                w.writerow(row)

    def _now(self) -> str:
        return datetime.now(IST).isoformat()

    def _finalize_row_for_csv(self, row: dict) -> Dict[str, Any]:
        out = {k: row.get(k, "") for k in FIELDNAMES}
        sm = out.get("strategy_meta")
        sm_obj = None
        if sm is not None and not isinstance(sm, str):
            sm_obj = sm
            sm_r = round_json_floats(sm) if round_json_floats else sm
            out["strategy_meta"] = json.dumps(sm_r, default=str)
        elif isinstance(sm, str) and sm.strip():
            try:
                sm_obj = json.loads(sm)
            except json.JSONDecodeError:
                sm_obj = None
        if sm_obj is None and isinstance(sm, dict):
            sm_obj = sm

        # Convenience columns for quick grep/reporting on OneDayMagicalLine rows.
        if out.get("magicalLine", "") in ("", None) or out.get("level", "") in ("", None):
            odml = None
            if isinstance(sm_obj, dict):
                odml = sm_obj.get("one_day_magical_line") or sm_obj.get("one_day_ml1")
            if isinstance(odml, dict):
                if out.get("magicalLine", "") in ("", None):
                    out["magicalLine"] = odml.get(
                        "magicalLine", odml.get("ml1", "")
                    )
                if out.get("level", "") in ("", None):
                    out["level"] = odml.get("level", "")
        if out.get("avg_price", "") not in ("", None):
            try:
                out["avg_price"] = round(float(out["avg_price"]), 2)
            except (TypeError, ValueError):
                pass
        return out

    def _read_open_snapshot(self, path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """
        Last row wins per symbol; keep only symbols that are still open (net_qty != 0
        and not a fill CLOSE). Supports legacy append-only files until rewritten.
        """
        target_path = path or self._path
        if not os.path.exists(target_path) or os.path.getsize(target_path) == 0:
            return {}
        with open(target_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return {}
            rows = list(reader)
        last_by_sym: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            sym = (row.get("symbol") or "").strip()
            if sym:
                last_by_sym[sym] = row

        open_rows: Dict[str, Dict[str, Any]] = {}
        for sym, row in last_by_sym.items():
            nq = _parse_net_qty(str(row.get("net_qty") or ""))
            ev = (row.get("event") or "").strip()
            src = (row.get("source") or "").strip()
            if nq == 0:
                continue
            if src == "fill" and ev == "CLOSE":
                continue
            open_rows[sym] = row
        return open_rows

    def _write_snapshot(
        self, rows_by_symbol: Dict[str, Dict[str, Any]], path: Optional[str] = None
    ) -> None:
        target_path = path or self._path
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDNAMES)
            w.writeheader()
            for sym in sorted(rows_by_symbol.keys()):
                r = rows_by_symbol[sym]
                w.writerow({k: r.get(k, "") for k in FIELDNAMES})

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

        finalized = self._finalize_row_for_csv(
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
        with self._lock:
            # Keep legacy engine-primary snapshot for compatibility.
            snap = self._read_open_snapshot()
            if new_qty == 0:
                snap.pop(symbol, None)
            else:
                snap[symbol] = finalized
            self._write_snapshot(snap)

            # Also maintain strategy-specific snapshot.
            row_strategy = str(finalized.get("strategy") or "").strip() or self.strategy
            strategy_path = self._path_for_strategy(row_strategy)
            strat_snap = self._read_open_snapshot(strategy_path)
            if new_qty == 0:
                strat_snap.pop(symbol, None)
            else:
                strat_snap[symbol] = finalized
            self._write_snapshot(strat_snap, strategy_path)

    def record_broker_reconcile_snapshot(self, position_manager: Any) -> None:
        """Live: replace file with one row per non-flat position after PM synced to broker."""
        snap: Dict[str, Dict[str, Any]] = {}
        for sym, pos in position_manager.positions.items():
            if pos.net_qty == 0:
                continue
            pm_bucket = getattr(position_manager, "position_metadata", {}).get(
                sym, {}
            ) or {}
            sm = pm_bucket.get("strategy_meta")
            snap[sym] = self._finalize_row_for_csv(
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
        with self._lock:
            self._write_snapshot(snap)
            # Strategy-wise snapshots (for multi-strategy engines).
            by_strategy: Dict[str, Dict[str, Dict[str, Any]]] = {}
            for sym, row in snap.items():
                strategy_name = str(row.get("strategy") or "").strip() or self.strategy
                bucket = by_strategy.setdefault(strategy_name, {})
                bucket[sym] = row
            for strategy_name, strategy_rows in by_strategy.items():
                self._write_snapshot(strategy_rows, self._path_for_strategy(strategy_name))
