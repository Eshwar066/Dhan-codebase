"""Dhan broker: order placement via DhanBrokerApi. Trade-led OMS via get_recent_fills / get_fill_for_client_order_id."""

import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

from core.broker.base import BaseBroker
from core.broker.internal.dhan import mappings as dhan_mappings
from core.broker.internal.dhan.mappings import dhan_correlation_id
from core.utils.global_rate_limiter import DHAN_ORDER_API, GlobalRateLimiter


def _order_intent_to_payload(intent, execution_price=None):
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
    return {
        "tradingsymbol": inst.place_order_symbol(),
        "exchange": exchange,
        "quantity": total_qty,
        "price": float(price),
        "trigger_price": float(getattr(intent, "trigger_price", 0) or 0),
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
    }


class DhanBroker(BaseBroker):
    """Order placement via Dhan. Uses IBrokerApi (DhanBrokerApi)."""

    # Dhan docs: max 25 modifications per order — switch to cancel + re-place before hard failure.
    DHAN_MODIFY_WARN_THRESHOLD = 20

    def __init__(self, api, position_manager=None, intent_store=None):
        super().__init__(position_manager=position_manager, intent_store=intent_store)
        self.api = api
        self._dhan_modify_counts: Dict[str, int] = {}
        self._last_place_order_failure: Optional[Dict[str, Any]] = None

    def _build_payload(self, intent, execution_price=None):
        if hasattr(intent, "instrument"):
            return _order_intent_to_payload(intent, execution_price)
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
        return {
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

    def place_order(self, intent, execution_price=None, retries=2):
        order_payload = self._build_payload(intent, execution_price)
        intent_id = order_payload["intent_id"]
        self._last_place_order_failure = None
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
                    fail_msg = resp.get("message") or str(resp)
                    self._last_place_order_failure = {
                        "message": fail_msg,
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
                self._last_place_order_failure = {
                    "message": str(e),
                    "payload": order_payload,
                    "response": None,
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

    def find_order_by_client_id(self, client_order_id):
        orders = self.api.get_order_list() or []
        cid = str(client_order_id or "").strip()
        dhan_cid = dhan_correlation_id(cid)
        for o in orders:
            tag = str(o.get("tag") or o.get("correlationId") or "").strip()
            if tag == cid or tag == dhan_cid:
                return o
        return None

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

    def get_positions_for_recon(self):
        df = self.api.get_positions()
        if df is None or df.empty:
            return {}
        broker_positions = {}
        for _, row in df.iterrows():
            sym = row["tradingSymbol"]
            broker_positions[sym] = {
                "qty": int(row["netQty"]),
                "avg_price": float(row["avgPrice"]),
                "segment": row.get("segment", "EQ"),
                "lot_size": int(row.get("lotSize", 1)),
            }
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
                "tag": o.get("tag") or o.get("intent_id"),
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
