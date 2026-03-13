"""Delta Exchange broker API: order placement and position/order lookup via delta_rest_client."""

from typing import Any, Dict, List, Optional

from core.data.sources.delta_source import DeltaSource


def _ensure_list_str(symbols: Any) -> List[str]:
    if symbols is None:
        return []
    if isinstance(symbols, str):
        return [symbols]
    return list(symbols)


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
            return {
                "status": "error",
                "order_id": None,
                "message": f"Unknown symbol: {tradingsymbol}",
            }
        side = (transaction_type or "BUY").lower()
        limit_price = (
            float(price)
            if price and (order_type or "MARKET").upper() == "LIMIT"
            else None
        )
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

    def get_orders_history(
        self, page_size: int = 50
    ) -> List[Dict[str, Any]]:
        """Order history via order_history (v2/orders/history) for resolving fill status when not in live list."""
        return self._source.get_orders_history(page_size=page_size)

    def get_fills(self, page_size: int = 50) -> List[Dict[str, Any]]:
        """Fills via fills() (v2/fills) for order fill status."""
        return self._source.get_fills(page_size=page_size)

    def product_id_for_symbol(self, symbol: str) -> Optional[int]:
        """Resolve symbol to Delta product_id (e.g. BTCUSD -> id)."""
        return self._source.product_id_for_symbol(symbol)

    def batch_edit(self, product_id: int, orders: List[Dict[str, Any]]) -> Any:
        """Edit orders in batch (e.g. update limit_price). Each order: { 'id': order_id, 'limit_price': str }."""
        return self._source.batch_edit(product_id=product_id, orders=orders)

    def set_leverage(self, product_id: int, leverage: int) -> Any:
        """Set leverage for a Delta product (by product_id)."""
        return self._source.set_leverage(product_id=product_id, leverage=leverage)

    def set_leverage_for_symbols(self, symbols: List[str], leverage: int) -> Dict[str, Any]:
        """
        Set leverage for each symbol in the list. Resolves symbol -> product_id and calls set_leverage.
        Returns a dict of symbol -> result (or error message) for each.
        """
        symbols = _ensure_list_str(symbols)
        results: Dict[str, Any] = {}
        for symbol in symbols:
            pid = self._source.product_id_for_symbol(symbol)
            if pid is None:
                results[symbol] = {"ok": False, "message": f"Unknown symbol: {symbol}"}
                continue
            try:
                out = self._source.set_leverage(product_id=int(pid), leverage=leverage)
                results[symbol] = {"ok": True, "product_id": pid, "response": out}
            except Exception as e:
                results[symbol] = {"ok": False, "message": str(e)}
        return results
