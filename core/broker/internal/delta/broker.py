"""Delta Exchange broker: order placement via DeltaBrokerApi (delta_rest_client)."""

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from core.broker.base import BaseBroker

logger = logging.getLogger(__name__)


def _get_reduce_only(action: str) -> bool:
    """
    OMS rule: ENTRY → reduce_only=False (open/increase position);
    EXIT → reduce_only=True (only reduce existing position).
    Prevents accidental position flips when exit and entry signals are reordered.
    """
    return (action or "").upper() in {"EXIT", "FORCE_EXIT"}


def _intent_to_delta_payload(intent, execution_price=None):
    """Build payload for DeltaBrokerApi.place_order from OrderIntent or dict."""
    if hasattr(intent, "instrument"):
        inst = intent.instrument
        trading_symbol = getattr(inst, "trading_symbol", "") or getattr(
            inst, "custom_symbol", ""
        )
        segment = getattr(inst, "segment", "EQ")
        qty = int(getattr(intent, "qty", getattr(inst, "lot_size", 1)))
        lot_size = int(getattr(inst, "lot_size", 1))
        total_qty = qty * lot_size
        price = execution_price if execution_price is not None else (intent.price or 0)
        action = getattr(intent, "action", "")
        return {
            "tradingsymbol": trading_symbol,
            "exchange": segment,
            "quantity": total_qty,
            "price": float(price),
            "trigger_price": float(getattr(intent, "trigger_price", 0) or 0),
            "order_type": getattr(intent, "order_type", "MARKET"),
            "transaction_type": intent.side,
            "trade_type": getattr(intent, "trade_type", "MARGIN"),
            "tag": intent.intent_id,
            "reduce_only": "true" if _get_reduce_only(action) else "false",
        }
    # Dict intent
    total_qty = int(intent.get("qty", 1)) * int(intent.get("lot_size", 1))
    price = (
        execution_price
        if execution_price is not None
        else float(intent.get("price", 0) or 0)
    )
    action = intent.get("action", "")
    reduce_only = "true" if _get_reduce_only(action) else intent.get("reduce_only", "false")
    return {
        "tradingsymbol": intent.get("trading_symbol", ""),
        "exchange": intent.get("segment", "EQ"),
        "quantity": total_qty,
        "price": price,
        "trigger_price": float(intent.get("trigger_price", 0) or 0),
        "order_type": intent.get("order_type", "MARKET"),
        "transaction_type": intent.get("side", "BUY"),
        "trade_type": intent.get("trade_type", "MARGIN"),
        "tag": intent.get("intent_id"),
        "reduce_only": reduce_only if reduce_only in ("true", "false") else "false",
    }


def _delta_required_margin(intent, execution_price=None, leverage: int = 1):
    """Estimate initial margin: contract notional divided by configured leverage."""
    lev = max(1, int(leverage or 1))
    if hasattr(intent, "instrument"):
        inst = intent.instrument
        qty = int(getattr(intent, "qty", getattr(inst, "lot_size", 1)))
        lot = int(getattr(inst, "lot_size", 1))
        price = execution_price if execution_price is not None else (intent.price or 0)
        mult = getattr(inst, "contract_multiplier", 1)
        notional = abs(qty) * lot * float(price) * float(mult)
        return notional / lev
    notional = (
        int(intent.get("qty", 1))
        * int(intent.get("lot_size", 1))
        * float(execution_price or intent.get("price") or 0)
    )
    return notional / lev


