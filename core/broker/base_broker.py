from abc import ABC, abstractmethod
from typing import Optional, Dict


class BaseBroker(ABC):
    """
    Abstract broker contract.
    All brokers (LIVE / SIMULATED / PAPER) must implement this.
    """

    def __init__(self, position_manager=None, intent_store=None):
        self.position_manager = position_manager
        self.intent_store = intent_store

    # =========================
    # ORDER PLACEMENT
    # =========================
    @abstractmethod
    def place_order(self, intent: Dict, retries: int = 0) -> Optional[str]:
        """
        Place an order using intent.

        Args:
            intent (dict): normalized trading intent
            retries (int): retry count (LIVE brokers only)

        Returns:
            order_id (str) or None
        """
        raise NotImplementedError

    # =========================
    # EXIT POSITION
    # =========================
    @abstractmethod
    def exit_position(
        self,
        trading_symbol: str,
        qty: int,
        side: str,
        segment: str = "EQ",
        lot_size: int = 1,
    ) -> Optional[str]:
        """
        Exit a position explicitly.
        Must internally call place_order().
        """
        raise NotImplementedError

    # =========================
    # POSITION SYNC (LIVE ONLY)
    # =========================
    def sync_positions(self):
        """
        Optional.
        LIVE brokers may override this to reconcile broker truth.
        """
        return None

    # =========================
    # ORDER LOOKUP (OPTIONAL)
    # =========================
    def find_order_by_client_id(self, client_order_id: str):
        """
        Optional idempotency hook.
        LIVE brokers may override.
        """
        return None
