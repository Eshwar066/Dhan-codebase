"""Simulated broker for both PAPER and BACKTEST. No real exchange; instant fill. PAPER runs the same validations as LIVE (reconciliation, order-state check, trade-led sync)."""

import csv
import uuid
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.broker.base import BaseBroker
from core.models.order_intent import OrderIntent
from core.orderExecution.intent_store import IntentStatus
from core.utils.instruments.instrument_store import Instrument


class SimulatedBroker(BaseBroker):
    """Used for both PAPER and BACKTEST: instant fill, no real exchange. Same contract as live brokers so LiveEngine (PAPER) runs all validations."""

    def __init__(self, position_manager=None, intent_store=None, latency_ms=20):
        super().__init__(position_manager=position_manager, intent_store=intent_store)
        self.latency_ms = latency_ms
        # structure_id -> pending MAIN_SL / MAIN_TARGET (resting; evaluate_pending_stops)
        self._pending_sl: Dict[str, Dict[str, Any]] = {}
        self._pending_target: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _sl_orders_log_path(strategy: str) -> str:
        safe = (strategy or "GLOBAL").replace("/", "_").replace(" ", "_")
        base = Path(__file__).resolve().parents[4] / "logs" / safe
        base.mkdir(parents=True, exist_ok=True)
        return str(base / f"{safe}_sl_orders.csv")

    def _append_sl_order_event(self, strategy: str, row: Dict[str, Any]) -> None:
        path = self._sl_orders_log_path(strategy)
        fieldnames = [
            "event",
            "timestamp",
            "structure_id",
            "strategy",
            "symbol",
            "trigger_price",
            "intent_id",
            "fill_price",
            "detail",
        ]
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            if f.tell() == 0:
                w.writeheader()
            w.writerow({k: row.get(k, "") for k in fieldnames})

    def place_order(self, intent, execution_price=None, retries=0):
        order_id = f"SIM-{uuid.uuid4().hex[:10]}"
        if self.intent_store:
            self.intent_store.update(intent.intent_id, "SENT")
        if self.latency_ms:
            time.sleep(self.latency_ms / 1000)
        instrument = intent.instrument
        assert isinstance(instrument, Instrument), f"place_order expects Instrument, got {type(instrument)}"
        assert instrument.trading_symbol and instrument.custom_symbol

        _tag_m = str(getattr(intent, "tag", "") or "").upper()
        _act_m = str(getattr(intent, "action", "") or "").upper()
        if _tag_m == "MAIN_EXIT" and _act_m == "EXIT":
            _sid_m = getattr(intent, "structure_id", None)
            if _sid_m:
                self.cancel_pending_bracket(str(_sid_m), reason="MAIN_EXIT")

        tag_u = str(getattr(intent, "tag", "") or "").upper()
        act_u = str(getattr(intent, "action", "") or "").upper()
        if tag_u == "MAIN_SL" and act_u == "FORCE_EXIT":
            stid = str(getattr(intent, "structure_id", "") or "")
            trig = float(
                getattr(intent, "trigger_price", None)
                or getattr(intent, "price", None)
                or 0.0
            )
            strat = getattr(intent, "strategy", None) or "GLOBAL"
            side_u = str(getattr(intent, "side", "") or "").upper()
            # Short option cover: BUY SL when premium >= trigger. Long exit: SELL SL when premium <= trigger.
            trigger_when = "lte" if side_u == "SELL" else "gte"
            self._pending_sl[stid] = {
                "intent": intent,
                "trigger_price": trig,
                "instrument": instrument,
                "strategy": strat,
                "trigger_when": trigger_when,
            }
            ts = getattr(intent, "candle_ts", None)
            ts_s = (
                ts.strftime("%Y-%m-%d %H:%M:%S")
                if isinstance(ts, datetime)
                else (str(ts) if ts is not None else "")
            )
            self._append_sl_order_event(
                strat,
                {
                    "event": "ARMED",
                    "timestamp": ts_s,
                    "structure_id": stid,
                    "strategy": strat,
                    "symbol": instrument.trading_symbol,
                    "trigger_price": trig,
                    "intent_id": getattr(intent, "intent_id", ""),
                    "fill_price": "",
                    "detail": "simulated resting SL",
                },
            )
            return order_id

        if tag_u == "MAIN_TARGET" and act_u == "FORCE_EXIT":
            stid = str(getattr(intent, "structure_id", "") or "")
            trig = float(
                getattr(intent, "trigger_price", None)
                or getattr(intent, "price", None)
                or 0.0
            )
            strat = getattr(intent, "strategy", None) or "GLOBAL"
            side_u = str(getattr(intent, "side", "") or "").upper()
            trigger_when = "gte" if side_u == "SELL" else "lte"
            self._pending_target[stid] = {
                "intent": intent,
                "trigger_price": trig,
                "instrument": instrument,
                "strategy": strat,
                "trigger_when": trigger_when,
            }
            ts = getattr(intent, "candle_ts", None)
            ts_s = (
                ts.strftime("%Y-%m-%d %H:%M:%S")
                if isinstance(ts, datetime)
                else (str(ts) if ts is not None else "")
            )
            self._append_sl_order_event(
                strat,
                {
                    "event": "ARMED",
                    "timestamp": ts_s,
                    "structure_id": stid,
                    "strategy": strat,
                    "symbol": instrument.trading_symbol,
                    "trigger_price": trig,
                    "intent_id": getattr(intent, "intent_id", ""),
                    "fill_price": "",
                    "detail": "simulated resting TARGET",
                },
            )
            return order_id

        lot_size = int(getattr(instrument, "lot_size", 1) or 1)
        fill_units = max(1, int(getattr(intent, "qty", 1) or 1)) * lot_size

        if self.order_router:
            self.order_router.process_fill(
                instrument=instrument,
                side=intent.side,
                qty=fill_units,
                price=float(execution_price),
                expected_price=getattr(intent, "price", None),
                order_id=order_id,
                intent_id=intent.intent_id,
                strategy=getattr(intent, "strategy", None),
                candle_ts=getattr(intent, "candle_ts", None),
                tag=getattr(intent, "tag", None),
                structure_id=getattr(intent, "structure_id", None),
                action=getattr(intent, "action", None),
            )
        else:
            self.position_manager.on_fill(
                instrument=instrument,
                side=intent.side,
                qty=fill_units,
                price=float(execution_price),
                intent_id=intent.intent_id,
                order_id=order_id,
                strategy=getattr(intent, "strategy", None),
                candle_ts=getattr(intent, "candle_ts", None),
                tag=getattr(intent, "tag", None),
                structure_id=getattr(intent, "structure_id", None),
                action=getattr(intent, "action", None),
            )
            if self.intent_store:
                self.intent_store.update(intent.intent_id, "FILLED")
        return order_id

    def cancel_pending_sl(self, structure_id: str, *, detail: str = "MAIN_EXIT") -> None:
        """Remove resting MAIN_SL (OCO sibling fill or MAIN_EXIT)."""
        sid = str(structure_id)
        rec = self._pending_sl.pop(sid, None)
        if not rec:
            return
        self._cancel_bracket_record(rec, sid, detail=detail)

    def cancel_pending_target(self, structure_id: str, *, detail: str = "MAIN_EXIT") -> None:
        """Remove resting MAIN_TARGET (OCO sibling fill or MAIN_EXIT)."""
        sid = str(structure_id)
        rec = self._pending_target.pop(sid, None)
        if not rec:
            return
        self._cancel_bracket_record(rec, sid, detail=detail)

    def cancel_pending_bracket(self, structure_id: str, *, reason: str = "MAIN_EXIT") -> None:
        sid = str(structure_id)
        self.cancel_pending_sl(sid, detail=reason)
        self.cancel_pending_target(sid, detail=reason)

    def _cancel_bracket_record(self, rec: Dict[str, Any], sid: str, *, detail: str) -> None:
        intent = rec["intent"]
        strat = rec.get("strategy") or getattr(intent, "strategy", None) or "GLOBAL"
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._append_sl_order_event(
            strat,
            {
                "event": "CANCELLED",
                "timestamp": ts,
                "structure_id": sid,
                "strategy": strat,
                "symbol": getattr(intent.instrument, "trading_symbol", ""),
                "trigger_price": rec.get("trigger_price", ""),
                "intent_id": getattr(intent, "intent_id", ""),
                "fill_price": "",
                "detail": detail,
            },
        )
        if self.intent_store and getattr(intent, "intent_id", None):
            try:
                self.intent_store.update(
                    intent.intent_id,
                    IntentStatus.CANCELLED,
                    order_state="CANCELLED",
                )
            except Exception:
                pass

    def evaluate_pending_stops(
        self,
        order_router: Any,
        price_map: Dict[str, float],
        candle_ts: Any,
    ) -> None:
        """
        Resting MAIN_SL / MAIN_TARGET: SL lte/gte per side; target profit gte for long SELL.
        """
        if not order_router or not price_map:
            return
        self._evaluate_pending_book(
            order_router,
            price_map,
            candle_ts,
            book=self._pending_sl,
            fill_prefix="SIM-SL",
            exit_reason="SL",
            on_hit=lambda stid: self.cancel_pending_target(stid, detail="SL_hit"),
        )
        self._evaluate_pending_book(
            order_router,
            price_map,
            candle_ts,
            book=self._pending_target,
            fill_prefix="SIM-TGT",
            exit_reason="TARGET",
            on_hit=lambda stid: self.cancel_pending_sl(stid, detail="TARGET_hit"),
        )

    def _evaluate_pending_book(
        self,
        order_router: Any,
        price_map: Dict[str, float],
        candle_ts: Any,
        *,
        book: Dict[str, Dict[str, Any]],
        fill_prefix: str,
        exit_reason: str,
        on_hit,
    ) -> None:
        if not book:
            return
        for stid, rec in list(book.items()):
            inst = rec["instrument"]
            sym = inst.trading_symbol
            ltp = price_map.get(sym)
            if ltp is None:
                continue
            trig = float(rec["trigger_price"])
            when = str(rec.get("trigger_when") or "gte")
            ltp_f = float(ltp)
            if when == "lte":
                if ltp_f > trig + 1e-12:
                    continue
            elif ltp_f + 1e-12 < trig:
                continue
            intent = rec["intent"]
            del book[stid]
            if on_hit:
                on_hit(stid)
            strat = rec.get("strategy") or getattr(intent, "strategy", None) or "GLOBAL"
            ts = candle_ts
            ts_s = (
                ts.strftime("%Y-%m-%d %H:%M:%S")
                if isinstance(ts, datetime)
                else (str(ts) if ts is not None else "")
            )
            self._append_sl_order_event(
                strat,
                {
                    "event": "FILLED",
                    "timestamp": ts_s,
                    "structure_id": stid,
                    "strategy": strat,
                    "symbol": sym,
                    "trigger_price": trig,
                    "intent_id": getattr(intent, "intent_id", ""),
                    "fill_price": float(ltp),
                    "detail": f"{exit_reason} hit",
                },
            )
            oid = f"{fill_prefix}-{uuid.uuid4().hex[:10]}"
            order_router.process_fill(
                instrument=inst,
                side=intent.side,
                qty=intent.qty,
                price=float(ltp),
                expected_price=trig,
                order_id=oid,
                intent_id=intent.intent_id,
                strategy=getattr(intent, "strategy", None),
                candle_ts=candle_ts,
                tag=getattr(intent, "tag", None),
                structure_id=getattr(intent, "structure_id", None),
                action=getattr(intent, "action", None),
                exit_reason=exit_reason,
                execution_source=exit_reason,
            )

    def get_positions_for_recon(self):
        """Return PositionManager state in same format as live brokers so reconcile is a no-op (paper truth = PM)."""
        if not self.position_manager:
            return {}
        out = {}
        for sym, pos in self.position_manager.positions.items():
            if pos.net_qty == 0:
                continue
            inst = pos.instrument
            segment = getattr(inst, "segment", "EQ") or "EQ"
            lot_size = int(getattr(inst, "lot_size", 1) or 1)
            out[sym] = {
                "qty": pos.net_qty,
                "avg_price": float(pos.avg_price),
                "segment": segment,
                "lot_size": lot_size,
            }
        return out

    def get_open_orders(self) -> List[Dict[str, Any]]:
        """Paper: no open orders (instant fill). Same interface as live so order-state verification runs."""
        return []

    def get_recent_fills(self, page_size: int = 50) -> List[Dict[str, Any]]:
        """Paper: fills already applied in place_order via process_fill. Same interface as live so sync_trades runs."""
        return []

    def find_order_by_client_id(self, client_order_id: str) -> Optional[Dict[str, Any]]:
        """Paper: orders are filled immediately, so never in open list. Same interface as live."""
        return None

    def get_fill_for_client_order_id(
        self, client_order_id: str, page_size: int = 50
    ) -> Optional[Dict[str, Any]]:
        """Paper: fill already applied in place_order. Same interface as live for missing-order path."""
        return None

    def get_fill_by_order_id(
        self, broker_order_id: str, page_size: int = 50
    ) -> Optional[Dict[str, Any]]:
        """Paper: same as get_fill_for_client_order_id. Same interface as live."""
        return None

    def exit_position(self, trading_symbol, qty, side, segment="EQ", lot_size=1):
        exit_side = "SELL" if side == "BUY" else "BUY"
        # Minimal intent for simulated exit; real OrderIntent requires instrument
        intent = OrderIntent(
            intent_id=f"exit_{uuid.uuid4().hex[:6]}",
            instrument=Instrument(
                trading_symbol=trading_symbol,
                custom_symbol=trading_symbol,
                exchange="NSE",
                segment=segment,
                instrument_type="EQ",
                lot_size=lot_size,
            ),
            side=exit_side,
            qty=int(qty),
            price=0.0,
            order_type="MARKET",
            strategy="",
            structure_id="",
            trade_type="MARGIN",
            tag=None,
            symbol=trading_symbol,
            action="EXIT",
            candle_ts=datetime.now(),
        )
        return self.place_order(intent, execution_price=0.0)
