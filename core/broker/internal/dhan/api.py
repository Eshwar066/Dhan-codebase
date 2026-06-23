"""Dhan broker API: order placement and position/order lookup via Dhan."""

from typing import Any, Dict, List, Optional


class DhanBrokerApi:
    """IBrokerApi implementation for Dhan. Order placement + positions + order list."""

    def __init__(self, dhan_source):
        self._source = dhan_source

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
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._source.place_order(
            tradingsymbol=tradingsymbol,
            exchange=exchange,
            quantity=quantity,
            price=int(price),
            trigger_price=int(trigger_price),
            order_type=order_type,
            transaction_type=transaction_type,
            trade_type=trade_type,
            disclosed_quantity=disclosed_quantity,
            after_market_order=after_market_order,
            validity=validity,
            amo_time=amo_time,
            bo_profit_value=bo_profit_value,
            bo_stop_loss_value=bo_stop_loss_value,
            tag=tag,
            correlation_id=correlation_id,
        )

    def place_forever_order(
        self,
        tradingsymbol: str,
        exchange: str,
        quantity: int,
        price: float = 0,
        trigger_price: float = 0,
        order_type: str = "LIMIT",
        transaction_type: str = "BUY",
        trade_type: str = "MARGIN",
        order_flag: str = "SINGLE",
        disclosed_quantity: int = 0,
        validity: str = "DAY",
        tag: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._source.place_forever_order(
            tradingsymbol=tradingsymbol,
            exchange=exchange,
            quantity=quantity,
            price=float(price),
            trigger_price=float(trigger_price),
            order_type=order_type,
            transaction_type=transaction_type,
            trade_type=trade_type,
            order_flag=order_flag,
            disclosed_quantity=disclosed_quantity,
            validity=validity,
            tag=tag,
            correlation_id=correlation_id,
        )

    def cancel_forever_order(self, order_id: str) -> Any:
        return getattr(self._source, "cancel_forever_order", lambda _oid: None)(order_id)

    def get_forever_orders(self) -> List[Dict[str, Any]]:
        return getattr(self._source, "get_forever_orders", lambda: [])()

    def get_positions(self, debug: str = "NO") -> Any:
        return self._source.get_positions(debug=debug)

    def get_order_list(self) -> List[Dict[str, Any]]:
        return getattr(self._source, "get_order_list", lambda: [])()

    def get_fills(self, page_size: int = 50) -> List[Dict[str, Any]]:
        """Fills from order list (filled/TRADED orders) for trade-led OMS."""
        return getattr(self._source, "get_fills", lambda page_size=50: [])(page_size=page_size)