class DeltaBroker(BaseBroker):
    """Order placement via Delta Exchange. Uses DeltaBrokerApi (DeltaSource / delta_rest_client)."""

    def __init__(
        self,
        api,
        position_manager=None,
        intent_store=None,
        default_leverage: int = 1,
    ):
        super().__init__(position_manager=position_manager, intent_store=intent_store)
        self.api = api
        self._realtime_feed: Optional[Any] = None
        self.default_leverage = max(1, int(default_leverage or 1))
        self._last_place_order_failure: Optional[Dict[str, Any]] = None

    def supports_combined_bracket(self) -> bool:
        return hasattr(self.api, "place_bracket_tp_sl")

    def set_realtime_feed(self, feed: Any) -> None:
        """Attach Delta WS feed for orders/positions (REST remains fallback)."""
        self._realtime_feed = feed

    @staticmethod
    def _wallet_available(wallet: Optional[Dict[str, Any]]) -> Optional[float]:
        if not isinstance(wallet, dict):
            return None
        for key in (
            "available_balance",
            "availableBalance",
            "balance",
            "withdrawable_balance",
        ):
            v = wallet.get(key)
            if v is None:
                continue
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
        return None

    def get_balance_snapshot(self) -> Optional[Dict[str, Any]]:
        """
        Fetch wallet balances used by Delta funds checks and return a log-friendly snapshot.
        """
        source = getattr(self.api, "_source", None)
        if source is None or not getattr(source, "get_balances", None):
            return None
        try:
            usd_wallet = source.get_balances(14)  # USD
            inr_wallet = source.get_balances(204)  # INR
            usd_available = self._wallet_available(usd_wallet)
            inr_available = self._wallet_available(inr_wallet)
            selected_available = (
                usd_available
                if usd_available is not None
                else inr_available
            )
            return {
                "usd_available": usd_available,
                "inr_available": inr_available,
                "selected_available": selected_available,
                "usd_wallet_present": isinstance(usd_wallet, dict),
                "inr_wallet_present": isinstance(inr_wallet, dict),
            }
        except Exception as e:
            logger.warning("Delta balance snapshot failed: %s", e)
            return None

    def check_funds_before_order(
        self,
        intent: Any,
        execution_price: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Check available wallet balance vs required notional before placing order.
        Delta does not expose SPAN; uses wallet balance as proxy.
        """
        # pdb.set_trace()
        try:
            required = _delta_required_margin(
                intent, execution_price, leverage=self.default_leverage
            )
        except Exception as e:
            logger.warning("Delta funds check: failed to compute required margin: %s", e)
            return None

        snapshot = self.get_balance_snapshot()
        if not isinstance(snapshot, dict):
            return None

        try:
            available = snapshot.get("selected_available")
            if available is None:
                return None
            available = float(available)

            # Guard against false negatives from stale/mismatched wallet fields.
            # If available is zero/negative, let broker-side validation decide.
            if available <= 0:
                logger.warning(
                    "Delta funds check advisory-only: selected_available=%s (usd=%s, inr=%s). "
                    "Skipping local block and letting broker validate.",
                    available,
                    snapshot.get("usd_available"),
                    snapshot.get("inr_available"),
                )
                return None

            if available < required:
                shortfall = required - available
                return {
                    "ok": False,
                    "available": available,
                    "required_margin": required,
                    "span_margin": None,
                    "shortfall": shortfall,
                    "message": (
                        f"Available={available:.2f}, required={required:.2f}; shortfall={shortfall:.2f}"
                    ),
                }

            return {
                "ok": True,
                "available": available,
                "required_margin": required,
                "span_margin": None,
                "shortfall": 0,
                "message": "",
            }

        except Exception as e:
            logger.warning("Delta funds check: balance fetch failed: %s", e)
            return None

    def place_order(
        self,
        intent: Any,
        execution_price: Optional[float] = None,
        retries: int = 0,
    ) -> Optional[str]:
        self._last_place_order_failure = None
        payload = _intent_to_delta_payload(intent, execution_price)
        for attempt in range(retries + 1):
            try:
                ot = str(payload.get("order_type") or "MARKET").upper()
                if ot in {"SL", "SL-M", "STOP", "STOP_MARKET", "STOP_LIMIT"}:
                    stop_ot = "MARKET" if ot in {"SL-M", "STOP_MARKET"} else "LIMIT"
                    limit_price = payload["price"] if stop_ot == "LIMIT" else None
                    result = None
                    stop_retries = 3
                    for stop_attempt in range(stop_retries):
                        try:
                            result = self.api.place_bracket_stop_loss(
                                tradingsymbol=payload["tradingsymbol"],
                                quantity=payload["quantity"],
                                transaction_type=payload["transaction_type"],
                                trigger_price=payload["trigger_price"] or payload["price"],
                                price=limit_price,
                                stop_trigger_method="mark_price",
                                tag=payload.get("tag"),
                            )
                        except Exception as stop_e:
                            err_txt = str(stop_e).lower()
                            if (
                                "no_open_position" in err_txt
                                and stop_attempt < (stop_retries - 1)
                            ):
                                logger.warning(
                                    "Delta stop-order no_open_position for %s "
                                    "(attempt %s/%s); retrying in 60s",
                                    payload.get("tradingsymbol"),
                                    stop_attempt + 1,
                                    stop_retries,
                                )
                                time.sleep(60)
                                continue
                            raise
                        if result.get("status") == "success":
                            break
                        err_txt = str(result).lower()
                        if (
                            "no_open_position" in err_txt
                            and stop_attempt < (stop_retries - 1)
                        ):
                            logger.warning(
                                "Delta stop-order no_open_position for %s "
                                "(attempt %s/%s); retrying in 60s",
                                payload.get("tradingsymbol"),
                                stop_attempt + 1,
                                stop_retries,
                            )
                            time.sleep(60)
                            continue
                        break
                else:
                    result = self.api.place_order(
                        tradingsymbol=payload["tradingsymbol"],
                        exchange=payload["exchange"],
                        quantity=payload["quantity"],
                        price=payload["price"],
                        trigger_price=payload["trigger_price"],
                        order_type=payload["order_type"],
                        transaction_type=payload["transaction_type"],
                        trade_type=payload["trade_type"],
                        tag=payload.get("tag"),
                        reduce_only=payload.get("reduce_only", "false"),
                    )
                if result.get("status") == "success":
                    if self.intent_store and payload.get("tag"):
                        self.intent_store.update(payload["tag"], "SENT")
                    return result.get("order_id")
                err_txt = str(result).lower()
                self._last_place_order_failure = {
                    "message": str(result),
                    "error_code": ((result or {}).get("error") or {}).get("code")
                    if isinstance((result or {}).get("error"), dict)
                    else None,
                    "retryable": "no_open_position" in err_txt,
                }
                logger.warning("Delta place_order returned error: %s", result)
                return None
            except Exception as e:
                err_txt = str(e).lower()
                if attempt == retries:
                    ot = str(payload.get("order_type") or "MARKET").upper()
                    if ot in {"SL", "SL-M", "STOP", "STOP_MARKET", "STOP_LIMIT"} and (
                        "no_open_position" in err_txt
                    ):
                        self._last_place_order_failure = {
                            "message": str(e),
                            "error_code": "no_open_position",
                            "retryable": True,
                        }
                        logger.warning(
                            "Delta stop-order no_open_position for %s after 3 attempts; "
                            "skipping broker-side SL intent and relying on strategy exit logic. error=%s",
                            payload.get("tradingsymbol"),
                            e,
                        )
                        return None
                    if ot in {"SL", "SL-M", "STOP", "STOP_MARKET", "STOP_LIMIT"} and (
                        "bracket_order_exists" in err_txt
                    ):
                        self._last_place_order_failure = {
                            "message": str(e),
                            "error_code": "bracket_order_exists",
                            "retryable": False,
                        }
                        logger.warning(
                            "Delta bracket already exists for %s; "
                            "use combined TP+SL placement instead. error=%s",
                            payload.get("tradingsymbol"),
                            e,
                        )
                        return None
                    if ot in {"SL", "SL-M", "STOP", "STOP_MARKET", "STOP_LIMIT"} and (
                        "unsupported" in err_txt or "400" in err_txt
                    ):
                        self._last_place_order_failure = {
                            "message": str(e),
                            "error_code": "unsupported_stop",
                            "retryable": False,
                        }
                        logger.warning(
                            "Delta stop-order unsupported for %s on current environment; "
                            "skipping broker-side SL intent and relying on strategy exit logic. error=%s",
                            payload.get("tradingsymbol"),
                            e,
                        )
                        return None
                    logger.warning("Delta place_order exception (final attempt): %s", e, exc_info=True)
                    raise
                time.sleep(0.3)
        return None

    def exit_position(
        self,
        trading_symbol: str,
        qty: int,
        side: str,
        segment: str = "EQ",
        lot_size: int = 1,
    ) -> Optional[str]:
        exit_side = "SELL" if side == "BUY" else "BUY"
        intent = {
            "intent_id": f"exit_{uuid.uuid4().hex[:6]}",
            "trading_symbol": trading_symbol,
            "side": exit_side,
            "qty": int(qty),
            "segment": segment,
            "lot_size": int(lot_size),
            "order_type": "MARKET",
            "trade_type": "MARGIN",
            "reduce_only": "true",
        }
        return self.place_order(intent, execution_price=None)

    def find_order_by_client_id(self, client_order_id: str):
        """Find order in live list; if not there, look up in /v2/orders/history and /v2/fills."""
        for o in self.api.get_order_list() or []:
            if o.get("tag") == client_order_id:
                return o
        return self._find_order_in_history_or_fills(client_order_id)

    def _find_order_in_history_or_fills(self, client_order_id: str):
        """Resolve order status from order history or fills when not in live list."""
        if not hasattr(self.api, "get_orders_history"):
            return None
        # 1) Try order history (uses order_history; page_size=50)
        try:
            history = self.api.get_orders_history(page_size=50)
        except Exception as e:
            logger.debug("Delta get_orders_history failed: %s", e)
            history = []
        for o in history or []:
            tag = o.get("client_order_id") or o.get("tag")
            if tag != client_order_id:
                continue
            # Normalize to same shape as get_order_list for router
            state = (o.get("state") or o.get("status") or "").lower()
            size = int(o.get("size", 0) or 0)
            unfilled = int(o.get("unfilled_size", 0) or 0)
            filled = size - unfilled
            if filled < 0:
                filled = size
            return {
                "order_id": str(o.get("id", o.get("order_id", ""))),
                "tag": tag,
                "product_id": o.get("product_id"),
                "symbol": o.get("product_symbol")
                or (o.get("product") or {}).get("symbol"),
                "status": state,
                "side": (o.get("side") or "").lower(),
                "qty": size,
                "remaining_qty": unfilled,
                "filled_size": filled,
                "size": size,
                "unfilled_size": unfilled,
                "average_fill_price": float(
                    o.get("average_fill_price") or o.get("limit_price") or 0
                ),
                "price": float(
                    o.get("limit_price") or o.get("average_fill_price") or 0
                ),
                "reduce_only": o.get("reduce_only"),
            }
        # 2) Try fills (uses fills(); page_size=50) to get fill price/size
        fill_info = self.get_fill_for_client_order_id(client_order_id)
        if fill_info:
            return {
                "order_id": str(fill_info.get("order_id", "")),
                "tag": client_order_id,
                "product_id": fill_info.get("product_id"),
                "symbol": fill_info.get("product_symbol"),
                "status": "filled",
                "side": (fill_info.get("side") or "").lower(),
                "qty": int(fill_info.get("size", 0)),
                "remaining_qty": 0,
                "filled_size": fill_info.get("size", 0),
                "size": fill_info.get("size", 0),
                "unfilled_size": 0,
                "average_fill_price": fill_info.get("price", 0),
                "price": fill_info.get("price", 0),
                "reduce_only": fill_info.get("reduce_only"),
            }
        return None

    def get_fill_for_client_order_id(
        self, client_order_id: str, page_size: int = 50
    ) -> Optional[Dict[str, Any]]:
        """
        Resolve fill price and size from /v2/fills for a given client_order_id (intent_id).
        Used when order is missing from open list so we do not assume filled with price=0.
        Returns dict with price, size, order_id, side, etc., or None if no matching fill.
        """
        if not hasattr(self.api, "get_fills"):
            return None
        try:
            fills = self.api.get_fills(page_size=page_size)
        except Exception as e:
            logger.debug("Delta get_fills failed for client_order_id=%s: %s", client_order_id, e)
            return None
        matching = [
            f
            for f in (fills or [])
            if (f.get("client_order_id") or f.get("order_id") or f.get("tag"))
            == client_order_id
            or str(f.get("client_order_id") or "") == client_order_id
        ]
        if not matching:
            return None
        total_size = sum(float(f.get("size", 0) or 0) for f in matching)
        if total_size <= 0:
            return None
        total_value = sum(
            float(f.get("size", 0) or 0) * float(f.get("price", 0) or 0)
            for f in matching
        )
        avg_price = total_value / total_size if total_size else 0
        product_symbol = matching[0].get("product_symbol") or (
            matching[0].get("product") or {}
        ).get("symbol")
        return {
            "order_id": str(matching[0].get("order_id", matching[0].get("id", ""))),
            "tag": client_order_id,
            "product_id": matching[0].get("product_id"),
            "symbol": product_symbol,
            "product_symbol": product_symbol,
            "side": (matching[0].get("side") or "").lower(),
            "size": total_size,
            "price": avg_price,
            "reduce_only": matching[0].get("reduce_only"),
        }

    def get_fill_by_order_id(
        self, broker_order_id: str, page_size: int = 50
    ) -> Optional[Dict[str, Any]]:
        """
        Resolve fill by broker order_id when fill API does not return client_order_id.
        Returns same shape as get_fill_for_client_order_id (price, size, side, order_id).
        """
        if not broker_order_id or not hasattr(self.api, "get_fills"):
            return None
        try:
            fills = self.api.get_fills(page_size=page_size)
        except Exception as e:
            logger.debug("Delta get_fills failed for order_id=%s: %s", broker_order_id, e)
            return None
        bid_str = str(broker_order_id)
        matching = [
            f
            for f in (fills or [])
            if str(f.get("order_id") or f.get("id") or "") == bid_str
        ]
        if not matching:
            return None
        total_size = sum(float(f.get("size", 0) or 0) for f in matching)
        if total_size <= 0:
            return None
        total_value = sum(
            float(f.get("size", 0) or 0) * float(f.get("price", 0) or 0)
            for f in matching
        )
        avg_price = total_value / total_size if total_size else 0
        return {
            "order_id": bid_str,
            "price": avg_price,
            "size": total_size,
            "side": (matching[0].get("side") or "").lower(),
            "reduce_only": matching[0].get("reduce_only"),
        }

    def get_positions(self):
        return self.api.get_positions()

    def get_recent_fills(self, page_size: int = 50) -> List[Dict[str, Any]]:
        """Return recent fills from /v2/fills for trade-led OMS sync. Positions are updated from these trades."""
        if not hasattr(self.api, "get_fills"):
            return []
        try:
            return self.api.get_fills(page_size=page_size) or []
        except Exception:
            return []

    # used in live engine
    def get_positions_for_recon(self):
        feed = self._realtime_feed
        if feed is not None and hasattr(feed, "get_positions_for_recon"):
            try:
                if feed.is_connected() and feed.ws_positions_ready():
                    ws_positions = feed.get_positions_for_recon()
                    if ws_positions is not None:
                        return ws_positions
            except Exception as e:
                logger.debug(
                    "Delta WS positions unavailable, using REST fallback: %s", e
                )

        positions = self.api.get_positions()
        if not positions:
            return {}
        broker_positions = {}
        for row in positions:
            sym = (
                row.get("tradingSymbol")
                or row.get("trading_symbol")
                or str(row.get("product_id", ""))
            )
            broker_positions[sym] = {
                "qty": int(row.get("netQty", row.get("size", 0))),
                "avg_price": float(row.get("avgPrice", row.get("entry_price", 0))),
                "segment": row.get("segment", "DELTA"),
                "lot_size": int(row.get("lotSize", 1)),
            }
        return broker_positions

    def sync_positions(self):
        if not self.position_manager:
            return
        broker_positions = self.get_positions_for_recon()
        if broker_positions:
            self.position_manager.reconcile_with_broker(broker_positions)

    @staticmethod
    def _bracket_leg_type_for_tag(tag: str) -> Optional[str]:
        tag_u = str(tag or "").upper()
        if tag_u == "MAIN_SL":
            return "stop_loss_order"
        if tag_u == "MAIN_TARGET":
            return "take_profit_order"
        return None

    def _live_orders_for_symbol(self, tradingsymbol: str) -> List[Dict[str, Any]]:
        sym_u = str(tradingsymbol or "").upper()
        orders: List[Dict[str, Any]] = []
        try:
            raw = self.api.get_order_list() or []
        except Exception:
            raw = []
        for o in raw or []:
            if not isinstance(o, dict):
                continue
            o_sym = str(o.get("symbol") or "").upper()
            if o_sym == sym_u:
                orders.append(o)
        return orders

    def has_bracket_leg_on_exchange(self, tradingsymbol: str, tag: str) -> bool:
        """True if Delta already has a resting bracket leg for this symbol/tag."""
        leg_type = self._bracket_leg_type_for_tag(tag)
        if not leg_type:
            return False
        open_states = {
            "open",
            "pending",
            "placed",
            "trigger pending",
            "live",
            "untriggered",
        }
        for o in self._live_orders_for_symbol(tradingsymbol):
            if str(o.get("stop_order_type") or "") != leg_type:
                continue
            if (o.get("status") or "").lower() in open_states:
                return True
        return False

    def find_bracket_leg_order_id(self, tradingsymbol: str, tag: str) -> Optional[str]:
        leg_type = self._bracket_leg_type_for_tag(tag)
        if not leg_type:
            return None
        open_states = {
            "open",
            "pending",
            "placed",
            "trigger pending",
            "live",
            "untriggered",
        }
        for o in self._live_orders_for_symbol(tradingsymbol):
            if str(o.get("stop_order_type") or "") != leg_type:
                continue
            if (o.get("status") or "").lower() in open_states:
                oid = o.get("order_id")
                return str(oid) if oid is not None else None
        return None

    def place_combined_bracket_orders(
        self,
        sl_intent: Any,
        target_intent: Any,
        sl_execution_price: Optional[float] = None,
        target_execution_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Place MAIN_SL + MAIN_TARGET as one Delta bracket (required by exchange API).
        Returns {ok, sl_order_id, tp_order_id, reason, message}.
        """
        self._last_place_order_failure = None
        sl_payload = _intent_to_delta_payload(sl_intent, sl_execution_price)
        tgt_payload = _intent_to_delta_payload(target_intent, target_execution_price)
        stop_retries = 5
        last_err: Optional[str] = None
        for attempt in range(stop_retries):
            try:
                result = self.api.place_bracket_tp_sl(
                    tradingsymbol=sl_payload["tradingsymbol"],
                    quantity=sl_payload["quantity"],
                    transaction_type=sl_payload["transaction_type"],
                    stop_loss_trigger=sl_payload["trigger_price"]
                    or sl_payload["price"],
                    take_profit_trigger=tgt_payload["trigger_price"]
                    or tgt_payload["price"],
                    stop_trigger_method="mark_price",
                    tag=sl_payload.get("tag"),
                )
            except Exception as e:
                last_err = str(e)
                err_txt = last_err.lower()
                if "no_open_position" in err_txt and attempt < (stop_retries - 1):
                    logger.warning(
                        "Delta combined bracket no_open_position for %s "
                        "(attempt %s/%s); retrying in 2s",
                        sl_payload.get("tradingsymbol"),
                        attempt + 1,
                        stop_retries,
                    )
                    time.sleep(2)
                    continue
                if "bracket_order_exists" in err_txt:
                    sl_oid = self.find_bracket_leg_order_id(
                        sl_payload["tradingsymbol"], "MAIN_SL"
                    )
                    tp_oid = self.find_bracket_leg_order_id(
                        sl_payload["tradingsymbol"], "MAIN_TARGET"
                    )
                    if sl_oid or tp_oid:
                        return {
                            "ok": True,
                            "sl_order_id": sl_oid,
                            "tp_order_id": tp_oid,
                            "reason": "bracket_already_exists",
                        }
                self._last_place_order_failure = {
                    "message": last_err,
                    "retryable": "no_open_position" in err_txt,
                }
                return {
                    "ok": False,
                    "sl_order_id": None,
                    "tp_order_id": None,
                    "reason": "broker_error",
                    "message": last_err,
                }

            if result.get("status") == "success":
                return {
                    "ok": True,
                    "sl_order_id": result.get("sl_order_id") or result.get("order_id"),
                    "tp_order_id": result.get("tp_order_id"),
                    "reason": "order_placed",
                }
            last_err = str(result)
            err_txt = last_err.lower()
            if "no_open_position" in err_txt and attempt < (stop_retries - 1):
                time.sleep(2)
                continue
            break

        self._last_place_order_failure = {
            "message": last_err or "combined bracket failed",
            "retryable": False,
        }
        return {
            "ok": False,
            "sl_order_id": None,
            "tp_order_id": None,
            "reason": "no_order_id",
            "message": last_err or "combined bracket failed",
        }

    def get_open_orders(self):
        """
        Returns normalized list of open/pending orders.

        Prefers Delta WebSocket orders snapshot when ready; falls back to REST live orders.
        """
        feed = self._realtime_feed
        if feed is not None and hasattr(feed, "get_open_orders_ws"):
            try:
                if feed.is_connected() and feed.ws_open_orders_ready():
                    ws_orders = feed.get_open_orders_ws()
                    if ws_orders is not None:
                        return self._normalize_open_orders(ws_orders)
            except Exception as e:
                logger.debug(
                    "Delta WS open orders unavailable, using REST fallback: %s", e
                )

        orders = self.api.get_order_list() or []
        return self._normalize_open_orders(orders)

    @staticmethod
    def _normalize_open_orders(orders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        open_states = {
            "open",
            "pending",
            "placed",
            "trigger pending",
            "live",
            "untriggered",
        }
        normalized_orders: List[Dict[str, Any]] = []
        for o in orders or []:
            if not isinstance(o, dict):
                continue
            status = (o.get("status") or "").lower()
            if status not in open_states:
                continue
            product_id = o.get("product_id") or o.get("symbol")
            normalized_orders.append(
                {
                    "order_id": o.get("order_id"),
                    "tag": o.get("tag"),
                    "status": status,
                    "symbol": o.get("symbol"),
                    "product_id": product_id,
                    "side": (o.get("side") or "").lower(),
                    "qty": int(o.get("qty") or 0),
                    "reduce_only": o.get("reduce_only"),
                    "stop_order_type": o.get("stop_order_type"),
                }
            )
        return normalized_orders

    def update_order_price(
        self, product_id: int, order_id: str, new_limit_price: float
    ) -> bool:
        """Update limit price of an open order (e.g. re-quote exit at near bid/ask). Returns True on success."""
        if not hasattr(self.api, "batch_edit"):
            return False
        try:
            orders = [{"id": str(order_id), "limit_price": str(new_limit_price)}]
            self.api.batch_edit(product_id=product_id, orders=orders)
            return True
        except Exception:
            return False
