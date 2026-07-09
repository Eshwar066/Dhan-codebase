"""Dhan broker: order placement via DhanBrokerApi. Trade-led OMS via get_recent_fills / get_fill_for_client_order_id."""

import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

from core.broker.base import BaseBroker
from core.broker.internal.dhan import mappings as dhan_mappings
from core.broker.internal.dhan.mappings import dhan_correlation_id, parse_dhan_api_error
from core.utils.global_rate_limiter import DHAN_ORDER_API, GlobalRateLimiter
from core.utils.price_tick import resolve_tick_size, round_by_tick_size


def _quantize_order_prices(
    payload: Dict[str, Any],
    *,
    instrument: Any = None,
    instrument_store: Any = None,
    side: str = "",
) -> Dict[str, Any]:
    """Ensure limit/trigger prices are valid multiples of exchange tick size."""
    sym = str(payload.get("tradingsymbol") or "").strip()
    if not sym:
        return payload
    tick = resolve_tick_size(sym, instrument_store, instrument=instrument)
    side_u = str(side or payload.get("transaction_type") or "").upper()
    buy_mode = "ceil" if side_u == "BUY" else "floor"
    sell_mode = "floor" if side_u == "SELL" else "ceil"
    order_type = str(payload.get("order_type") or "").upper()
    out = dict(payload)
    for key, mode in (
        ("price", buy_mode if side_u != "SELL" else sell_mode),
        ("trigger_price", sell_mode if "SL" in order_type else buy_mode),
    ):
        raw = out.get(key)
        if raw is None:
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        if val <= 0:
            continue
        rounded = round_by_tick_size(val, tick, floor_or_ceil=mode)
        if rounded is not None:
            out[key] = rounded
    return out


def _order_intent_to_payload(intent, execution_price=None, instrument_store=None):
    """Convert OrderIntent to dict for Dhan payload."""
    inst = intent.instrument
    segment = getattr(inst, "segment", "NFO")
    exchange = dhan_mappings.internal_segment_to_exchange_arg(
        str(segment) if segment is not None else "NFO"
    )
    price = execution_price if execution_price is not None else (intent.price or 0)
    qty = getattr(intent, "qty", inst.lot_size)
    lot_size = int(getattr(inst, "lot_size", 1))
    total_qty = int(qty) * lot_size
    extras = getattr(intent, "metadata_extras", None) or {}
    execution_mode = str(extras.get("execution_mode") or "").strip().upper()
    trigger = float(getattr(intent, "trigger_price", 0) or 0)
    if execution_mode in ("GTT", "HYBRID_GTT") and trigger <= 0:
        trigger = float(price or 0)
    payload = {
        "tradingsymbol": inst.place_order_symbol(),
        "exchange": exchange,
        "quantity": total_qty,
        "price": float(price),
        "trigger_price": trigger,
        "order_type": getattr(intent, "order_type", "MARKET"),
        "transaction_type": intent.side,
        "trade_type": getattr(intent, "trade_type", "MARGIN"),
        "disclosed_quantity": 0,
        "after_market_order": False,
        "validity": "DAY",
        "amo_time": "OPEN",
        "bo_profit_value": None,
        "bo_stop_loss_value": None,
        "tag": dhan_correlation_id(intent.intent_id),
        "intent_id": intent.intent_id,
        "correlation_id": dhan_correlation_id(intent.intent_id),
        "execution_mode": execution_mode,
        "order_flag": str(extras.get("order_flag") or "SINGLE").upper(),
    }
    return _quantize_order_prices(
        payload,
        instrument=inst,
        instrument_store=instrument_store,
        side=intent.side,
    )


