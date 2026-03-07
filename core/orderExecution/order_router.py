import json
import time
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, Optional, Set, Tuple

OptionalAlert = Optional[Callable[[str], None]]
import pdb
import datetime

from core.orderExecution.intent_store import IntentStatus


class OrderState(str, Enum):
    """
    Local order state cache. Reconciliation only corrects drift; broker calls
    (find_order_by_client_id) are used only when we don't already have terminal state.
    """

    NEW = "NEW"  # Intent created, not yet sent
    SENT = "SENT"  # Sent to broker, ack not confirmed
    OPEN = "OPEN"  # Seen on broker open list (or acked)
    PARTIAL = "PARTIAL"  # Partially filled
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


# Terminal states: no need to poll broker for these
_TERMINAL_ORDER_STATES: Set[OrderState] = {
    OrderState.FILLED,
    OrderState.CANCELLED,
    OrderState.REJECTED,
    OrderState.EXPIRED,
}


class OrderRouter:
    def __init__(
        self,
        risk_manager,
        broker,
        intent_store,
        position_manager=None,
        slippage_model=None,
        engine_logger=None,
        instrument_store=None,  # Added for symbol resolution during adoption
        circuit_breaker_threshold: int = 5,
        slippage_threshold_pct: float = None,
        engine_id: Optional[str] = None,
        strategy_id: Optional[str] = None,
        telegram_alert: OptionalAlert = None,
    ):
        self.risk = risk_manager
        self.broker = broker
        self.intent_store = intent_store
        self.position_manager = position_manager
        self.slippage_model = slippage_model or (lambda price: price)
        self.engine_logger = engine_logger
        self.instrument_store = instrument_store
        self.circuit_breaker_threshold = circuit_breaker_threshold
        self.slippage_threshold_pct = slippage_threshold_pct
        self.engine_id = engine_id
        self.strategy_id = strategy_id
        self.telegram_alert = telegram_alert
        self._consecutive_failures = 0
        # Order state cache: intent_id -> OrderState. Persisted to logs/order_state_{engine_id}.json.
        self._order_state: Dict[str, OrderState] = {}
        _logs_dir = Path(__file__).resolve().parents[2] / "logs"
        _logs_dir.mkdir(parents=True, exist_ok=True)
        _safe_id = (engine_id or "default").replace(" ", "_").replace("/", "_")
        self._order_state_file = _logs_dir / f"order_state_{_safe_id}.json"
        self._load_order_state()
        self._rebuild_order_state_cache()

    def _load_order_state(self) -> None:
        """Load intent_id -> OrderState from logs/order_state_{engine_id}.json."""
        if not getattr(self, "_order_state_file", None) or not self._order_state_file.exists():
            return
        try:
            with open(self._order_state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for intent_id, val in (data if isinstance(data, dict) else {}).items():
                try:
                    self._order_state[intent_id] = (
                        OrderState(val) if isinstance(val, str) else val
                    )
                except (ValueError, TypeError):
                    pass
        except (json.JSONDecodeError, OSError):
            pass

    def _persist_order_state(self) -> None:
        """Write _order_state to logs/order_state_{engine_id}.json."""
        if not getattr(self, "_order_state_file", None):
            return
        try:
            data = {k: (v.value if isinstance(v, OrderState) else v) for k, v in self._order_state.items()}
            with open(self._order_state_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass

    def _set_order_state(self, intent_id: str, state: OrderState) -> None:
        """Update in-memory cache and persist to JSON."""
        self._order_state[intent_id] = state
        self._persist_order_state()

    def _rebuild_order_state_cache(self) -> None:
        """Merge IntentStore order states into _order_state (e.g. after restart). Then persist."""
        if not hasattr(self.intent_store, "get_all_order_states"):
            return
        for intent_id, order_state_val in self.intent_store.get_all_order_states():
            try:
                self._order_state[intent_id] = (
                    OrderState(order_state_val)
                    if isinstance(order_state_val, str)
                    else order_state_val
                )
            except (ValueError, TypeError):
                pass
        self._persist_order_state()

    def process_intent(self, intent, price_map, idempotency_key=None):
        if not self.risk.allow_intent(
            intent, price_map, candle_ts=getattr(intent, "candle_ts", None)
        ):
            self.intent_store.update(
                intent.intent_id, IntentStatus.REJECTED, order_state=OrderState.REJECTED
            )
            self._set_order_state(intent.intent_id, OrderState.REJECTED)
            return

        # Fix 3: Intent Deduplication (scoped by engine_id + strategy_id to support multi-engine/multi-strategy)
        intent_engine_id = getattr(intent, "engine_id", None) or self.engine_id
        intent_strategy_id = (
            getattr(intent, "strategy_id", None)
            or getattr(intent, "strategy_name", None)
            or self.strategy_id
        )
        if getattr(intent, "action", "") == "EXIT":
            pending = self.intent_store.list_by_status(
                IntentStatus.SENT
            ) + self.intent_store.list_by_status(IntentStatus.VALIDATED)
            symbol = (
                intent.instrument.trading_symbol
                if hasattr(intent, "instrument")
                else ""
            )
            for p in pending:
                p_payload = p.get("payload", {})
                if (
                    p_payload.get("symbol") == symbol
                    and p_payload.get("action") == "EXIT"
                    and p_payload.get("engine_id") == intent_engine_id
                    and p_payload.get("strategy_id") == intent_strategy_id
                ):
                    if self.engine_logger:
                        self.engine_logger.log(
                            "oms",
                            f"Exit intent for {symbol} already in flight; skipping",
                        )
                    return

        # Resolve execution price: intent.price first, else price_map (e.g. backtest candle close)
        exec_price = intent.price
        if exec_price is None and price_map:
            sym = (
                getattr(intent.instrument, "trading_symbol", None)
                if getattr(intent, "instrument", None)
                else None
            )
            if sym is not None:
                exec_price = price_map.get(sym)
        if exec_price is None:
            raise ValueError(
                f"No price available for intent {intent.intent_id} (intent.price=None and price_map has no "
                f"entry for {getattr(getattr(intent, 'instrument', None), 'trading_symbol', '?')})"
            )

        exec_price = self.slippage_model(exec_price)
        sym = intent.instrument.trading_symbol if hasattr(intent, "instrument") else ""
        side = getattr(intent, "side", "")
        qty = getattr(intent, "qty", 0)

        # Ensure intent exists in store (for fill sync and stale exit refresh)
        if not self.intent_store.exists(intent.intent_id):
            payload = {
                "symbol": sym,
                "side": side,
                "qty": qty,
                "action": getattr(intent, "action", "ENTRY"),
                "engine_id": intent_engine_id,
                "strategy_id": intent_strategy_id,
            }
            self.intent_store.create(
                payload=payload,
                intent_id=intent.intent_id,
                idempotency_key=idempotency_key if idempotency_key is not None else getattr(intent, "idempotency_key", None),
            )
            rec = self.intent_store.get(intent.intent_id)
            if rec and hasattr(intent, "instrument"):
                rec["instrument"] = intent.instrument

        # Fix 1: Persistence Before Flight
        self.intent_store.update(intent.intent_id, IntentStatus.VALIDATED)

        try:
            order_id = self.broker.place_order(intent, execution_price=exec_price)
        except Exception as e:
            self._consecutive_failures += 1
            if self.engine_logger:
                self.engine_logger.log("risk_block", f"Broker place_order failed: {e}")
            if self.telegram_alert:
                self.telegram_alert(f"Broker error: {sym} {side} qty={qty} — {e}")
            if (
                self._consecutive_failures >= self.circuit_breaker_threshold
                and self.risk
            ):
                self.risk.trigger_kill_switch("broker_failure")
                if self.engine_logger:
                    self.engine_logger.broker_circuit_breaker_triggered(
                        "broker_failure"
                    )
            self.intent_store.update(
                intent.intent_id, "REJECTED", order_state=OrderState.REJECTED
            )
            self._set_order_state(intent.intent_id, OrderState.REJECTED)
            return

        if order_id is None:
            self._consecutive_failures += 1
            if self.engine_logger:
                self.engine_logger.log("risk_block", "Broker place_order returned None")
            if self.telegram_alert:
                self.telegram_alert(f"Broker returned no order_id: {sym} {side} qty={qty}")
            if (
                self._consecutive_failures >= self.circuit_breaker_threshold
                and self.risk
            ):
                self.risk.trigger_kill_switch("broker_failure")
                if self.engine_logger:
                    self.engine_logger.broker_circuit_breaker_triggered(
                        "broker_failure"
                    )
            self.intent_store.update(
                intent.intent_id, "REJECTED", order_state=OrderState.REJECTED
            )
            self._set_order_state(intent.intent_id, OrderState.REJECTED)
            return

        self._consecutive_failures = 0
        self._set_order_state(intent.intent_id, OrderState.SENT)
        if self.telegram_alert:
            self.telegram_alert(f"Order placed: {sym} {side} qty={qty} order_id={order_id}")
        if self.engine_logger:
            self.engine_logger.order_placed(
                symbol=sym,
                side=side,
                qty=qty,
                price=exec_price,
                order_id=order_id,
                intent_id=getattr(intent, "intent_id", None),
            )
        self.intent_store.update(
            intent.intent_id,
            "SENT",
            broker_order_id=order_id,
            order_state=OrderState.SENT,
        )
        if getattr(intent, "action", "") == "EXIT":
            sent_rec = self.intent_store.get(intent.intent_id)
            if sent_rec:
                sent_rec["last_price_update_ts"] = time.time()

    def refresh_stale_exit_orders(
        self,
        get_bid_ask: Callable[[str], Tuple[float, float]],
        stale_seconds: float = 60,
    ) -> None:
        """
        If an open EXIT order has been sitting unfilled for >= stale_seconds,
        update its limit price to near bid (SELL) or near ask (BUY) and repeat until fill.
        Only runs when broker supports update_order_price (e.g. Delta).
        """
        if not hasattr(self.broker, "update_order_price"):
            return
        now = time.time()
        sent_exits = [
            i
            for i in self.intent_store.list_by_status(IntentStatus.SENT)
            if (i.get("payload") or {}).get("action") == "EXIT"
        ]
        for rec in sent_exits:
            intent_id = rec.get("intent_id")
            if not intent_id:
                continue

            # Use last_price_update_ts so only re-quote interval matters. Fallback to updated_at only when missing (not when 0).
            # Explicit 0 = "always stale" (adopted EXIT orphan from yesterday) so we must not fall back to updated_at.
            raw_ts = rec.get("last_price_update_ts")

            if raw_ts is None:
                last_price_ts = rec.get("updated_at") or 0
            else:
                last_price_ts = raw_ts
            try:
                last_price_ts = float(last_price_ts)
            except (TypeError, ValueError):
                last_price_ts = 0
            if last_price_ts <= 0:
                pass  # Treat as always stale (e.g. adopted orphan from yesterday)
            elif now - last_price_ts < stale_seconds:
                continue

            symbol = (rec.get("payload") or {}).get("symbol") or ""
            if not symbol:
                symbol = getattr(rec.get("instrument"), "trading_symbol", "") or ""
            if not symbol:
                if self.engine_logger:
                    self.engine_logger.log(
                        "oms", f"Refresh exit skip {intent_id}: no symbol"
                    )
                continue
            order_id = rec.get("broker_order_id")
            if not order_id:
                if self.engine_logger:
                    self.engine_logger.log(
                        "oms", f"Refresh exit skip {intent_id}: no broker_order_id"
                    )
                continue
            broker_order = None
            if hasattr(self.broker, "find_order_by_client_id"):
                broker_order = self.broker.find_order_by_client_id(intent_id)
            if not broker_order:
                if self.engine_logger:
                    self.engine_logger.log(
                        "oms",
                        f"Refresh exit skip {intent_id}: order not found at broker",
                    )
                continue
            status = (broker_order.get("status") or "").lower()
            open_states = {"open", "pending", "placed", "trigger pending"}
            if status not in open_states:
                if self.engine_logger:
                    self.engine_logger.log(
                        "oms",
                        f"Refresh exit skip {intent_id}: broker status={status} (not open)",
                    )
                continue
            product_id = broker_order.get("product_id")
            if product_id is None:
                if self.engine_logger:
                    self.engine_logger.log(
                        "oms", f"Refresh exit skip {intent_id}: no product_id"
                    )
                continue
            bid, ask = get_bid_ask(symbol)
            side = (rec.get("side") or rec.get("payload", {}).get("side") or "").upper()
            if side == "SELL":
                new_price = bid
            else:
                new_price = ask
            if new_price is None or new_price <= 0:
                if self.engine_logger:
                    self.engine_logger.log(
                        "oms", f"Refresh exit skip {intent_id}: no bid/ask for {symbol}"
                    )
                continue
            try:
                ok = self.broker.update_order_price(
                    product_id=int(product_id),
                    order_id=str(order_id),
                    new_limit_price=float(new_price),
                )
                if ok and self.engine_logger:
                    self.engine_logger.log(
                        "oms",
                        f"Refreshed exit order {intent_id} at {new_price} (near {'bid' if side == 'SELL' else 'ask'})",
                    )
                if ok:
                    self.intent_store.update(intent_id, IntentStatus.SENT)
                    rec = self.intent_store.get(intent_id)
                    if rec:
                        rec["last_price_update_ts"] = now
            except Exception as e:
                if self.engine_logger:
                    self.engine_logger.log("oms", f"Refresh exit order failed: {e}")

    def verify_open_orders_with_broker(self) -> Tuple[bool, Dict]:
        """
        Compare broker open orders with local IntentStore (SENT/VALIDATED).
        Attempts to resolve mismatches by updating local records.
        Returns (ok: bool, details: dict).
        """
        if not hasattr(self.broker, "get_open_orders"):
            return True, {}
        try:
            broker_open = self.broker.get_open_orders()
        except Exception as e:
            if self.engine_logger:
                self.engine_logger.order_state_mismatch(
                    f"Failed to fetch broker open orders: {e}"
                )
            return False, {"error": str(e)}

        # Consider both VALIDATED (in flight) and SENT
        local_pending = self.intent_store.list_by_status(
            IntentStatus.SENT
        ) + self.intent_store.list_by_status(IntentStatus.VALIDATED)

        local_intent_ids = {
            i.get("intent_id") for i in local_pending if i.get("intent_id")
        }
        broker_tags = {o.get("tag") for o in broker_open if o.get("tag")}
        # broker_order_ids = {o.get("order_id") for o in broker_open}

        # 1. Orphans: On broker but not in local pending
        # We might have recorded them earlier, so check if they exist AT ALL in intent_store
        orphans = []
        for o in broker_open:
            tag = o.get("tag")
            if not tag:
                continue

            if not self.intent_store.exists(tag):
                orphans.append(o)
                # Orphan Adoption: Create local record for pre-existing broker order
                b_sym = o.get("symbol") or o.get("product_symbol")
                product_id = o.get("product_id")

                engine_sym = b_sym
                instr = None
                if self.instrument_store and b_sym:
                    inst = None
                    if hasattr(self.instrument_store, "get_by_symbol"):
                        inst = self.instrument_store.get_by_symbol(b_sym)
                    if (
                        not inst
                        and product_id
                        and hasattr(self.instrument_store, "get_by_product_id")
                    ):
                        inst = self.instrument_store.get_by_product_id(product_id)
                    if not inst and hasattr(
                        self.instrument_store, "intent_creation_details"
                    ):
                        inst = self.instrument_store.intent_creation_details(
                            b_sym, None, None, None, None
                        )
                    if not inst and hasattr(
                        self.instrument_store, "futures_intent_creation_details"
                    ):
                        inst = self.instrument_store.futures_intent_creation_details(
                            b_sym, "DELTA", None
                        )
                    if inst:
                        engine_sym = inst.trading_symbol
                        instr = inst

                # Detect EXIT vs ENTRY from broker (e.g. Delta reduce_only)
                is_reduce = o.get("reduce_only") in (True, "true", "yes", 1)
                action = "EXIT" if is_reduce else "ENTRY"
                stub_payload = {
                    "symbol": engine_sym,
                    "side": (o.get("side") or "").upper(),
                    "qty": int(o.get("qty") or 0),
                    "action": action,
                    "strategy": "recovery",
                    "structure_id": f"recovered:{engine_sym}",
                    "candle_ts": None,
                    "engine_id": self.engine_id,
                    "strategy_id": self.strategy_id,
                }

                # Register in store
                self.intent_store.create(payload=stub_payload, intent_id=tag)
                self.intent_store.update(
                    tag,
                    IntentStatus.SENT,
                    broker_order_id=o.get("order_id"),
                    order_state=OrderState.OPEN,
                )
                self._set_order_state(tag, OrderState.OPEN)  # Seen on broker

                # Augment record for process_fill
                intent_record = self.intent_store.get(tag)
                intent_record["instrument"] = instr
                intent_record["side"] = (o.get("side") or "").upper()
                intent_record["qty"] = int(o.get("qty") or 0)
                intent_record["action"] = stub_payload["action"]
                # EXIT orphans (e.g. open from yesterday): set last_price_update_ts=0 so next refresh run re-quotes immediately
                if action == "EXIT":
                    intent_record["last_price_update_ts"] = 0

                if self.engine_logger:
                    self.engine_logger.log(
                        "oms", f"Adopted orphan order {tag} for {engine_sym}"
                    )

            elif tag in local_intent_ids:
                # Local thinks it's pending, broker confirms it's open. Sync order ID and persist OPEN.
                self._set_order_state(tag, OrderState.OPEN)
                intent = self.intent_store.get(tag)
                self.intent_store.update(
                    tag,
                    IntentStatus.SENT,
                    broker_order_id=intent.get("broker_order_id") or o.get("order_id"),
                    order_state=OrderState.OPEN,
                )

        # 2. Missing: In local pending but not on broker open list
        # Usually FILLED/REJECTED/CANCELLED. Only poll broker when cache doesn't have terminal state.
        missing = [
            i
            for i in local_pending
            if i.get("intent_id") and i.get("intent_id") not in broker_tags
        ]
        missing_needing_poll = [
            i
            for i in missing
            if self._order_state.get(i.get("intent_id")) not in _TERMINAL_ORDER_STATES
        ]

        if missing_needing_poll and hasattr(self.broker, "find_order_by_client_id"):
            time.sleep(0.5)  # Let broker open list settle (recent fills may drop off)

        for i in missing:
            tag = i.get("intent_id")
            if self._order_state.get(tag) in _TERMINAL_ORDER_STATES:
                continue  # Already resolved locally; no broker call
            if hasattr(self.broker, "find_order_by_client_id"):
                try:
                    order = self.broker.find_order_by_client_id(tag)
                    if order:
                        status = (order.get("status") or "").lower()
                        filled = (
                            float(order["filled_size"])
                            if order.get("filled_size") is not None
                            else (
                                float(order.get("size", 0))
                                - float(order.get("unfilled_size", 0))
                            )
                        )
                        size = float(order.get("size", 0))

                        # Partial fill: filled > 0 and unfilled > 0 (filled < size)
                        if size > 0 and filled > 0 and filled < size:
                            self._set_order_state(tag, OrderState.PARTIAL)
                            self.intent_store.update(
                                tag,
                                IntentStatus.SENT,  # Still in flight
                                broker_order_id=order.get("order_id"),
                                order_state=OrderState.PARTIAL,
                            )
                            if self.position_manager:
                                self.process_fill(
                                    instrument=i.get("instrument"),
                                    side=i.get("side"),
                                    qty=filled,
                                    price=float(
                                        order.get("average_fill_price")
                                        or i.get("price", 0)
                                    ),
                                    order_id=order.get("order_id"),
                                    intent_id=tag,
                                    strategy=i.get("strategy"),
                                    structure_id=i.get("structure_id"),
                                    tag=i.get("tag"),
                                    candle_ts=i.get("candle_ts"),
                                    action=i.get("action"),
                                )
                        elif status == "filled" or (size > 0 and filled >= size):
                            if self.engine_logger:
                                self.engine_logger.log(
                                    "oms",
                                    f"Syncing fill for {tag} discovered via polling",
                                )

                            # Reconstruct fill from broker data and intent record
                            # Note: In a real system, we'd ideally have the original OrderIntent object.
                            # Since we don't have it here easily (intent_store stores dicts),
                            # we'll use the values from the dict.
                            payload = i.get("payload", {})
                            instr = i.get(
                                "instrument"
                            )  # If stored in dict; depends on intent_store implementation

                            self._set_order_state(tag, OrderState.FILLED)
                            self.intent_store.update(
                                tag,
                                IntentStatus.FILLED,
                                broker_order_id=order.get("order_id"),
                                order_state=OrderState.FILLED,
                            )

                            if self.position_manager:
                                self.process_fill(
                                    instrument=i.get("instrument"),
                                    side=i.get("side"),
                                    qty=filled,
                                    price=float(
                                        order.get("average_fill_price")
                                        or i.get("price", 0)
                                    ),
                                    order_id=order.get("order_id"),
                                    intent_id=tag,
                                    strategy=i.get("strategy"),
                                    structure_id=i.get("structure_id"),
                                    tag=i.get("tag"),
                                    candle_ts=i.get("candle_ts"),
                                    action=i.get("action"),
                                )

                        elif status in ("cancelled", "rejected", "expired"):
                            ost = (
                                OrderState.CANCELLED
                                if status == "cancelled"
                                else (
                                    OrderState.REJECTED
                                    if status == "rejected"
                                    else OrderState.EXPIRED
                                )
                            )
                            self._set_order_state(tag, ost)
                            self.intent_store.update(
                                tag, IntentStatus.REJECTED, order_state=ost
                            )
                except Exception as e:
                    if self.engine_logger:
                        self.engine_logger.log(
                            "oms", f"Failed to sync status for {tag}: {e}"
                        )

        diff = {
            "orphan_broker_orders": len(orphans),
            "missing_local_records": len(missing),
        }

        if orphans or missing:
            if self.engine_logger:
                self.engine_logger.order_state_mismatch(
                    "Order state mismatch detected", details=diff
                )
            return False, diff

        return True, {}

    def process_fill(
        self,
        instrument,
        side,
        qty,
        price,
        expected_price=None,
        order_id=None,
        intent_id=None,
        strategy=None,
        structure_id=None,
        tag=None,
        candle_ts=None,
        action=None,
    ):
        """
        Single entry point for fill processing. Call from broker fill callback or LiveEngine.
        Updates position via PositionManager.on_fill(); if position closed, records realized PnL
        with RiskManager for daily_max_loss enforcement. Then logs and runs slippage check.
        """
        if not self.position_manager:
            self.report_fill(
                getattr(instrument, "trading_symbol", ""),
                side,
                qty,
                expected_price,
                price,
                order_id=order_id,
                intent_id=intent_id,
            )
            return
        position_closed, realized_pnl = self.position_manager.on_fill(
            instrument=instrument,
            side=side,
            qty=qty,
            price=price,
            intent_id=intent_id,
            order_id=order_id,
            strategy=strategy,
            structure_id=structure_id,
            tag=tag,
            candle_ts=candle_ts,
            action=action,
        )
        if position_closed and realized_pnl is not None:
            self.risk.record_realized_pnl(realized_pnl)
        sym = getattr(instrument, "trading_symbol", "")
        self.report_fill(
            sym,
            side,
            qty,
            expected_price,
            price,
            order_id=order_id,
            intent_id=intent_id,
        )
        if intent_id and self.intent_store:
            self._set_order_state(intent_id, OrderState.FILLED)
            self.intent_store.update(
                intent_id,
                IntentStatus.FILLED,
                broker_order_id=order_id,
                order_state=OrderState.FILLED,
            )

    def report_fill(
        self,
        symbol,
        side,
        qty,
        expected_price,
        fill_price,
        order_id=None,
        intent_id=None,
    ):
        """Logs order_filled and high_slippage_warning if above threshold. Called by process_fill or legacy paths."""
        if self.engine_logger:
            self.engine_logger.order_filled(
                symbol=symbol, side=side, qty=qty, price=fill_price, order_id=order_id
            )
        if (
            self.slippage_threshold_pct is not None
            and expected_price
            and expected_price > 0
            and fill_price is not None
        ):
            pct = abs(fill_price - expected_price) / expected_price
            if pct > self.slippage_threshold_pct:
                if self.engine_logger:
                    self.engine_logger.high_slippage_warning(
                        symbol=symbol,
                        expected_price=expected_price,
                        fill_price=fill_price,
                        slippage_pct=pct * 100,
                    )
                if self.telegram_alert:
                    self.telegram_alert(
                        f"High slippage: {symbol} expected={expected_price:.2f} fill={fill_price:.2f} ({pct * 100:.2f}%)"
                    )
