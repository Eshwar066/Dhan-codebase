"""
Broker API: exchange-facing interface for order placement and position/order lookup.

All order-related calls (place_order, get_positions, get_order_list) go through
an IBrokerApi implementation. Engines and OrderRouter use brokers that wrap
these APIs — they never call the data layer for orders.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class IBrokerApi(ABC):
    """
    Contract for order placement and position/order lookup.
    Implementations: DhanBrokerApi, DeltaBrokerApi (and future exchanges).
    """

    @abstractmethod
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
    ) -> Dict[str, Any]:
        """
        Place a single order on the exchange.
        Returns dict with at least "status" and on success "order_id".
        """
        raise NotImplementedError

    @abstractmethod
    def get_positions(self, debug: str = "NO") -> Any:
        """Current positions (broker-specific format, e.g. DataFrame or list)."""
        raise NotImplementedError

    def get_order_list(self) -> List[Dict[str, Any]]:
        """List of orders (for idempotency / status lookup). Default: empty list."""
        return []
