"""Delta Exchange broker API (stub)."""

from typing import Any, Dict, List, Optional


class DeltaBrokerApi:
    """IBrokerApi stub for Delta Exchange. Replace with real client when integrating."""

    def __init__(self, api_key: str = "", api_secret: str = "", testnet: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet

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
        return {"status": "error", "message": "Delta Exchange not implemented"}

    def get_positions(self, debug: str = "NO") -> Any:
        return []

    def get_order_list(self) -> List[Dict[str, Any]]:
        return []
