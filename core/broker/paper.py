"""
Paper broker: uses Dhan for data, simulates orders (no real execution).
"""

import logging
from typing import Dict, Optional, Tuple

from core.broker.base import BaseBroker
from core.api.dhan_data import DhanDataProvider


class PaperBroker(BaseBroker):
    """Paper trading: Dhan data + simulated order book."""

    def __init__(self, client_code: str, access_token: str, deps_dir: str = "Dependencies"):
        self._data = DhanDataProvider(client_code, access_token, deps_dir)
        self._orders: Dict[str, dict] = {}
        self._positions: Dict[str, dict] = {}
        self._balance = 0.0
        self._order_id = 0
        self._log = logging.getLogger("PaperBroker")

    @property
    def data(self) -> DhanDataProvider:
        return self._data

    def _next_order_id(self) -> str:
        self._order_id += 1
        return f"PAPER_{self._order_id}"

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
        oid = self._next_order_id()
        self._orders[oid] = {
            "tradingsymbol": tradingsymbol,
            "exchange": exchange,
            "quantity": quantity,
            "price": price,
            "transaction_type": transaction_type,
            "status": "COMPLETE",
        }
        key = f"{tradingsymbol}_{exchange}"
        q = quantity if transaction_type.upper() == "BUY" else -quantity
        prev = self._positions.get(key, {"qty": 0})
        self._positions[key] = {"qty": prev.get("qty", 0) + q}
        self._log.info("PAPER order %s: %s %s %s @ %s", oid, transaction_type, quantity, tradingsymbol, price or "MKT")
        return oid

    def get_balance(self) -> float:
        return self._balance

    def get_positions(self):
        return self._positions

    def get_order_report(self) -> Tuple[Dict, Dict]:
        details = {k: v.get("status", "") for k, v in self._orders.items()}
        prices = {k: v.get("price", 0) for k, v in self._orders.items()}
        return details, prices
