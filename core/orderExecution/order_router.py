import json
import logging
import time
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

# Trade-led OMS: positions are updated only from trade events (fills), not from order state.

OptionalAlert = Optional[Callable[[str], None]]
import pdb
import datetime

logger = logging.getLogger(__name__)

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
        # Orphan fill sync (no intent match): ignore stale / pre-session broker rows
        max_orphan_fill_age_seconds: Optional[float] = 300,
        reject_orphan_fills_before_oms_session: bool = True,
        reject_orphan_fill_if_predates_position_open: bool = True,
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
        self.max_orphan_fill_age_seconds = max_orphan_fill_age_seconds
        self.reject_orphan_fills_before_oms_session = (
            reject_orphan_fills_before_oms_session
        )
        self.reject_orphan_fill_if_predates_position_open = (
            reject_orphan_fill_if_predates_position_open
        )
        self._consecutive_failures = 0
        # Order state cache: intent_id -> OrderState. Persisted to logs/order_state_{engine_id}.json.
        self._order_state: Dict[str, OrderState] = {}
        self._order_state_log: List[Dict[str, Any]] = []
        self._order_state_log_max = 5000
        # Trade-led: only apply each trade once; positions = f(trades), not f(order state)
        self._processed_trade_ids: Set[str] = set()
        self._processed_trade_ids_max = 10000
        # EXTERNAL_CLOSE: additive confidence (see _external_close_confidence_score)
        self._orphan_close_score_threshold = 6
        self._orphan_close_suspect_floor = 5
        _strategy_dir = (
            str(self.strategy_id or "GLOBAL").replace(" ", "_").replace("/", "_")
        )
        _logs_dir = Path(__file__).resolve().parents[2] / "logs" / _strategy_dir
        _logs_dir.mkdir(parents=True, exist_ok=True)
        _safe_id = (engine_id or "default").replace(" ", "_").replace("/", "_")
        self._order_state_file = _logs_dir / f"order_state_{_safe_id}.json"
        self._load_order_state()
        self._rebuild_order_state_cache()
        # Fills before this instant are ignored for orphan EXTERNAL_CLOSE / LIQUIDATION / ADL paths.
        self._oms_session_start_unix = time.time()

    def reset_oms_session_boundary(self) -> None:
        """Call when starting a new trading session (same process) to tighten orphan fill acceptance."""
        self._oms_session_start_unix = time.time()

    def _load_order_state(self) -> None:
        """Load intent_id -> OrderState and optional action log from logs/order_state_{engine_id}.json."""
        if (
            not getattr(self, "_order_state_file", None)
            or not self._order_state_file.exists()
        ):
            return
        try:
            with open(self._order_state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return
            # New format: { "states": {...}, "log": [...] }
            if "states" in data:
                for intent_id, val in data["states"].items():
                    try:
                        self._order_state[intent_id] = (
                            OrderState(val) if isinstance(val, str) else val
                        )
                    except (ValueError, TypeError):
                        pass
                self._order_state_log = data.get("log") or []
            else:
                # Legacy: flat intent_id -> state
                for intent_id, val in data.items():
                    try:
                        self._order_state[intent_id] = (
                            OrderState(val) if isinstance(val, str) else val
                        )
                    except (ValueError, TypeError):
                        pass
                self._order_state_log = []
        except (json.JSONDecodeError, OSError):
            pass

    def _persist_order_state(self) -> None:
        """Write _order_state and action log to logs/order_state_{engine_id}.json."""
        if not getattr(self, "_order_state_file", None):
            return
        try:
            states = {
                k: (v.value if isinstance(v, OrderState) else v)
                for k, v in self._order_state.items()
            }
            log = getattr(self, "_order_state_log", [])
            data = {"states": states, "log": log}
            with open(self._order_state_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass

    def _set_order_state(
        self,
        intent_id: str,
        state: OrderState,
        action: Optional[str] = None,
        message: Optional[str] = None,
    ) -> None:
        """Update in-memory cache, append detailed log entry, and persist to JSON."""
        self._order_state[intent_id] = state
        state_val = state.value if isinstance(state, OrderState) else state
        entry = {
            "timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[
                :-3
            ]
            + "Z",
            "intent_id": intent_id,
            "state": state_val,
            "action": action or "set",
            "message": message or "",
        }
        log = getattr(self, "_order_state_log", [])
        log.append(entry)
        if len(log) > getattr(self, "_order_state_log_max", 500):
            self._order_state_log = log[-self._order_state_log_max :]
        else:
            self._order_state_log = log
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
        # Append one log entry for this rebuild (no single intent_id)
        log = getattr(self, "_order_state_log", [])
        log.append(
            {
                "timestamp": datetime.datetime.utcnow().strftime(
                    "%Y-%m-%dT%H:%M:%S.%f"
                )[:-3]
                + "Z",
                "intent_id": "",
                "state": "",
                "action": "cache_rebuild",
                "message": "Merged order states from intent_store at startup",
            }
        )
        if len(log) > getattr(self, "_order_state_log_max", 500):
            self._order_state_log = log[-self._order_state_log_max :]
        else:
            self._order_state_log = log
        self._persist_order_state()

    def process_intent(self, intent, price_map, idempotency_key=None):
        if not self.risk.allow_intent(
            intent, price_map, candle_ts=getattr(intent, "candle_ts", None)
        ):
            self.intent_store.update(
                intent.intent_id, IntentStatus.REJECTED, order_state=OrderState.REJECTED
            )
            self._set_order_state(
                intent.intent_id,
                OrderState.REJECTED,
                action="risk_rejected",
                message="Risk manager did not allow intent",
            )
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

        # Resolve execution price: always prefer price_map (engine updates it with best bid/ask)
        sym = (
            getattr(intent.instrument, "trading_symbol", None)
            if getattr(intent, "instrument", None)
            else None
        )
        exec_price = None
        
        if price_map and sym is not None:
            exec_price = price_map.get(sym)
        if exec_price is None:
            exec_price = intent.price
        if exec_price is None:
            raise ValueError(
                f"No price available for intent {intent.intent_id} (price_map has no "
                f"entry for {sym!r} and intent.price is None)"
            )

        exec_price = self.slippage_model(exec_price)
        sym = intent.instrument.trading_symbol if hasattr(intent, "instrument") else ""
        side = getattr(intent, "side", "")
        qty = getattr(intent, "qty", 0)
        action = getattr(intent, "action", "ENTRY")

        # ENTRY → check margin. EXIT / FORCE_EXIT → NEVER check margin (otherwise you cannot close positions).
        if action not in ("EXIT", "FORCE_EXIT"):
            funds_check = getattr(
                self.broker, "check_funds_before_order", lambda _i, _p: None
            )(intent, exec_price)
            if funds_check is not None and funds_check.get("ok") is False:
                shortfall = funds_check.get("shortfall", 0)
                msg = funds_check.get("message") or "Insufficient funds"
                if self.engine_logger:
                    self.engine_logger.log(
                        "risk_block",
                        f"Funds check failed: {msg} (shortfall={shortfall})",
                    )
                if self.telegram_alert:
                    self.telegram_alert(
                        f"⚠️ Order blocked – insufficient funds: {sym} {side} qty={qty}. {msg} Shortfall: {shortfall}"
                    )
                self.intent_store.update(
                    intent.intent_id, IntentStatus.REJECTED, order_state=OrderState.REJECTED
                )
                self._set_order_state(
                    intent.intent_id,
                    OrderState.REJECTED,
                    action="insufficient_funds",
                    message=msg,
                )
                return

        # Ensure intent exists in store (for fill sync and stale exit refresh)
        if not self.intent_store.exists(intent.intent_id):
            payload = {
                "symbol": sym,
                "side": side,
                "qty": qty,
                "action": getattr(intent, "action", "ENTRY"),
                "engine_id": intent_engine_id,
                "strategy_id": intent_strategy_id,
                "structure_id": getattr(intent, "structure_id", None),
                "tag": getattr(intent, "tag", None),
            }
            _extras = getattr(intent, "metadata_extras", None)
            if _extras is not None:
                payload["strategy_meta"] = _extras
            self.intent_store.create(
                payload=payload,
                intent_id=intent.intent_id,
                idempotency_key=(
                    idempotency_key
                    if idempotency_key is not None
                    else getattr(intent, "idempotency_key", None)
                ),
            )
            rec = self.intent_store.get(intent.intent_id)
            if rec:
                if hasattr(intent, "instrument"):
                    rec["instrument"] = intent.instrument
                rec["strategy"] = intent_strategy_id
                rec["structure_id"] = getattr(intent, "structure_id", None)
                rec["tag"] = getattr(intent, "tag", None)
                rec["action"] = getattr(intent, "action", "ENTRY")

        # Keep intent record metadata in sync when intent already existed (e.g. idempotency retry)
        rec = self.intent_store.get(intent.intent_id)
        if rec:
            rec["strategy"] = intent_strategy_id
            rec["structure_id"] = getattr(intent, "structure_id", None)
            rec["tag"] = getattr(intent, "tag", None)
            rec["action"] = getattr(intent, "action", "ENTRY")
            if hasattr(intent, "instrument"):
                rec["instrument"] = intent.instrument
            pay = rec.get("payload") or {}
            if getattr(intent, "structure_id", None) is not None:
                pay["structure_id"] = intent.structure_id
            if getattr(intent, "tag", None) is not None:
                pay["tag"] = intent.tag
            _extras = getattr(intent, "metadata_extras", None)
            if _extras is not None:
                pay["strategy_meta"] = _extras
            rec["payload"] = pay

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
            self._set_order_state(
                intent.intent_id,
                OrderState.REJECTED,
                action="broker_error",
                message=f"place_order failed: {e}",
            )
            return

        if order_id is None:
            self._consecutive_failures += 1
            if self.engine_logger:
                self.engine_logger.log("risk_block", "Broker place_order returned None")
            else:
                logger.warning("Broker place_order returned None for %s %s qty=%s", sym, side, qty)
            if self.telegram_alert:
                self.telegram_alert(
                    f"Broker returned no order_id: {sym} {side} qty={qty}"
                )
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
            self._set_order_state(
                intent.intent_id,
                OrderState.REJECTED,
                action="broker_no_order_id",
                message="Broker place_order returned None",
            )
            return

        self._consecutive_failures = 0
        # Paper/sim broker may call process_fill inside place_order, so intent can already be FILLED.
        # Do not overwrite terminal status with SENT so has_pending_intent stays correct.
        rec = self.intent_store.get(intent.intent_id)
        already_terminal = rec and rec.get("status") in (
            IntentStatus.FILLED,
            IntentStatus.REJECTED,
            IntentStatus.CANCELLED,
            IntentStatus.EXPIRED,
        )
        if not already_terminal:
            self._set_order_state(
                intent.intent_id,
                OrderState.SENT,
                action="order_placed",
                message=f"order_id={order_id}",
            )
            if self.telegram_alert:
                self.telegram_alert(
                    f"Order placed: {sym} {side} qty={qty} order_id={order_id},price={exec_price},"
                )
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
        else:
            # Paper/sim filled synchronously: keep status FILLED, still log order_placed for audit.
            if self.telegram_alert:
                self.telegram_alert(
                    f"Order placed: {sym} {side} qty={qty} order_id={order_id},price={exec_price},"
                )
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
                rec["status"],
                broker_order_id=order_id,
            )

    # working
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

            symbol = self._instrument_trading_symbol(rec.get("instrument")) or (
                (rec.get("payload") or {}).get("symbol") or ""
            )
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
            else:
                logger.warning("Failed to fetch broker open orders: %s", e)
            return False, {"error": str(e)}

        # Trade-led: sync trades (fills) first so positions are up to date before we compare order state
        self.sync_trades_from_broker()

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
                self._set_order_state(
                    tag,
                    OrderState.OPEN,
                    action="adopt_orphan",
                    message="Order seen on broker open list; adopted as local intent",
                )

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
                self._set_order_state(
                    tag,
                    OrderState.OPEN,
                    action="sync_open",
                    message="Broker confirms order is open",
                )
                intent = self.intent_store.get(tag)
                self.intent_store.update(
                    tag,
                    IntentStatus.SENT,
                    broker_order_id=intent.get("broker_order_id") or o.get("order_id"),
                    order_state=OrderState.OPEN,
                )

        # 2. Missing: In local pending but not on broker open list
        # Usually FILLED/REJECTED/CANCELLED. Only poll broker when cache doesn't have terminal state.
        missing = []
        for i in local_pending:
            intent_id = i.get("intent_id")
            if not intent_id or intent_id in broker_tags:
                continue
            payload = i.get("payload") or {}
            action = str(payload.get("action") or i.get("action") or "").upper()
            # FORCE_EXIT (broker-side SL/trigger) may be absent from open/fills APIs
            # until trigger/execution. If broker acknowledged with order_id, keep it
            # as valid pending instead of flagging as missing every reconcile cycle.
            if action == "FORCE_EXIT" and i.get("broker_order_id"):
                continue
            missing.append(i)
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
                            self._set_order_state(
                                tag,
                                OrderState.PARTIAL,
                                action="sync_partial",
                                message=f"Polling: filled={filled} size={size}",
                            )
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

                            # Apply fill FIRST. Do not mark intent FILLED before process_fill:
                            # process_fill used to see FILLED + skip, so on_fill never ran (no PM, no SL).
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
                            self._set_order_state(
                                tag,
                                OrderState.FILLED,
                                action="sync_filled",
                                message="Syncing fill discovered via polling",
                            )
                            self.intent_store.update(
                                tag,
                                IntentStatus.FILLED,
                                broker_order_id=order.get("order_id"),
                                order_state=OrderState.FILLED,
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
                            self._set_order_state(
                                tag,
                                ost,
                                action="sync_terminal",
                                message=f"Broker status={status!r}",
                            )
                            self.intent_store.update(
                                tag, IntentStatus.REJECTED, order_state=ost
                            )
                    else:
                        # Trade-led: order missing from open list. Resolve fill by client_order_id first,
                        # then by broker order_id (fills API often returns only order_id, not client_order_id).
                        fill_info = None
                        if hasattr(self.broker, "get_fill_for_client_order_id"):
                            try:
                                fill_info = self.broker.get_fill_for_client_order_id(tag)
                            except Exception:
                                pass
                        if not fill_info and i.get("broker_order_id") and hasattr(self.broker, "get_fill_by_order_id"):
                            try:
                                fill_info = self.broker.get_fill_by_order_id(str(i["broker_order_id"]))
                            except Exception:
                                pass
                        if fill_info and float(fill_info.get("price") or 0) > 0:
                            # Only apply trade if not already FILLED (e.g. by sync_trades)
                            if self._order_state.get(tag) not in _TERMINAL_ORDER_STATES:
                                trade = {
                                    "trade_id": f"fill_{tag}_{fill_info.get('order_id', '')}",
                                    "order_id": fill_info.get("order_id"),
                                    "intent_id": tag,
                                    "client_order_id": tag,
                                    "tag": tag,
                                    "price": float(fill_info["price"]),
                                    "size": float(fill_info.get("size") or 0),
                                    "side": (fill_info.get("side") or i.get("side") or "").upper(),
                                }
                                if self.process_trade(trade):
                                    if self.engine_logger:
                                        self.engine_logger.log(
                                            "oms",
                                            f"Missing order {tag}: applied trade from /v2/fills (trade-led)",
                                        )
                            else:
                                self._set_order_state(
                                    tag,
                                    OrderState.FILLED,
                                    action="assume_filled",
                                    message="Fill from API; trade already applied by sync_trades",
                                )
                                self.intent_store.update(
                                    tag, IntentStatus.FILLED, order_state=OrderState.FILLED
                                )
                        else:
                            # No trade found: do not update position or mark FILLED (trade-led: no trade → no position change)
                            if self.engine_logger:
                                self.engine_logger.log(
                                    "oms",
                                    f"Missing order {tag}: no fill in API; leaving state unchanged (trade-led OMS)",
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

    @staticmethod
    def _instrument_trading_symbol(inst: Any) -> str:
        """Resolve PM/broker symbol from an Instrument instance or serialized dict."""
        if inst is None:
            return ""
        ts = getattr(inst, "trading_symbol", None)
        if ts:
            return str(ts).strip()
        if isinstance(inst, dict):
            d = inst
            return str(
                d.get("trading_symbol")
                or d.get("tradingsymbol")
                or d.get("tradingSymbol")
                or d.get("symbol")
                or ""
            ).strip()
        return ""

    def _terminal_fill_reflected_in_pm(
        self,
        instrument,
        side: str,
        qty: int,
        action: Optional[str],
        intent_id: Optional[str],
        structure_id: Optional[str] = None,
    ) -> bool:
        """
        True only if PositionManager already matches this terminal fill — safe to skip a duplicate
        broker callback. For ENTRY, prefers structure_id slice match (intent-centric), then legacy net match.
        """
        if not self.position_manager or instrument is None:
            return False
        sym = self._instrument_trading_symbol(instrument)
        if not sym:
            return False
        act = str(action or "").upper()
        q = int(qty)
        sd = str(side or "").upper()
        net = int(self.position_manager.get_qty(sym))
        pos = self.position_manager.positions.get(sym)

        if act == "ENTRY":
            signed_exp = -q if sd == "SELL" else q
            stid = str(structure_id).strip() if structure_id else ""
            if stid:
                slice_q = self.position_manager.get_structure_slice(sym, stid)
                if slice_q != 0 and slice_q == signed_exp:
                    if not intent_id:
                        return False
                    pid = getattr(pos, "intent_id", None) if pos else None
                    pm_mid = (
                        self.position_manager.position_metadata.get(sym) or {}
                    ).get("intent_id")
                    if pid and str(pid) != str(intent_id):
                        return False
                    if not pid and pm_mid and str(pm_mid) != str(intent_id):
                        return False
                    if not pid and not pm_mid:
                        return False
                    return True
            if net == 0:
                return False
            if sd == "SELL":
                ok = net == -q
            elif sd == "BUY":
                ok = net == q
            else:
                return False
            if not ok:
                return False
            if not intent_id:
                return False
            pid = getattr(pos, "intent_id", None) if pos else None
            pm_mid = (self.position_manager.position_metadata.get(sym) or {}).get(
                "intent_id"
            )
            if pid and str(pid) != str(intent_id):
                return False
            if not pid and pm_mid and str(pm_mid) != str(intent_id):
                return False
            if not pid and not pm_mid:
                return False
            return True

        if act in ("EXIT", "FORCE_EXIT"):
            return net == 0

        return False

    def _adopt_main_entry_shadow_fill(
        self,
        instrument,
        intent: Dict[str, Any],
        intent_id: str,
        side: str,
        qty: int,
        price: float,
        order_id: Any,
        trade_id: str,
    ) -> None:
        """
        Broker/reconcile already shows the correct net qty for a MAIN ENTRY, but PM lacked
        intent/metadata (e.g. FILLED was set before on_fill). Attach linkage and run the same
        on_main_entry_fill hook as a normal open — does not change net_qty.
        """
        sym = self._instrument_trading_symbol(instrument)
        if not sym or not self.position_manager:
            return
        payload = intent.get("payload") or {}
        strategy = intent.get("strategy") or payload.get("strategy_id")
        structure_id = intent.get("structure_id") or payload.get("structure_id")
        tag = intent.get("tag") or payload.get("tag") or "MAIN"
        meta_extras = payload.get("strategy_meta")
        iq = int(qty)
        signed = -iq if str(side).upper() == "SELL" else iq
        with self.position_manager._lock:
            self.position_manager._merge_position_metadata(
                sym,
                strategy=strategy,
                structure_id=structure_id,
                tag=tag,
                intent_id=intent_id,
                metadata_extras=meta_extras,
            )
            pos = self.position_manager.positions.get(sym)
            if pos:
                if strategy:
                    pos.strategy = strategy
                if structure_id:
                    pos.structure_id = structure_id
                if tag:
                    pos.tag = tag
                pos.intent_id = intent_id
            if structure_id and str(tag or "").upper() == "MAIN":
                d = self.position_manager._structure_slices.setdefault(sym, {})
                sid = str(structure_id)
                if d.get(sid) in (None, 0):
                    d[sid] = signed
        hook = getattr(self.position_manager, "on_main_entry_fill", None)
        if callable(hook) and str(tag or "").upper() == "MAIN":
            try:
                hook(
                    instrument=instrument,
                    side=side,
                    qty=qty,
                    price=price,
                    strategy=strategy,
                    structure_id=structure_id,
                    tag=tag,
                    action="ENTRY",
                    candle_ts=intent.get("candle_ts"),
                    intent_id=intent_id,
                    metadata_extras=meta_extras,
                )
            except Exception as e:
                logger.warning("on_main_entry_fill after shadow adopt failed: %s", e)
        self._set_order_state(
            intent_id,
            OrderState.FILLED,
            action="adopt_main_entry_shadow",
            message="Metadata + SL hook; qty already at broker",
        )
        self.intent_store.update(
            intent_id,
            IntentStatus.FILLED,
            broker_order_id=order_id,
            order_state=OrderState.FILLED,
        )
        self._processed_trade_ids.add(trade_id)
        if len(self._processed_trade_ids) > getattr(
            self, "_processed_trade_ids_max", 10000
        ):
            self._processed_trade_ids = set(
                list(self._processed_trade_ids)[
                    -self._processed_trade_ids_max // 2 :
                ]
            )
        self.position_manager.note_trade_led_fill(sym)
        self.report_fill(
            sym,
            side,
            int(qty),
            None,
            price,
            order_id=order_id,
            intent_id=intent_id,
        )

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
        exit_reason=None,
        execution_source=None,
    ):
        """
        Single entry point for fill processing. Call from broker fill callback or LiveEngine.
        Updates position via PositionManager.on_fill(); if position closed, records realized PnL
        with RiskManager for daily_max_loss enforcement. Then logs and runs slippage check.
        """
        if not self.position_manager:
            self.report_fill(
                self._instrument_trading_symbol(instrument),
                side,
                qty,
                expected_price,
                price,
                order_id=order_id,
                intent_id=intent_id,
            )
            return
        # Skip duplicate callback only when PM already reflects this fill — not merely when
        # intent_store says FILLED (polling used to set FILLED before process_fill, skipping on_fill).
        if intent_id and self.intent_store:
            rec = self.intent_store.get(intent_id)
            if rec:
                st = rec.get("status")
                stv = getattr(st, "value", st)
                ord_state = self._order_state.get(intent_id)
                rec_order_id = rec.get("broker_order_id")
                same_order = (
                    order_id is not None
                    and rec_order_id is not None
                    and str(order_id) == str(rec_order_id)
                )
                action_eff = action or rec.get("action") or (rec.get("payload") or {}).get(
                    "action"
                )
                if str(stv) == "FILLED" and (
                    ord_state == OrderState.FILLED or ord_state == "FILLED"
                ):
                    if same_order or order_id is None:
                        pay0 = rec.get("payload") or {}
                        stid0 = rec.get("structure_id") or pay0.get("structure_id")
                        if self._terminal_fill_reflected_in_pm(
                            instrument,
                            side,
                            int(qty),
                            str(action_eff or ""),
                            intent_id,
                            structure_id=stid0,
                        ):
                            if self.engine_logger:
                                self.engine_logger.log(
                                    "oms",
                                    f"Skipping duplicate fill callback for already-filled intent {intent_id}",
                                )
                            return
                        if self.engine_logger:
                            self.engine_logger.log(
                                "oms",
                                f"CRITICAL: intent {intent_id} terminal but PM not updated — applying fill anyway",
                            )
        metadata_extras = None
        _ir = self.intent_store.get(intent_id) if intent_id and self.intent_store else None
        if _ir:
            metadata_extras = (_ir.get("payload") or {}).get("strategy_meta")
        if self.position_manager and intent_id and _ir:
            pay_pf = _ir.get("payload") or {}
            act_pf = str(
                action or _ir.get("action") or pay_pf.get("action") or ""
            ).upper()
            tag_pf = str(tag or _ir.get("tag") or pay_pf.get("tag") or "MAIN").upper()
            stid_pf = structure_id or _ir.get("structure_id") or pay_pf.get("structure_id")
            sym_pf = self._instrument_trading_symbol(instrument)
            if (
                act_pf == "ENTRY"
                and sym_pf
                and stid_pf
                and tag_pf == "MAIN"
                and self.position_manager.has_structure_slice_open(sym_pf, str(stid_pf))
                and not self._terminal_fill_reflected_in_pm(
                    instrument,
                    side,
                    int(qty),
                    act_pf,
                    intent_id,
                    structure_id=str(stid_pf),
                )
            ):
                if self.engine_logger:
                    self.engine_logger.log(
                        "oms",
                        f"Skipping duplicate MAIN ENTRY fill callback structure_id={stid_pf}",
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
            metadata_extras=metadata_extras,
            exit_reason=exit_reason,
            execution_source=execution_source or "INTENT",
        )
        if position_closed and realized_pnl is not None:
            self.risk.record_realized_pnl(realized_pnl)
        sym = self._instrument_trading_symbol(instrument)
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
            self._set_order_state(
                intent_id,
                OrderState.FILLED,
                action="process_fill",
                message="Fill processed from callback or engine",
            )
            self.intent_store.update(
                intent_id,
                IntentStatus.FILLED,
                broker_order_id=order_id,
                order_state=OrderState.FILLED,
            )
        if self.position_manager and sym:
            self.position_manager.note_trade_led_fill(sym)

    def process_trade(self, trade: Dict[str, Any]) -> bool:
        """
        Trade-led OMS: update position from a trade event (fill). Orders are metadata;
        positions are driven only by trades. Idempotent by trade_id.
        Returns True if trade was applied, False if skipped (e.g. already processed).
        """
        trade_id = str(
            trade.get("trade_id")
            or trade.get("id")
            or f"{trade.get('order_id', '')}_{trade.get('created_at', '')}"
        )
        if not trade_id or trade_id in getattr(self, "_processed_trade_ids", set()):
            return False
        intent_id = trade.get("intent_id") or trade.get("client_order_id") or trade.get("tag")
        if not intent_id:
            return False
        price = float(trade.get("price") or 0)
        size = float(trade.get("size") or 0)
        if price <= 0 or size <= 0:
            return False
        side = (trade.get("side") or "").upper()
        order_id = trade.get("order_id")
        # Resolve instrument and metadata from intent_store
        intent = self.intent_store.get(intent_id) if self.intent_store else None
        if not intent:
            return False
        instrument = trade.get("instrument") or intent.get("instrument")
        if not instrument:
            return False
        if self.position_manager:
            payload = intent.get("payload") or {}
            action_to_apply = intent.get("action") or payload.get("action") or trade.get("action")
            action_upper = str(action_to_apply or "").upper()
            sym = self._instrument_trading_symbol(instrument)

            tag_u = str(intent.get("tag") or payload.get("tag") or "MAIN").upper()
            stid = (
                intent.get("structure_id")
                or payload.get("structure_id")
                or trade.get("structure_id")
            )
            if action_upper == "ENTRY" and sym and tag_u == "MAIN":
                prev_q = int(self.position_manager.get_qty(sym))
                if prev_q != 0:
                    iq = int(size)
                    exp = -iq if side == "SELL" else iq
                    if prev_q == exp and not self._terminal_fill_reflected_in_pm(
                        instrument,
                        side,
                        iq,
                        action_upper,
                        intent_id,
                        structure_id=stid,
                    ):
                        if self.engine_logger:
                            self.engine_logger.log(
                                "oms",
                                f"Adopting MAIN ENTRY linkage for {sym} intent_id={intent_id} "
                                f"(qty already at broker; attaching metadata + SL)",
                            )
                        self._adopt_main_entry_shadow_fill(
                            instrument=instrument,
                            intent=intent,
                            intent_id=intent_id,
                            side=side,
                            qty=iq,
                            price=price,
                            order_id=order_id,
                            trade_id=trade_id,
                        )
                        return True

            # Skip ENTRY from fills API only when this intent's ENTRY is already reflected in PM
            # (true duplicate). Do not skip merely because the symbol is open — that can hide
            # a never-applied ENTRY after reconcile vs. fill races.
            if action_upper == "ENTRY" and self._terminal_fill_reflected_in_pm(
                instrument,
                side,
                int(size),
                action_upper,
                intent_id,
                structure_id=stid,
            ):
                if self.engine_logger:
                    self.engine_logger.log(
                        "oms",
                        f"Skipping duplicate ENTRY trade for {sym} (intent_id={intent_id}) — PM already matches",
                    )
                self._processed_trade_ids.add(trade_id)
                self._set_order_state(
                    intent_id,
                    OrderState.FILLED,
                    action="skip_duplicate_entry_trade",
                    message="ENTRY trade already in PM",
                )
                self.intent_store.update(
                    intent_id,
                    IntentStatus.FILLED,
                    broker_order_id=order_id,
                    order_state=OrderState.FILLED,
                )
                self.position_manager.note_trade_led_fill(sym)
                return True

            if (
                action_upper == "ENTRY"
                and sym
                and stid
                and tag_u == "MAIN"
                and self.position_manager.has_structure_slice_open(sym, str(stid))
                and not self._terminal_fill_reflected_in_pm(
                    instrument,
                    side,
                    int(size),
                    action_upper,
                    intent_id,
                    structure_id=str(stid),
                )
            ):
                if self.engine_logger:
                    self.engine_logger.log(
                        "oms",
                        f"Skipping duplicate MAIN ENTRY for structure_id={stid} on {sym} "
                        f"(intent_id={intent_id})",
                    )
                self._processed_trade_ids.add(trade_id)
                self._set_order_state(
                    intent_id,
                    OrderState.FILLED,
                    action="skip_duplicate_structure_entry",
                    message="MAIN ENTRY already open for this structure_id",
                )
                self.intent_store.update(
                    intent_id,
                    IntentStatus.FILLED,
                    broker_order_id=order_id,
                    order_state=OrderState.FILLED,
                )
                self.position_manager.note_trade_led_fill(sym)
                return True

            execution_source = trade.get("execution_source") or "INTENT"
            position_closed, realized_pnl = self.position_manager.on_fill(
                instrument=instrument,
                side=side,
                qty=int(size),
                price=price,
                intent_id=intent_id,
                order_id=order_id,
                strategy=(
                    intent.get("strategy")
                    or payload.get("strategy_id")
                    or trade.get("strategy")
                ),
                structure_id=(
                    intent.get("structure_id")
                    or payload.get("structure_id")
                    or trade.get("structure_id")
                ),
                tag=intent.get("tag") or trade.get("tag"),
                candle_ts=intent.get("candle_ts") or trade.get("candle_ts"),
                action=intent.get("action") or payload.get("action") or trade.get("action"),
                metadata_extras=payload.get("strategy_meta"),
                execution_source=execution_source,
            )
            if position_closed and realized_pnl is not None:
                self.risk.record_realized_pnl(realized_pnl)
        sym = self._instrument_trading_symbol(instrument)
        self.report_fill(
            sym, side, int(size), trade.get("expected_price"), price,
            order_id=order_id, intent_id=intent_id,
        )
        self._set_order_state(
            intent_id,
            OrderState.FILLED,
            action="process_trade",
            message=f"Position updated from trade ({trade.get('execution_source') or 'INTENT'})",
        )
        self.intent_store.update(
            intent_id,
            IntentStatus.FILLED,
            broker_order_id=order_id,
            order_state=OrderState.FILLED,
        )
        self._processed_trade_ids.add(trade_id)
        if len(self._processed_trade_ids) > getattr(self, "_processed_trade_ids_max", 10000):
            self._processed_trade_ids = set(list(self._processed_trade_ids)[-self._processed_trade_ids_max // 2 :])
        if self.position_manager and sym:
            self.position_manager.note_trade_led_fill(sym)
        return True

    @staticmethod
    def _string_indicates_exchange_liquidation(s: str) -> bool:
        """
        True only for explicit liquidation semantics — not bare 'liquid' (matches 'illiquid', etc.).
        """
        if not isinstance(s, str) or not s.strip():
            return False
        sl = s.lower()
        if "liquidation" in sl or "liquidated" in sl:
            return True
        if "force_liquid" in sl:
            return True
        return False

    @staticmethod
    def _is_delta_liquidation_fill(f: Dict[str, Any]) -> bool:
        """True if broker fill is an exchange-driven liquidation (no client_order_id / intent)."""
        if not isinstance(f, dict):
            return False
        if f.get("liquidation") is True or f.get("is_liquidation") is True:
            return True
        ft = f.get("fill_type") or f.get("type") or ""
        if isinstance(ft, str) and OrderRouter._string_indicates_exchange_liquidation(ft):
            return True
        meta = f.get("meta")
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (json.JSONDecodeError, TypeError):
                meta = None
        if isinstance(meta, dict):
            for key in ("fill_type", "type", "order_type", "liquidation_type"):
                v = meta.get(key)
                if isinstance(v, str) and OrderRouter._string_indicates_exchange_liquidation(v):
                    return True
        return False

    @staticmethod
    def _is_adl_fill(f: Dict[str, Any]) -> bool:
        """Auto-deleverage close (future-proof; Delta/metadata may expose flags later)."""
        if not isinstance(f, dict):
            return False
        if f.get("adl") is True or f.get("is_adl") is True:
            return True
        ft = f.get("fill_type") or f.get("type") or ""
        if isinstance(ft, str) and (
            "adl" in ft.lower() or "delever" in ft.lower()
        ):
            return True
        meta = f.get("meta")
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (json.JSONDecodeError, TypeError):
                meta = None
        if isinstance(meta, dict):
            for key in ("fill_type", "type", "order_type", "liquidation_type"):
                v = meta.get(key)
                if isinstance(v, str) and (
                    "adl" in v.lower() or "delever" in v.lower()
                ):
                    return True
        return False

    def _known_broker_order_ids(self) -> Set[str]:
        """All broker order IDs we have recorded on intents (own orders)."""
        out: Set[str] = set()
        if not self.intent_store or not hasattr(self.intent_store, "intents"):
            return out
        try:
            for rec in self.intent_store.intents.values():
                bid = rec.get("broker_order_id")
                if bid is not None and str(bid).strip():
                    out.add(str(bid).strip())
        except Exception:
            pass
        return out

    def resolve_intent_id_by_broker_order_id(self, broker_order_id: str) -> Optional[str]:
        """Map Dhan OrderNo / broker order id to intent_id when CorrelationId is empty."""
        bid = str(broker_order_id or "").strip()
        if not bid or not self.intent_store:
            return None
        try:
            for rec in self.intent_store.intents.values():
                if str(rec.get("broker_order_id") or "").strip() == bid:
                    iid = rec.get("intent_id")
                    return str(iid) if iid else None
        except Exception:
            pass
        return None

    def _external_close_confidence_score(
        self, f: Dict[str, Any], known_order_ids: Set[str]
    ) -> Tuple[int, Optional[Any]]:
        """
        Confidence for treating a fill as EXTERNAL_CLOSE (not boolean) — reduces false positives
        when the broker drops client_order_id on our own exit orders.

        +2 no client_order_id / tag
        +2 broker order_id not in known_order_ids
        +1 reduce_only is True
        +2 fill direction matches an open leg that would reduce exposure
        """
        if not isinstance(f, dict):
            return 0, None
        oid = str(f.get("order_id") or f.get("id") or "").strip()
        cid = str(f.get("client_order_id") or f.get("tag") or "").strip()
        if cid:
            return 0, None
        if not oid or oid in known_order_ids:
            return 0, None
        ro = f.get("reduce_only")
        if ro is False:
            return 0, None
        sym = OrderRouter._fill_product_symbol(f)
        side = (f.get("side") or "").upper()
        if not sym or side not in ("BUY", "SELL"):
            return 0, None
        score = 4
        if ro is True:
            score += 1
        pos = None
        if self.position_manager:
            pos = self._find_position_for_external_close(
                sym, side, float(f.get("size") or 0)
            )
        if pos is not None:
            score += 2
        return score, pos

    @staticmethod
    def _fill_product_symbol(f: Dict[str, Any]) -> str:
        sym = (
            f.get("product_symbol")
            or (f.get("product") or {}).get("symbol")
            or f.get("symbol")
            or ""
        )
        return str(sym).strip()

    #checked
    @staticmethod
    def _fill_timestamp_unix(f: Dict[str, Any]) -> Optional[float]:
        """Parse broker fill time to UTC unix seconds (float). None if missing or unparseable."""
        raw = f.get("created_at")
        if raw is None:
            raw = f.get("filled_at") or f.get("timestamp") or f.get("time")
        if raw is None:
            return None
        if isinstance(raw, (int, float)):
            ts = float(raw)
            if ts > 1e12:
                ts /= 1000.0
            return ts
        if isinstance(raw, str):
            s = raw.strip()
            if not s:
                return None
            try:
                uf = float(s)
                if uf > 1e12:
                    uf /= 1000.0
                return uf
            except ValueError:
                pass
            try:
                iso = s.replace("Z", "+00:00")
                dt = datetime.datetime.fromisoformat(iso)
                return dt.timestamp()
            except (ValueError, TypeError, OSError):
                return None
        return None

    def _orphan_fill_fails_time_gates(self, t_fill: Optional[float], order_id: Any) -> bool:
        """True => do not run orphan EXTERNAL_CLOSE / LIQUIDATION / ADL for this fill."""
        if t_fill is None:
            logger.debug(
                "Orphan fill skipped: no parseable fill time (order_id=%s)",
                order_id,
            )
            return True
        if self.reject_orphan_fills_before_oms_session:
            if t_fill + 0.5 < self._oms_session_start_unix:
                logger.debug(
                    "Orphan fill skipped: before OMS session start (order_id=%s)",
                    order_id,
                )
                return True
        if (
            self.max_orphan_fill_age_seconds is not None
            and self.max_orphan_fill_age_seconds > 0
        ):
            if time.time() - t_fill > self.max_orphan_fill_age_seconds:
                logger.debug(
                    "Orphan fill skipped: exceeds max_orphan_fill_age_seconds (order_id=%s)",
                    order_id,
                )
                return True
        return False

    @staticmethod
    def _symbol_keys_close_enough(a: str, b: str) -> bool:
        """Case-insensitive match for option contract symbols (e.g. C-BTC-65000-030426)."""
        return (a or "").strip().upper() == (b or "").strip().upper()

    def _close_qty_from_fill(self, pos: Any, raw_size: float) -> float:
        """
        Contracts to apply for this fill: supports partial liquidation when size is in contracts
        or in base currency (e.g. BTC) via instrument.contract_multiplier.
        If reported size is missing (<=0), assume full local leg.
        """
        net = abs(float(pos.net_qty))
        if net <= 0:
            return 0.0
        if raw_size <= 0:
            return net
        inst = pos.instrument
        mult = float(getattr(inst, "contract_multiplier", 0) or 0)
        # Integer contract count from API
        if raw_size >= 1.0 - 1e-9:
            q = float(int(round(raw_size)))
            return min(net, q) if q > 0 else net
        # Fractional: often base currency (notional) per contract on Delta
        if mult > 0 and raw_size < net * mult * 4 + 1e-9:
            contracts = raw_size / mult
            if contracts > 0:
                return min(net, float(contracts))
        # Unparseable small fraction: treat as partial in contract space
        if 0 < raw_size < 1:
            return min(net, float(raw_size))
        return min(net, float(raw_size))

    def _find_position_for_external_close(
        self,
        product_symbol: str,
        fill_side: str,
        fill_size_raw: float,
    ) -> Optional[Any]:
        """
        Match external close to an open leg. Priority when multiple: exact size, closest size,
        most recently updated, then highest exposure (|qty|*avg_price*lot_size).
        """
        if not self.position_manager or not product_symbol:
            return None
        fs = fill_side.upper()
        if fs not in ("BUY", "SELL"):
            return None

        candidates = []
        for sym_key, pos in self.position_manager.positions.items():
            if pos.net_qty == 0:
                continue
            inst_ts = (
                getattr(pos.instrument, "trading_symbol", "") or ""
                if pos.instrument
                else ""
            )
            if (
                not self._symbol_keys_close_enough(sym_key, product_symbol)
                and not self._symbol_keys_close_enough(inst_ts, product_symbol)
            ):
                continue
            if fs == "BUY" and pos.net_qty >= 0:
                continue
            if fs == "SELL" and pos.net_qty <= 0:
                continue
            candidates.append(pos)

        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        def _rank_tuple(pos: Any) -> Tuple[int, float, float, float]:
            net = abs(float(pos.net_qty))
            guessed = self._close_qty_from_fill(pos, fill_size_raw)
            exact_miss = 0 if abs(net - guessed) < 1e-8 else 1
            dist = abs(net - guessed)
            last = float(getattr(pos, "last_updated", 0) or 0)
            exposure = abs(float(pos.net_qty)) * float(pos.avg_price or 0) * float(
                getattr(pos.instrument, "lot_size", 1) or 1
            )
            return (exact_miss, dist, -last, -exposure)

        return sorted(candidates, key=_rank_tuple)[0]

    def _process_external_close_fill(self, f: Dict[str, Any], execution_source: str) -> bool:
        """
        Liquidation / ADL / orphan reduce-only fills without intent linkage.
        execution_source: LIQUIDATION | EXTERNAL_CLOSE | ADL
        """
        if not self.position_manager:
            return False
        if execution_source not in ("LIQUIDATION", "EXTERNAL_CLOSE", "ADL"):
            return False

        trade_id = str(
            f.get("trade_id")
            or f.get("id")
            or f"{f.get('order_id', '')}_{f.get('created_at', '')}"
        )
        if not trade_id or trade_id in getattr(self, "_processed_trade_ids", set()):
            return False

        fill_ts = self._fill_timestamp_unix(f)
        if fill_ts is None:
            logger.debug(
                "Orphan close skipped: missing fill timestamp (trade_id=%s)",
                trade_id,
            )
            return False

        price = float(f.get("price") or f.get("average_fill_price") or 0)
        raw_size = float(f.get("size") or f.get("qty") or 0)
        if price <= 0:
            return False

        sym = self._fill_product_symbol(f)
        side = (f.get("side") or "").upper()

        with self.position_manager._lock:
            pos = self._find_position_for_external_close(sym, side, raw_size)
            if not pos or pos.net_qty == 0:
                if pos is None:
                    # Expected when: stale fills in get_recent_fills, manual close already flat,
                    # or another account/session — not actionable for local OMS.
                    logger.debug(
                        "Orphan fill skipped (no reducing leg in local book): source=%s symbol=%s side=%s size=%s",
                        execution_source,
                        sym,
                        side,
                        raw_size,
                    )
                return False
            if self.reject_orphan_fill_if_predates_position_open:
                et = getattr(pos, "entry_time", None)
                if et is not None and fill_ts < float(et) - 1.0:
                    logger.debug(
                        "Orphan fill skipped: fill before local position open (symbol=%s fill_ts=%s entry_time=%s)",
                        getattr(pos.instrument, "trading_symbol", sym),
                        fill_ts,
                        et,
                    )
                    return False
            inst = pos.instrument
            sym_ts = getattr(inst, "trading_symbol", sym)
            close_qty = min(
                self._close_qty_from_fill(pos, raw_size),
                abs(float(pos.net_qty)),
            )
            prev_signed = int(pos.net_qty)
            pm_meta = self.position_manager.position_metadata.get(sym_ts) or {}
            strat = pos.strategy or pm_meta.get("strategy")
            struct_id = pos.structure_id or pm_meta.get("structure_id")
            tag = pos.tag or pm_meta.get("tag")
            intent_id = pos.intent_id or pm_meta.get("intent_id")
            meta_extras = pm_meta.get("strategy_meta")

        if close_qty <= 0:
            return False

        exit_reason = {
            "LIQUIDATION": "LIQUIDATION",
            "EXTERNAL_CLOSE": "EXTERNAL_CLOSE",
            "ADL": "ADL",
        }.get(execution_source, execution_source)
        order_id = str(f.get("order_id") or f.get("id") or "")

        qty_arg = (
            int(round(close_qty))
            if abs(close_qty - round(close_qty)) < 1e-9
            else close_qty
        )
        position_closed, realized_pnl = self.position_manager.on_fill(
            instrument=inst,
            side=side,
            qty=qty_arg,
            price=price,
            intent_id=intent_id,
            order_id=order_id or None,
            strategy=strat,
            structure_id=struct_id,
            tag=tag,
            candle_ts=None,
            action="EXIT",
            metadata_extras=meta_extras,
            exit_reason=exit_reason,
            execution_source=execution_source,
        )
        np = self.position_manager.positions.get(sym_ts)
        new_qty = int(np.net_qty) if np else 0

        fn = getattr(self.position_manager, "on_forced_exit", None)
        debounce_key = struct_id or sym_ts
        if callable(fn) and self.position_manager.should_emit_forced_exit(
            debounce_key, position_closed
        ):
            try:
                fn(
                    instrument=inst,
                    symbol=sym_ts,
                    strategy=strat,
                    structure_id=struct_id,
                    tag=tag,
                    intent_id=intent_id,
                    prev_qty=prev_signed,
                    new_qty=new_qty,
                    qty_closed=close_qty,
                    price=price,
                    execution_source=execution_source,
                    exit_reason=exit_reason,
                    position_closed=position_closed,
                    order_id=order_id or None,
                )
            except Exception as e:
                logger.warning("on_forced_exit callback failed: %s", e, exc_info=True)

        rec_es = getattr(self.risk, "record_execution_source", None)
        if callable(rec_es):
            try:
                rec_es(
                    execution_source,
                    strat,
                    symbol=sym_ts,
                    position_closed=position_closed,
                )
            except Exception as e:
                logger.debug("record_execution_source failed: %s", e)

        if position_closed and realized_pnl is not None:
            self.risk.record_realized_pnl(realized_pnl)

        self.report_fill(
            sym_ts,
            side,
            qty_arg,
            None,
            price,
            order_id=order_id or None,
            intent_id=intent_id,
        )
        if intent_id and self.intent_store:
            self._set_order_state(
                intent_id,
                OrderState.FILLED,
                action="external_close_fill",
                message=f"{execution_source} broker_order_id={order_id}",
            )
            self.intent_store.update(
                intent_id,
                IntentStatus.FILLED,
                broker_order_id=order_id or None,
                order_state=OrderState.FILLED,
            )
        self._processed_trade_ids.add(trade_id)
        if len(self._processed_trade_ids) > getattr(self, "_processed_trade_ids_max", 10000):
            self._processed_trade_ids = set(
                list(self._processed_trade_ids)[-self._processed_trade_ids_max // 2 :]
            )
        self.position_manager.note_trade_led_fill(sym_ts)
        if self.engine_logger:
            self.engine_logger.log(
                "oms",
                f"Applied {execution_source} fill to {sym_ts} qty={close_qty} intent_id={intent_id or 'none'}",
            )
        return True

    def sync_trades_from_broker(self) -> None:
        """
        Trade-led OMS: pull recent fills from broker and apply any new trades.
        Call before order-state verification so positions are up to date from trades.
        """
        if not getattr(self.broker, "get_recent_fills", None):
            return
        try:
            fills = self.broker.get_recent_fills(page_size=50)
        except Exception:
            return
        # Match by broker order_id when fill has no client_order_id (e.g. Delta often returns only order_id).
        # Include FILLED/CANCELLED intents so delayed API rows still map to process_trade (idempotent by trade_id).
        broker_order_id_to_intent: Dict[str, str] = {}
        known_order_ids = self._known_broker_order_ids()
        try:
            for rec in self.intent_store.intents.values():
                bid = rec.get("broker_order_id")
                iid = rec.get("intent_id")
                if bid is not None and iid:
                    k = str(bid).strip()
                    if k:
                        broker_order_id_to_intent.setdefault(k, iid)
        except Exception:
            pass
        for f in fills or []:
            intent_id = (
                f.get("client_order_id")
                or f.get("tag")
                or broker_order_id_to_intent.get(str(f.get("order_id") or f.get("id") or ""))
            )
            if intent_id and self.intent_store and self.intent_store.get(intent_id):
                oid = str(f.get("order_id") or f.get("id") or "")
                sz = float(f.get("size") or 0)
                pr = float(f.get("price") or 0)
                is_dhan = type(self.broker).__name__ == "DhanBroker"
                # Canonical REST reconciliation id for Dhan (distinct from DHAN_WS:* incremental keys).
                if is_dhan:
                    trade_id = f"DHAN_REST:{oid}:{int(sz)}:{pr}"
                else:
                    tid = f.get("id") or f.get("trade_id")
                    trade_id = str(tid) if tid else f"{oid}_{int(sz)}_{pr}"
                trade: Dict[str, Any] = {
                    "trade_id": trade_id,
                    "id": trade_id,
                    "order_id": oid or str(f.get("id", "")),
                    "intent_id": intent_id,
                    "client_order_id": intent_id,
                    "tag": intent_id,
                    "price": pr,
                    "size": sz,
                    "side": (f.get("side") or "").upper(),
                    "created_at": f.get("created_at"),
                    "execution_source": "REST_FILLS",
                }
                if is_dhan:
                    trade["fill_confidence"] = "CONFIRMED"
                self.process_trade(trade)
                continue

            t_fill = self._fill_timestamp_unix(f)
            if self._orphan_fill_fails_time_gates(t_fill, f.get("order_id")):
                continue

            # Manual / untagged fills: prefer EXTERNAL_CLOSE when a reducing leg exists locally,
            # before LIQUIDATION — avoids false 'liquid' substring matches stealing the path.
            exec_src = None
            score, pos_hint = self._external_close_confidence_score(
                f, known_order_ids
            )
            th = getattr(self, "_orphan_close_score_threshold", 6)
            sus = getattr(self, "_orphan_close_suspect_floor", 5)

            if self._is_adl_fill(f):
                exec_src = "ADL"
            elif score >= th and pos_hint is not None:
                exec_src = "EXTERNAL_CLOSE"
            elif self._is_delta_liquidation_fill(f):
                exec_src = "LIQUIDATION"
            else:
                if score >= th and pos_hint is None:
                    logger.info(
                        "Orphan-style fill score=%s but no reducing leg; not applying EXTERNAL_CLOSE (order_id=%s symbol=%s)",
                        score,
                        f.get("order_id"),
                        OrderRouter._fill_product_symbol(f),
                    )
                elif sus <= score < th:
                    logger.info(
                        "Suspect orphan-style fill below EXTERNAL_CLOSE threshold: score=%s (need %s) order_id=%s symbol=%s",
                        score,
                        th,
                        f.get("order_id"),
                        OrderRouter._fill_product_symbol(f),
                    )

            if exec_src and self._process_external_close_fill(f, exec_src):
                continue
        return

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
