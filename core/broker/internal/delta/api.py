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

    def place_bracket_stop_loss(
        self,
        tradingsymbol: str,
        quantity: int,
        transaction_type: str = "BUY",
        trigger_price: float = 0,
        price: Optional[float] = None,
        stop_trigger_method: str = "mark_price",
        tag: Optional[str] = None,
    ) -> Dict[str, Any]:
        product_id = self._source.product_id_for_symbol(tradingsymbol)
        if product_id is None:
            return {
                "status": "error",
                "order_id": None,
                "message": f"Unknown symbol: {tradingsymbol}",
            }
        side = (transaction_type or "BUY").lower()
        raw = self._source.place_bracket_stop_loss(
            product_id=int(product_id),
            size=int(quantity),
            side="buy" if side == "buy" else "sell",
            stop_price=float(trigger_price),
            limit_price=float(price) if price is not None else None,
            stop_trigger_method=stop_trigger_method,
            client_order_id=tag,
        )
        return self._normalize_bracket_response(raw)

    def place_bracket_tp_sl(
        self,
        tradingsymbol: str,
        quantity: int,
        transaction_type: str = "BUY",
        stop_loss_trigger: float = 0,
        take_profit_trigger: float = 0,
        stop_loss_limit: Optional[float] = None,
        take_profit_limit: Optional[float] = None,
        stop_trigger_method: str = "mark_price",
        tag: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Single Delta bracket with both stop-loss and take-profit legs."""
        product_id = self._source.product_id_for_symbol(tradingsymbol)
        if product_id is None:
            return {
                "status": "error",
                "order_id": None,
                "message": f"Unknown symbol: {tradingsymbol}",
            }
        side = (transaction_type or "BUY").lower()
        raw = self._source.place_bracket_tp_sl(
            product_id=int(product_id),
            size=int(quantity),
            side="buy" if side == "buy" else "sell",
            stop_loss_price=float(stop_loss_trigger),
            take_profit_price=float(take_profit_trigger),
            stop_loss_limit_price=stop_loss_limit,
            take_profit_limit_price=take_profit_limit,
            stop_trigger_method=stop_trigger_method,
            client_order_id=tag,
        )
        return self._normalize_bracket_response(raw, combined=True)

    @staticmethod
    def _normalize_bracket_response(
        raw: Any, *, combined: bool = False
    ) -> Dict[str, Any]:
        sl = (raw or {}).get("stop_loss_order") or {}
        tp = (raw or {}).get("take_profit_order") or {}
        sl_oid = sl.get("id") or sl.get("order_id")
        tp_oid = tp.get("id") or tp.get("order_id")
        oid = sl_oid or (raw or {}).get("id") or (raw or {}).get("order_id")
        out: Dict[str, Any] = {
            "status": "success" if oid is not None else "error",
            "order_id": str(oid) if oid is not None else None,
            "raw": raw,
        }
        if combined:
            out["sl_order_id"] = str(sl_oid) if sl_oid is not None else None
            out["tp_order_id"] = str(tp_oid) if tp_oid is not None else None
        return out

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
