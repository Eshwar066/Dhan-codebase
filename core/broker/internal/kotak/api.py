"""Kotak Neo broker API: IBrokerApi over KotakSource."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.broker.internal.kotak import mappings as kotak_map


class KotakBrokerApi:
    """IBrokerApi implementation for Kotak Neo."""

    def __init__(self, kotak_source):
        self._source = kotak_source

    def place_order(
        self,
        tradingsymbol: str,
        exchange: str,
        quantity: int,
        price: float = 0,
        trigger_price: float = 0,
        order_type: str = "MARKET",
        transaction_type: str = "BUY",
        trade_type: str = "MARGIN",
        disclosed_quantity: int = 0,
        after_market_order: bool = False,
        validity: str = "DAY",
        amo_time: str = "OPEN",
        bo_profit_value: Optional[float] = None,
        bo_stop_loss_value: Optional[float] = None,
        tag: Optional[str] = None,
        scrip_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        ot = kotak_map.normalize_order_type(order_type)
        px = float(price or 0)
        if ot == "MKT":
            px = 0.0
        return self._source.place_order(
            exchange_segment=kotak_map.internal_segment_to_neo(exchange),
            product=kotak_map.normalize_product(trade_type, exchange),
            price=str(px if px > 0 else "0"),
            order_type=ot,
            quantity=str(int(quantity)),
            validity=validity or "DAY",
            trading_symbol=tradingsymbol,
            transaction_type=kotak_map.normalize_transaction(transaction_type),
            amo="YES" if after_market_order else "NO",
            disclosed_quantity=str(int(disclosed_quantity or 0)),
            trigger_price=str(float(trigger_price or 0)),
            tag=tag,
            scrip_token=str(scrip_token) if scrip_token is not None else None,
        )

    def modify_order(
        self,
        order_id: str,
        price: float = 0,
        trigger_price: float = 0,
        quantity: Optional[int] = None,
        order_type: str = "LIMIT",
        validity: str = "DAY",
        **kwargs,
    ) -> Dict[str, Any]:
        payload = {
            "order_id": str(order_id),
            "price": str(float(price or 0)),
            "trigger_price": str(float(trigger_price or 0)),
            "order_type": kotak_map.normalize_order_type(order_type),
            "validity": validity or "DAY",
        }
        if quantity is not None:
            payload["quantity"] = str(int(quantity))
        payload.update({k: v for k, v in kwargs.items() if v is not None})
        return self._source.modify_order(**payload)

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        return self._source.cancel_order(order_id)

    def get_positions(self, debug: str = "NO") -> Any:
        return self._source.get_positions(debug=debug)

    def get_order_list(self) -> List[Dict[str, Any]]:
        return self._source.get_order_list()

    def get_order_by_id(self, order_id: str) -> Optional[Dict[str, Any]]:
        return self._source.get_order_by_id(order_id)
