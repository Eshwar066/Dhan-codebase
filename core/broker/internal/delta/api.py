"""Delta Exchange broker API: order placement and position/order lookup via delta_rest_client."""

from typing import Any, Dict, List, Optional

from core.data.sources.delta_source import DeltaSource


class DeltaBrokerApi:
    """IBrokerApi implementation for Delta Exchange. Uses DeltaSource (wraps DeltaRestClient)."""

    def __init__(self, delta_source: DeltaSource):
        self._source = delta_source

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
        reduce_only: str = "false",
    ) -> Dict[str, Any]:
        product_id = self._source.product_id_for_symbol(tradingsymbol)
        if product_id is None:
            return {"status": "error", "order_id": None, "message": f"Unknown symbol: {tradingsymbol}"}
        side = (transaction_type or "BUY").lower()
        limit_price = float(price) if price and (order_type or "MARKET").upper() == "LIMIT" else None
        return self._source.place_order(
            product_id=int(product_id),
            size=int(quantity),
            side="buy" if side == "buy" else "sell",
            limit_price=limit_price,
            order_type=order_type or "MARKET",
            client_order_id=tag,
            reduce_only=reduce_only,
        )

    def get_positions(self, debug: str = "NO") -> Any:
        return self._source.get_positions(debug=debug)

    def get_order_list(self) -> List[Dict[str, Any]]:
        return self._source.get_order_list()

    def product_id_for_symbol(self, symbol: str) -> Optional[int]:
        """Resolve symbol to Delta product_id (e.g. BTCUSD -> id)."""
        return self._source.product_id_for_symbol(symbol)

    def batch_edit(self, product_id: int, orders: List[Dict[str, Any]]) -> Any:
        """Edit orders in batch (e.g. update limit_price). Each order: { 'id': order_id, 'limit_price': str }."""
        return self._source.batch_edit(product_id=product_id, orders=orders)
