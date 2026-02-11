"""
Broker base: abstract contract for order placement and exchange API.
All broker implementations live under core/broker/internal/.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union


class IBrokerApi(ABC):
    """
    Contract for order placement and position/order lookup at the exchange.
    Implementations: DhanBrokerApi, DeltaBrokerApi (in internal/).
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
        """Place a single order. Returns dict with "status" and on success "order_id"."""
        raise NotImplementedError

    @abstractmethod
    def get_positions(self, debug: str = "NO") -> Any:
        """Current positions (broker-specific format)."""
        raise NotImplementedError

    def get_order_list(self) -> List[Dict[str, Any]]:
        """List of orders for idempotency / status lookup."""
        return []


class BaseBroker(ABC):
    """
    Abstract broker contract for order placement and position/exit.
    Engines and OrderRouter use brokers; they do not call the data layer for orders.
    """

    def __init__(self, position_manager=None, intent_store=None):
        self.position_manager = position_manager
        self.intent_store = intent_store

    @abstractmethod
    def place_order(
        self,
        intent: Union[Dict, Any],
        execution_price: Optional[float] = None,
        retries: int = 0,
    ) -> Optional[str]:
        """Place order from OrderIntent or dict. Returns order_id or None."""
        raise NotImplementedError

    @abstractmethod
    def exit_position(
        self,
        trading_symbol: str,
        qty: int,
        side: str,
        segment: str = "EQ",
        lot_size: int = 1,
    ) -> Optional[str]:
        """Exit a position explicitly. Must internally call place_order()."""
        raise NotImplementedError

    def sync_positions(self):
        """Optional. LIVE brokers may override to reconcile broker truth."""
        return None

    def find_order_by_client_id(self, client_order_id: str):
        """Optional idempotency hook. LIVE brokers may override."""
        return None
