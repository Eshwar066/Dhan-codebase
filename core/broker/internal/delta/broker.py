"""Delta Exchange broker: order placement via DeltaBrokerApi (delta_rest_client)."""

import time
import uuid
from typing import Any, Optional

from core.broker.base import BaseBroker


def _intent_to_delta_payload(intent, execution_price=None):
    """Build payload for DeltaBrokerApi.place_order from OrderIntent or dict."""
    if hasattr(intent, "instrument"):
        inst = intent.instrument
        trading_symbol = getattr(inst, "trading_symbol", "") or getattr(inst, "custom_symbol", "")
        segment = getattr(inst, "segment", "EQ")
        qty = int(getattr(intent, "qty", getattr(inst, "lot_size", 1)))
        lot_size = int(getattr(inst, "lot_size", 1))
        total_qty = qty * lot_size
        price = execution_price if execution_price is not None else (intent.price or 0)
        return {
            "tradingsymbol": trading_symbol,
            "exchange": segment,
            "quantity": total_qty,
            "price": float(price),
            "trigger_price": 0,
            "order_type": getattr(intent, "order_type", "MARKET"),
            "transaction_type": intent.side,
            "trade_type": getattr(intent, "trade_type", "MARGIN"),
            "tag": intent.intent_id,
            "reduce_only": "true" if getattr(intent, "action", "") == "EXIT" else "false",
        }
    # Dict intent
    total_qty = int(intent.get("qty", 1)) * int(intent.get("lot_size", 1))
    price = execution_price if execution_price is not None else float(intent.get("price", 0) or 0)
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
        "reduce_only": intent.get("reduce_only", "false"),
    }


class DeltaBroker(BaseBroker):
    """Order placement via Delta Exchange. Uses DeltaBrokerApi (DeltaSource / delta_rest_client)."""

    def __init__(self, api, position_manager=None, intent_store=None):
        super().__init__(position_manager=position_manager, intent_store=intent_store)
        self.api = api

    def place_order(
        self,
        intent: Any,
        execution_price: Optional[float] = None,
        retries: int = 0,
    ) -> Optional[str]:
        payload = _intent_to_delta_payload(intent, execution_price)
        for attempt in range(retries + 1):
            try:
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
                return None
            except Exception as e:
                if attempt == retries:
                    raise
                time.sleep(0.3)
        return None

    def exit_position(self, trading_symbol: str, qty: int, side: str, segment: str = "EQ", lot_size: int = 1) -> Optional[str]:
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
        for o in self.api.get_order_list() or []:
            if o.get("tag") == client_order_id:
                return o
        return None

    def get_positions(self):
        return self.api.get_positions()

    def sync_positions(self):
        if not self.position_manager:
            return
        positions = self.api.get_positions()
        if not positions:
            return
        broker_positions = {}
        for row in positions:
            sym = row.get("tradingSymbol") or row.get("trading_symbol") or str(row.get("product_id", ""))
            broker_positions[sym] = {
                "qty": int(row.get("netQty", row.get("size", 0))),
                "avg_price": float(row.get("avgPrice", row.get("entry_price", 0))),
                "segment": row.get("segment", "DELTA"),
                "lot_size": int(row.get("lotSize", 1)),
            }
        self.position_manager.reconcile_with_broker(broker_positions)
