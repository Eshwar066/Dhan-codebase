"""Kotak Neo broker: order placement via KotakBrokerApi (no Forever/GTT in v1)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Union

from core.broker.base import BaseBroker
from core.broker.internal.kotak import mappings as kotak_map

logger = logging.getLogger(__name__)


class KotakBroker(BaseBroker):
    """Order placement via Kotak Neo. Uses KotakBrokerApi."""

    supports_hedge_fill_gated_bundles = False

    def __init__(self, api, position_manager=None, intent_store=None):
        super().__init__(position_manager=position_manager, intent_store=intent_store)
        self.api = api
        self._last_place_order_failure: Optional[Dict[str, Any]] = None

    def place_order(
        self,
        intent: Union[Dict, Any],
        execution_price: Optional[float] = None,
        retries: int = 0,
    ) -> Optional[str]:
        self._last_place_order_failure = None
        payload = kotak_map.intent_to_neo_payload(intent, execution_price)
        attempts = max(0, int(retries)) + 1
        for attempt in range(attempts):
            try:
                result = self.api.place_order(
                    tradingsymbol=payload["trading_symbol"],
                    exchange=payload["exchange_segment"],
                    quantity=int(payload["quantity"]),
                    price=float(payload["price"] or 0),
                    trigger_price=float(payload["trigger_price"] or 0),
                    order_type=payload["order_type"],
                    transaction_type=payload["transaction_type"],
                    trade_type=payload["product"],
                    disclosed_quantity=int(payload.get("disclosed_quantity") or 0),
                    after_market_order=str(payload.get("amo") or "NO").upper() == "YES",
                    validity=payload.get("validity") or "DAY",
                    tag=payload.get("tag"),
                    scrip_token=payload.get("scrip_token"),
                )
            except Exception as e:
                self._last_place_order_failure = {
                    "message": str(e),
                    "retryable": attempt + 1 < attempts,
                }
                logger.exception("Kotak place_order failed attempt=%s: %s", attempt + 1, e)
                continue
            if isinstance(result, dict) and result.get("status") == "success":
                oid = result.get("order_id")
                if oid:
                    return f"KOTAK_REST:{oid}"
            msg = (
                result.get("message")
                if isinstance(result, dict)
                else kotak_map.response_message(result)
            )
            self._last_place_order_failure = {
                "message": msg,
                "retryable": False,
                "raw": result,
            }
            logger.error(
                "Kotak place_order rejected %s: %s",
                payload.get("trading_symbol"),
                msg,
            )
            return None
        return None

    def exit_position(
        self,
        trading_symbol: str,
        qty: int,
        side: str,
        segment: str = "EQ",
        lot_size: int = 1,
        order_type: str = "MARKET",
        price: float = 0,
        trigger_price: float = 0,
        trade_type: str = "MARGIN",
        tag: Optional[str] = None,
    ) -> Optional[str]:
        exit_side = "SELL" if str(side).upper() in {"B", "BUY"} else "BUY"
        intent = {
            "trading_symbol": trading_symbol,
            "segment": segment,
            "qty": int(qty),
            "lot_size": int(lot_size or 1),
            "side": exit_side,
            "order_type": order_type,
            "price": price,
            "trigger_price": trigger_price,
            "trade_type": trade_type,
            "intent_id": tag,
        }
        return self.place_order(intent)

    def cancel_order(self, order_id: str) -> bool:
        oid = str(order_id or "")
        if oid.startswith("KOTAK_REST:"):
            oid = oid.split(":", 1)[1]
        elif oid.startswith("KOTAK_WS:"):
            oid = oid.split(":", 1)[1]
        try:
            result = self.api.cancel_order(oid)
            return isinstance(result, dict) and result.get("status") == "success"
        except Exception as e:
            logger.warning("Kotak cancel_order failed %s: %s", oid, e)
            return False

    def modify_order_price(
        self,
        order_id: str,
        price: float,
        trigger_price: float = 0,
        quantity: Optional[int] = None,
        order_type: str = "LIMIT",
    ) -> bool:
        oid = str(order_id or "")
        if oid.startswith("KOTAK_REST:") or oid.startswith("KOTAK_WS:"):
            oid = oid.split(":", 1)[1]
        try:
            result = self.api.modify_order(
                order_id=oid,
                price=price,
                trigger_price=trigger_price,
                quantity=quantity,
                order_type=order_type,
            )
            return isinstance(result, dict) and result.get("status") == "success"
        except Exception as e:
            logger.warning("Kotak modify_order failed %s: %s", oid, e)
            return False

    def get_positions(self, debug: str = "NO") -> Any:
        return self.api.get_positions(debug=debug)

    def get_order_list(self):
        return self.api.get_order_list()
