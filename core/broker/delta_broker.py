"""
Delta Exchange broker: order placement and position/exit via DeltaBrokerApi.
Same BaseBroker contract as DhanBroker; feeds engines and order management when
Delta is selected as the broker.
"""

from typing import Any, Optional

from core.broker.base_broker import BaseBroker


class DeltaBroker(BaseBroker):
    """Order placement via Delta Exchange. Uses DeltaBrokerApi (stub until API wired)."""

    def __init__(self, api, position_manager=None, intent_store=None):
        """
        Args:
            api: DeltaBrokerApi instance (or future real Delta client).
        """
        super().__init__(position_manager=position_manager, intent_store=intent_store)
        self.api = api

    def place_order(
        self,
        intent: Any,
        execution_price: Optional[float] = None,
        retries: int = 0,
    ) -> Optional[str]:
        """Place order on Delta Exchange. Currently stub returns None."""
        # TODO: convert OrderIntent to Delta payload and call self.api.place_order(...)
        result = self.api.place_order(
            tradingsymbol=getattr(intent.instrument, "trading_symbol", ""),
            exchange=getattr(intent.instrument, "exchange", "NSE"),
            quantity=getattr(intent, "qty", 1),
            price=execution_price or getattr(intent, "price", 0),
            trigger_price=0,
            order_type=getattr(intent, "order_type", "MARKET"),
            transaction_type=getattr(intent, "side", "BUY"),
            trade_type=getattr(intent, "trade_type", "MARGIN"),
            tag=getattr(intent, "intent_id", None),
        )
        if result.get("status") == "success":
            return result.get("order_id")
        return None

    def exit_position(self, trading_symbol, qty, side, segment="EQ", lot_size=1):
        """Exit a position. Stub until Delta API supports it."""
        # TODO: build exit order and call place_order
        return None