class DhanBroker(BaseBroker):
    """Order placement via Dhan. Uses IBrokerApi (DhanBrokerApi)."""

    # Dhan docs: max 25 modifications per order — switch to cancel + re-place before hard failure.
    DHAN_MODIFY_WARN_THRESHOLD = 20
    supports_hedge_fill_gated_bundles = True
    hedge_fill_wait_timeout_sec = 120.0
    hedge_fill_poll_interval_sec = 0.5
    hedge_fill_margin_settle_sec = 0.5
    hedge_fill_retry_max_attempts = 3
    hedge_fill_retry_per_attempt_sec = 40.0
    hedge_fill_retry_strategy_ids = frozenset({"LEAPS_RSI"})

    def __init__(self, api, position_manager=None, intent_store=None):
        super().__init__(position_manager=position_manager, intent_store=intent_store)
        self.api = api
        self._dhan_modify_counts: Dict[str, int] = {}
        self._last_place_order_failure: Optional[Dict[str, Any]] = None

    def _instrument_store(self):
        router = getattr(self, "order_router", None)
        return getattr(router, "instrument_store", None) if router else None

    def _build_payload(self, intent, execution_price=None):
        store = self._instrument_store()
        if hasattr(intent, "instrument"):
            return _order_intent_to_payload(intent, execution_price, instrument_store=store)
        segment = intent.get("segment", "EQ")
        exchange = dhan_mappings.internal_segment_to_exchange_arg(str(segment))
        required = ["trading_symbol", "side", "qty"]
        for r in required:
            if r not in intent or intent[r] is None:
                raise ValueError(f"❌ Missing required intent field: {r}")
        qty = int(intent["qty"])
        lot_size = int(intent.get("lot_size", 1))
        total_qty = qty * lot_size
        price = execution_price if execution_price is not None else float(intent.get("price", 0) or 0)
        payload = {
            "tradingsymbol": intent["trading_symbol"],
            "exchange": exchange,
            "quantity": total_qty,
            "price": price,
            "trigger_price": float(intent.get("trigger_price", 0) or 0),
            "order_type": intent.get("order_type", "MARKET"),
            "transaction_type": intent["side"],
            "trade_type": intent.get("trade_type", "MARGIN"),
            "disclosed_quantity": int(intent.get("disclosed_quantity", 0)),
            "after_market_order": bool(intent.get("after_market_order", False)),
            "validity": intent.get("validity", "DAY"),
            "amo_time": intent.get("amo_time", "OPEN"),
            "bo_profit_value": intent.get("bo_profit_value", 0),
            "bo_stop_loss_value": intent.get("bo_stop_loss_value", 0),
            "tag": intent.get("intent_id"),
            "intent_id": intent.get("intent_id"),
            "correlation_id": intent.get("intent_id"),
        }
        return _quantize_order_prices(
            payload,
            instrument_store=store,
            side=str(intent.get("side") or ""),
        )

    def get_balance_snapshot(self) -> Optional[Dict[str, Any]]:
        """
        INR available margin/cash from Dhan fund limits — same keys as DeltaBroker
        so LiveEngine._log_startup_balance_snapshot can log/Telegram one shape.
        """
        source = getattr(self.api, "_source", None)
        if source is None or not getattr(source, "get_balance", None):
            return None
        try:
            available = float(source.get_balance())
        except (TypeError, ValueError) as e:
            logger.warning("Dhan balance snapshot: invalid balance: %s", e)
            return None
        except Exception as e:
            logger.warning("Dhan balance snapshot failed: %s", e)
            return None
        return {
            "selected_available": available,
            "inr_available": available,
            "usd_available": None,
        }

    @staticmethod
    def _parse_margin_shortfall(
        available: float, required_margin: float, insufficient_balance: float
    ) -> Tuple[bool, float]:
        """
        Dhan insufficientBalance = available - totalMargin (negative => shortfall).
        """
        if insufficient_balance < 0:
            return False, abs(insufficient_balance)
        if available < required_margin:
            return False, required_margin - available
        return True, 0.0

    def _get_available_balance(self) -> Optional[float]:
        source = getattr(self.api, "_source", None)
        if source is None:
            return None
        try:
            return float(getattr(source, "get_balance", lambda: 0)())
        except Exception:
            return None

    def check_funds_before_order(
        self,
        intent: Any,
        execution_price: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Check available balance and required/SPAN margin before placing order.
        Uses Dhan get_balance() and margin_calculator(); on shortage returns ok=False
        with shortfall and message for logging and Telegram.
        """
        try:
            payload = self._build_payload(intent, execution_price)
        except Exception:
            return None
        available = self._get_available_balance()
        if available is None:
            return None
        tsl = getattr(getattr(self.api, "_source", None), "tsl", None)
        required_margin = None
        span_margin = None
        if tsl and getattr(tsl, "margin_calculator", None):
            try:
                oc = tsl.margin_calculator(
                    tradingsymbol=payload["tradingsymbol"],
                    exchange=payload["exchange"],
                    transaction_type=payload["transaction_type"],
                    quantity=payload["quantity"],
                    trade_type=payload["trade_type"],
                    price=payload["price"],
                    trigger_price=payload["trigger_price"],
                )
                if isinstance(oc, dict):
                    required_margin = float(
                        oc.get("totalMargin") or oc.get("total_margin") or 0
                    )
                    span_margin = float(oc.get("spanMargin") or oc.get("span_margin") or 0)
                    if "availableBalance" in oc or "available_balance" in oc:
                        available = float(
                            oc.get("availableBalance")
                            or oc.get("available_balance")
                            or available
                        )
                    insufficient = float(
                        oc.get("insufficientBalance") or oc.get("insufficient_balance") or 0
                    )
                    ok, shortfall = self._parse_margin_shortfall(
                        available, required_margin, insufficient
                    )
                    if not ok:
                        return {
                            "ok": False,
                            "available": available,
                            "required_margin": required_margin,
                            "span_margin": span_margin if span_margin else None,
                            "shortfall": shortfall,
                            "message": (
                                f"Available={available:.2f}, required_margin={required_margin:.2f}, "
                                f"SPAN={span_margin:.2f}; shortfall={shortfall:.2f}"
                            ),
                        }
                    return {
                        "ok": True,
                        "available": available,
                        "required_margin": required_margin,
                        "span_margin": span_margin if span_margin else None,
                        "shortfall": 0,
                        "message": "",
                    }
            except Exception:
                pass
        if required_margin is None:
            required_margin = payload["price"] * payload["quantity"]
        ok, shortfall = self._parse_margin_shortfall(available, required_margin, 0)
        if not ok:
            return {
                "ok": False,
                "available": available,
                "required_margin": required_margin,
                "span_margin": span_margin,
                "shortfall": shortfall,
                "message": (
                    f"Available={available:.2f}, required={required_margin:.2f}; shortfall={shortfall:.2f}"
                ),
            }
        return {
            "ok": True,
            "available": available,
            "required_margin": required_margin,
            "span_margin": span_margin,
            "shortfall": 0,
            "message": "",
        }

    def check_funds_before_orders(
        self,
        legs: Sequence[Tuple[Any, Optional[float]]],
        *,
        include_position: bool = True,
        include_orders: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """
        Multi-leg margin (hedge benefit) for same-structure ENTRY legs.
        ``legs``: list of (intent, execution_price).
        """
        if not legs:
            return None
        if len(legs) == 1:
            return self.check_funds_before_order(legs[0][0], legs[0][1])

        payloads: List[Dict[str, Any]] = []
        for intent, execution_price in legs:
            try:
                payloads.append(self._build_payload(intent, execution_price))
            except Exception:
                return None

        available = self._get_available_balance()
        if available is None:
            return None

        tsl = getattr(getattr(self.api, "_source", None), "tsl", None)
        if not tsl or not getattr(tsl, "margin_calculator_multi", None):
            total_required = 0.0
            for intent, execution_price in legs:
                single = self.check_funds_before_order(intent, execution_price)
                if single is None:
                    return None
                if not single.get("ok", True):
                    return single
                total_required += float(single.get("required_margin") or 0)
            ok, shortfall = self._parse_margin_shortfall(available, total_required, 0)
            return {
                "ok": ok,
                "available": available,
                "required_margin": total_required,
                "span_margin": None,
                "shortfall": shortfall,
                "hedge_benefit": None,
                "leg_count": len(legs),
                "message": (
                    f"Multi-leg (sum of singles): available={available:.2f} "
                    f"required={total_required:.2f} shortfall={shortfall:.2f}"
                ),
            }

        try:
            oc = tsl.margin_calculator_multi(
                payloads,
                include_position=include_position,
                include_orders=include_orders,
            )
        except Exception as exc:
            logger.warning("margin_calculator_multi failed: %s", exc)
            return None

        if not isinstance(oc, dict):
            return None

        required_margin = float(
            oc.get("total_margin")
            or oc.get("totalMargin")
            or oc.get("total_margin_required")
            or 0
        )
        span_margin = float(oc.get("span_margin") or oc.get("spanMargin") or 0) or None
        hedge_benefit = oc.get("hedge_benefit") or oc.get("hedgeBenefit")
        ok, shortfall = self._parse_margin_shortfall(available, required_margin, 0)
        msg = (
            f"Multi-leg margin: available={available:.2f} required={required_margin:.2f} "
            f"legs={len(legs)}"
        )
        if hedge_benefit not in (None, ""):
            msg += f" hedge_benefit={hedge_benefit}"
        if not ok:
            msg += f"; shortfall={shortfall:.2f}"

        return {
            "ok": ok,
            "available": available,
            "required_margin": required_margin,
            "span_margin": span_margin,
            "shortfall": shortfall,
            "hedge_benefit": hedge_benefit,
            "leg_count": len(legs),
            "message": msg,
        }

    def modify_order_price(
        self,
        intent,
        broker_order_id: str,
        execution_price: Optional[float] = None,
    ) -> bool:
        """Modify a pending Dhan limit order to a new price (hedge retry)."""
        oid = str(broker_order_id or "").strip()
        if not oid:
            return False
        if not self.note_dhan_modify(oid):
            return False
        try:
            payload = self._build_payload(intent, execution_price)
        except Exception as exc:
            logger.warning("modify_order_price build_payload failed: %s", exc)
            return False
        source = getattr(self.api, "_source", None)
        tsl = getattr(source, "tsl", None) if source is not None else None
        if tsl is None or not getattr(tsl, "modify_order", None):
            return False
        try:
            GlobalRateLimiter.instance().acquire(DHAN_ORDER_API, 0.11)
            result = tsl.modify_order(
                order_id=oid,
                order_type=str(payload.get("order_type") or "LIMIT"),
                quantity=int(payload.get("quantity") or 0),
                price=float(payload.get("price") or 0),
                trigger_price=float(payload.get("trigger_price") or 0),
                disclosed_quantity=int(payload.get("disclosed_quantity") or 0),
                validity=str(payload.get("validity") or "DAY"),
            )
            return bool(result)
        except Exception as exc:
            logger.warning(
                "Dhan modify_order_price failed order_id=%s intent_id=%s: %s",
                oid,
                getattr(intent, "intent_id", None),
                exc,
            )
            return False

    def order_is_open(self, broker_order_id: str) -> bool:
        row = self.find_order_by_id(broker_order_id)
        if not isinstance(row, dict):
            return False
        status = str(row.get("orderStatus") or row.get("status") or "").lower()
        closed = {
            "filled",
            "traded",
            "complete",
            "completed",
            "cancelled",
            "rejected",
            "expired",
            "trigger cancelled",
        }
        return status not in closed

    def cancel_order_by_id(
        self,
        order_id: str,
        *,
        intent_id: Optional[str] = None,
        reason: str = "",
    ) -> bool:
        _ = reason
        source = getattr(self.api, "_source", None)
        if source is None:
            return False
        execution_mode = ""
        if intent_id and self.intent_store:
            rec = self.intent_store.get(str(intent_id)) or {}
            sm = (rec.get("payload") or {}).get("strategy_meta") or {}
            if isinstance(sm, dict):
                execution_mode = str(sm.get("execution_mode") or "").upper()

        def _cancel_forever() -> bool:
            if not hasattr(source, "cancel_forever_order"):
                return False
            try:
                source.cancel_forever_order(str(order_id))
                return True
            except Exception as exc:
                logger.warning(
                    "Dhan cancel_forever_order failed order_id=%s: %s", order_id, exc
                )
                return False

        def _cancel_regular() -> bool:
            if not hasattr(source, "cancel_order"):
                return False
            try:
                source.cancel_order(str(order_id))
                return True
            except Exception as exc:
                logger.warning("Dhan cancel_order failed order_id=%s: %s", order_id, exc)
                return False

        if execution_mode in ("GTT", "HYBRID_GTT"):
            return _cancel_forever() or _cancel_regular()
        if _cancel_regular():
            return True
        return _cancel_forever()

    def _place_forever_order(self, order_payload: Dict[str, Any], intent_id: str, retries: int):
        for attempt in range(retries + 1):
            try:
                GlobalRateLimiter.instance().acquire(DHAN_ORDER_API, 0.11)
                logger.info(
                    "Dhan place_forever_order attempt=%s/%s intent_id=%s payload=%s",
                    attempt + 1,
                    retries + 1,
                    intent_id,
                    order_payload,
                )
                resp = self.api.place_forever_order(
                    tradingsymbol=order_payload["tradingsymbol"],
                    exchange=order_payload["exchange"],
                    quantity=order_payload["quantity"],
                    price=order_payload["price"],
                    trigger_price=order_payload["trigger_price"],
                    order_type=order_payload["order_type"],
                    transaction_type=order_payload["transaction_type"],
                    trade_type=order_payload["trade_type"],
                    order_flag=order_payload.get("order_flag") or "SINGLE",
                    disclosed_quantity=order_payload["disclosed_quantity"],
                    validity=order_payload["validity"],
                    tag=order_payload["tag"],
                    correlation_id=order_payload.get("correlation_id") or order_payload["tag"],
                )
                if not isinstance(resp, dict):
                    raise Exception(f"Invalid broker response: {resp}")
                if resp.get("status") != "success":
                    parsed = parse_dhan_api_error(resp)
                    fail_msg = (
                        parsed.get("display_message")
                        or resp.get("message")
                        or str(resp)
                    )
                    self._last_place_order_failure = {
                        "message": fail_msg,
                        "display_message": fail_msg,
                        "error_code": resp.get("error_code") or parsed.get("error_code"),
                        "error_type": resp.get("error_type") or parsed.get("error_type"),
                        "error_message": resp.get("error_message")
                        or parsed.get("error_message"),
                        "payload": resp.get("payload") or order_payload,
                        "response": resp,
                        "attempt": attempt + 1,
                    }
                    logger.warning(
                        "Dhan broker place_forever_order rejected intent_id=%s attempt=%s payload=%s response=%s",
                        intent_id,
                        attempt + 1,
                        order_payload,
                        resp,
                    )
                    return None
                order_id = resp.get("order_id")
                if order_id and self.intent_store:
                    self.intent_store.update(intent_id, "SENT")
                return order_id
            except Exception as e:
                parsed = parse_dhan_api_error(e)
                fail_msg = parsed.get("display_message") or str(e)
                self._last_place_order_failure = {
                    "message": fail_msg,
                    "display_message": fail_msg,
                    "error_code": parsed.get("error_code"),
                    "error_type": parsed.get("error_type"),
                    "error_message": parsed.get("error_message"),
                    "payload": order_payload,
                    "response": (
                        e.args[0]
                        if getattr(e, "args", None) and isinstance(e.args[0], dict)
                        else None
                    ),
                    "attempt": attempt + 1,
                }
                logger.warning(
                    "Dhan place_forever_order exception intent_id=%s attempt=%s payload=%s error=%s",
                    intent_id,
                    attempt + 1,
                    order_payload,
                    fail_msg,
                )
                if attempt == retries:
                    return None
                time.sleep(0.4)
        return None

    def place_order(self, intent, execution_price=None, retries=2):
        tag_u = str(getattr(intent, "tag", "") or "").upper()
        act_u = str(getattr(intent, "action", "") or "").upper()
        stid = getattr(intent, "structure_id", None)
        if tag_u == "MAIN_EXIT" and act_u == "EXIT" and stid:
            reg = getattr(getattr(self, "order_router", None), "bracket_registry", None)
            if reg is not None:
                reg.cancel_all_for_structure(
                    str(stid),
                    broker=self,
                    order_router=self.order_router,
                    reason="MAIN_EXIT",
                )

        order_payload = self._build_payload(intent, execution_price)
        intent_id = order_payload["intent_id"]
        self._last_place_order_failure = None
        if str(order_payload.get("execution_mode") or "").upper() in ("GTT", "HYBRID_GTT"):
            return self._place_forever_order(order_payload, intent_id, retries)
        for attempt in range(retries + 1):
            try:
                GlobalRateLimiter.instance().acquire(DHAN_ORDER_API, 0.11)
                logger.info(
                    "Dhan place_order attempt=%s/%s intent_id=%s payload=%s",
                    attempt + 1,
                    retries + 1,
                    intent_id,
                    order_payload,
                )
                resp = self.api.place_order(
                    tradingsymbol=order_payload["tradingsymbol"],
                    exchange=order_payload["exchange"],
                    quantity=order_payload["quantity"],
                    price=order_payload["price"],
                    trigger_price=order_payload["trigger_price"],
                    order_type=order_payload["order_type"],
                    transaction_type=order_payload["transaction_type"],
                    trade_type=order_payload["trade_type"],
                    disclosed_quantity=order_payload["disclosed_quantity"],
                    after_market_order=order_payload["after_market_order"],
                    validity=order_payload["validity"],
                    amo_time=order_payload["amo_time"],
                    bo_profit_value=order_payload["bo_profit_value"],
                    bo_stop_loss_value=order_payload["bo_stop_loss_value"],
                    tag=order_payload["tag"],
                    correlation_id=order_payload.get("correlation_id") or order_payload["tag"],
                )
                if not isinstance(resp, dict):
                    raise Exception(f"Invalid broker response: {resp}")
                if resp.get("status") != "success":
                    parsed = parse_dhan_api_error(resp)
                    fail_msg = (
                        parsed.get("display_message")
                        or resp.get("message")
                        or str(resp)
                    )
                    self._last_place_order_failure = {
                        "message": fail_msg,
                        "display_message": fail_msg,
                        "error_code": resp.get("error_code") or parsed.get("error_code"),
                        "error_type": resp.get("error_type") or parsed.get("error_type"),
                        "error_message": resp.get("error_message")
                        or parsed.get("error_message"),
                        "payload": resp.get("payload") or order_payload,
                        "response": resp,
                        "attempt": attempt + 1,
                    }
                    logger.warning(
                        "Dhan broker place_order rejected intent_id=%s attempt=%s payload=%s response=%s",
                        intent_id,
                        attempt + 1,
                        order_payload,
                        resp,
                    )
                    return None
                order_id = resp.get("order_id")
                if order_id:
                    self.clear_dhan_modify_count(str(order_id))
                if self.intent_store:
                    self.intent_store.update(intent_id, "SENT")
                return order_id
            except TimeoutError:
                existing = self.find_order_by_client_id(intent_id)
                if existing:
                    return existing.get("order_id")
                if attempt == retries:
                    raise Exception("Order failed after retries")
                time.sleep(0.4)
            except Exception as e:
                parsed = parse_dhan_api_error(e)
                fail_msg = parsed.get("display_message") or str(e)
                self._last_place_order_failure = {
                    "message": fail_msg,
                    "display_message": fail_msg,
                    "error_code": parsed.get("error_code"),
                    "error_type": parsed.get("error_type"),
                    "error_message": parsed.get("error_message"),
                    "payload": order_payload,
                    "response": (
                        e.args[0]
                        if getattr(e, "args", None) and isinstance(e.args[0], dict)
                        else None
                    ),
                    "attempt": attempt + 1,
                }
                logger.warning(
                    "Dhan place_order exception intent_id=%s attempt=%s payload=%s error=%s",
                    intent_id,
                    attempt + 1,
                    order_payload,
                    e,
                    exc_info=True,
                )
                return None
        return None

    def get_all_forever_orders_raw(self) -> List[Dict[str, Any]]:
        """All Forever (GTT) orders including traded/cancelled (for fill detection)."""
        if not getattr(self.api, "get_forever_orders", None):
            return []
        try:
            orders = self.api.get_forever_orders() or []
        except Exception as exc:
            logger.warning("Dhan get_forever_orders failed: %s", exc)
            return []
        if isinstance(orders, list):
            return [o for o in orders if isinstance(o, dict)]
        return []

    def _normalize_forever_order_for_recon(self, o: Dict[str, Any]) -> Dict[str, Any]:
        """Map a raw Forever order row to reconciliation fields (incl. traded)."""
        status = (o.get("orderStatus") or o.get("status") or "").lower()
        try:
            qty = float(o.get("quantity") or o.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        try:
            filled = float(
                o.get("tradedQty")
                or o.get("traded_qty")
                or o.get("filledQty")
                or o.get("filled_qty")
                or 0
            )
        except (TypeError, ValueError):
            filled = 0.0
        traded_statuses = {"traded", "complete", "completed"}
        if status in traded_statuses and filled <= 0 and qty > 0:
            filled = qty
        if filled <= 0 and status in traded_statuses:
            filled = qty
        recon_status = status
        if status in traded_statuses or (qty > 0 and filled >= qty):
            recon_status = "filled"
        try:
            avg_px = float(
                o.get("averageTradedPrice")
                or o.get("average_traded_price")
                or o.get("price")
                or 0
            )
        except (TypeError, ValueError):
            avg_px = 0.0
        corr = o.get("correlationId") or o.get("tag") or ""
        return {
            "order_id": o.get("orderId") or o.get("order_id"),
            "tag": corr,
            "correlationId": corr,
            "status": recon_status,
            "quantity": qty,
            "size": qty,
            "filled_size": filled,
            "filled": filled,
            "average_fill_price": avg_px,
            "is_forever": True,
            "symbol": o.get("tradingSymbol") or o.get("trading_symbol"),
        }

    def find_forever_order_by_client_id(
        self, client_order_id: str
    ) -> Optional[Dict[str, Any]]:
        """Find a Forever order by correlationId/tag (any status, incl. traded)."""
        cid = str(client_order_id or "").strip()
        if not cid:
            return None
        dhan_cid = dhan_correlation_id(cid)
        for o in self.get_all_forever_orders_raw():
            tag = str(o.get("correlationId") or o.get("tag") or "").strip()
            if tag == cid or tag == dhan_cid:
                return self._normalize_forever_order_for_recon(o)
        return None

    def find_order_by_id(self, broker_order_id: str) -> Optional[Dict[str, Any]]:
        """Lookup order by Dhan orderId (REST GET /orders/{id})."""
        oid = str(broker_order_id or "").strip()
        if not oid:
            return None
        fn = getattr(self.api, "get_order_by_id", None)
        if callable(fn):
            try:
                row = fn(oid)
                if isinstance(row, dict) and row:
                    return row
            except Exception as exc:
                logger.warning("Dhan find_order_by_id failed order_id=%s: %s", oid, exc)
        for o in self.api.get_order_list() or []:
            if str(o.get("orderId") or o.get("order_id") or "") == oid:
                return o
        return None

    def find_order_by_client_id(self, client_order_id):
        orders = self.api.get_order_list() or []
        cid = str(client_order_id or "").strip()
        dhan_cid = dhan_correlation_id(cid)
        for o in orders:
            tag = str(o.get("tag") or o.get("correlationId") or "").strip()
            if tag == cid or tag == dhan_cid:
                return o
        forever = self.find_forever_order_by_client_id(client_order_id)
        if forever:
            return forever
        return None

    def get_forever_open_orders(self) -> List[Dict[str, Any]]:
        """Pending Forever (GTT) orders for reconciliation (not in regular order book)."""
        closed_statuses = {
            "traded",
            "cancelled",
            "rejected",
            "expired",
            "complete",
            "completed",
        }
        out: List[Dict[str, Any]] = []
        for o in self.get_all_forever_orders_raw():
            status = (o.get("orderStatus") or o.get("status") or "").lower()
            if status in closed_statuses:
                continue
            norm = self._normalize_forever_order_for_recon(o)
            out.append(norm)
        return out

    def get_recent_fills(self, page_size: int = 50) -> List[Dict[str, Any]]:
        """Recent fills from order list (TRADED/filled) for trade-led OMS sync."""
        if not getattr(self.api, "get_fills", None):
            return []
        try:
            return self.api.get_fills(page_size=page_size) or []
        except Exception:
            return []

    def get_fill_for_client_order_id(
        self, client_order_id: str, page_size: int = 50
    ) -> Optional[Dict[str, Any]]:
        """
        Resolve fill price/size for a given intent_id (tag) from filled orders.
        For trade-led OMS: do not assume filled with price=0 when order is missing.
        """
        fills = self.get_recent_fills(page_size=page_size)
        dhan_cid = dhan_correlation_id(client_order_id)
        for f in fills:
            fcid = str(f.get("client_order_id") or f.get("tag") or "").strip()
            if fcid == client_order_id or fcid == dhan_cid:
                price = float(f.get("price") or 0)
                size = float(f.get("size") or 0)
                if price > 0 and size > 0:
                    return {
                        "order_id": str(f.get("order_id", "")),
                        "price": price,
                        "size": size,
                        "side": (f.get("side") or "").upper(),
                    }
        return None

    def get_fill_by_order_id(
        self, broker_order_id: str, page_size: int = 50
    ) -> Optional[Dict[str, Any]]:
        """
        Resolve fill by broker order_id when fill/order list does not return tag.
        Returns dict with price, size, side, order_id.
        """
        if not broker_order_id:
            return None
        fills = self.get_recent_fills(page_size=page_size)
        bid_str = str(broker_order_id)
        for f in fills:
            if str(f.get("order_id") or f.get("id") or "") == bid_str:
                price = float(f.get("price") or 0)
                size = float(f.get("size") or 0)
                if price > 0 and size > 0:
                    return {
                        "order_id": bid_str,
                        "price": price,
                        "size": size,
                        "side": (f.get("side") or "").upper(),
                    }
        return None

    def get_positions(self):
        return self.api.get_positions()

    @staticmethod
    def _position_row_value(row, *column_names, default=0):
        """Read a position field from a pandas Series with API column name fallbacks."""
        for name in column_names:
            try:
                if hasattr(row, "index") and name not in row.index:
                    continue
                val = row[name] if hasattr(row, "index") else row.get(name)
                if val is None:
                    continue
                if isinstance(val, float) and val != val:
                    continue
                return val
            except (KeyError, TypeError, ValueError):
                continue
        return default

    def get_positions_for_recon(self):
        df = self.api.get_positions()
        if df is None:
            return {}
        if isinstance(df, dict):
            return {}
        try:
            if getattr(df, "empty", True):
                return {}
        except Exception:
            return {}
        broker_positions = {}
        for _, row in df.iterrows():
            sym = self._position_row_value(
                row,
                "tradingSymbol",
                "trading_symbol",
                "symbol",
                default=None,
            )
            if not sym:
                continue
            qty_raw = self._position_row_value(
                row, "netQty", "net_qty", "quantity", default=0
            )
            avg_raw = self._position_row_value(
                row,
                "avgPrice",
                "avg_price",
                "averagePrice",
                "costPrice",
                "buyAvg",
                "sellAvg",
                default=0,
            )
            segment = self._position_row_value(
                row, "segment", "exchangeSegment", default="EQ"
            )
            lot_raw = self._position_row_value(row, "lotSize", "lot_size", default=1)
            try:
                broker_positions[str(sym)] = {
                    "qty": int(qty_raw),
                    "avg_price": float(avg_raw),
                    "segment": str(segment or "EQ"),
                    "lot_size": max(1, int(lot_raw)),
                }
            except (TypeError, ValueError) as e:
                logger.warning(
                    "Skipping position row for recon sym=%s: %s", sym, e
                )
        return broker_positions

    def sync_positions(self):
        if not self.position_manager:
            return
        broker_positions = self.get_positions_for_recon()
        if broker_positions:
            self.position_manager.reconcile_with_broker(broker_positions)

    def exit_position(self, trading_symbol, qty, side, segment="EQ", lot_size=1):
        exit_side = "SELL" if side == "BUY" else "BUY"
        eid = f"exit_{uuid.uuid4().hex[:6]}"
        intent = {
            "intent_id": eid,
            "trading_symbol": trading_symbol,
            "side": exit_side,
            "qty": int(qty),
            "segment": segment,
            "lot_size": int(lot_size),
            "order_type": "MARKET",
            "trade_type": "MARGIN",
            "correlation_id": eid,
        }
        return self.place_order(intent, execution_price=None)

    def get_open_orders(self):
        """Open/pending orders for order-state consistency. Dhan: filter by orderStatus not in filled/cancelled/rejected."""
        orders = self.api.get_order_list() or []
        if not orders:
            return []
        # Dhan orderbook: record may have orderStatus, orderId, tag, etc.
        closed_statuses = {"filled", "cancelled", "rejected", "complete", "completed", "trigger cancelled"}
        out = []
        for o in orders if isinstance(orders, list) else []:
            status = (o.get("orderStatus") or o.get("status") or "").lower()
            if status in closed_statuses:
                continue
            out.append({
                "order_id": o.get("orderId") or o.get("order_id"),
                "tag": o.get("tag") or o.get("correlationId") or o.get("intent_id"),
                "status": status or "open",
            })
        return out

    def note_dhan_modify(self, broker_order_id: str) -> bool:
        """
        Call before each Dhan modify_order on the same broker order id.
        Returns False when modify count would exceed DHAN_MODIFY_WARN_THRESHOLD (20):
        caller should cancel + re-place instead (Dhan hard limit 25).
        """
        oid = str(broker_order_id)
        next_c = self._dhan_modify_counts.get(oid, 0) + 1
        if next_c > self.DHAN_MODIFY_WARN_THRESHOLD:
            logger.warning(
                "Dhan modify limit: order_id=%s would reach modify #%s — use cancel + re-place",
                oid,
                next_c,
            )
            return False
        self._dhan_modify_counts[oid] = next_c
        return True

    def clear_dhan_modify_count(self, broker_order_id: Optional[str]) -> None:
        if broker_order_id:
            self._dhan_modify_counts.pop(str(broker_order_id), None)

    def should_cancel_reorder_instead_of_modify(self, broker_order_id: str) -> bool:
        return self._dhan_modify_counts.get(str(broker_order_id), 0) >= self.DHAN_MODIFY_WARN_THRESHOLD
