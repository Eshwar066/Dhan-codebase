"""
Abstract broker interface.
Backtest / paper / live all use the same contract; live uses Dhan, paper simulates.
"""

from abc import ABC, abstractmethod
from typing import Dict, Tuple, Optional


class BaseBroker(ABC):
    """Placeholder for order/position/balance. Extend for paper and live."""

    @abstractmethod
    def place_order(
        self,
        tradingsymbol: str,
        exchange: str,
        quantity: int,
        price: float,
        trigger_price: float,
        order_type: str,
        transaction_type: str,
        trade_type: str,
    ) -> Optional[str]:
        """Return order_id or None."""
        pass

    @abstractmethod
    def get_balance(self) -> float:
        pass

    @abstractmethod
    def get_positions(self):
        """Return positions (list/dict/DataFrame)."""
        pass

    def get_order_report(self) -> Tuple[Dict, Dict]:
        """Return (order_details, order_exe_price)."""
        return {}, {}
