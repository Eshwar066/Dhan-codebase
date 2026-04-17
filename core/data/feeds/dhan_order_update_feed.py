"""
Dhan private order-update WebSocket feed (incremental fills → synthetic trades).

Pairs with DhanWebSocketFeed (market data). Uses core.library.dhan_order_update_ws.
"""

import logging
from typing import Any, Callable, Dict, Optional

from core.library.dhan_order_update_ws import DhanOrderUpdateClient

logger = logging.getLogger(__name__)


class DhanOrderUpdateFeed:
    """
    Thin wrapper around DhanOrderUpdateClient for LiveEngine wiring.
    """

    def __init__(self, access_token: str, client_id: str):
        self.access_token = access_token
        self.client_id = client_id
        self._client: Optional[DhanOrderUpdateClient] = None
        self._callback: Optional[Callable[[Dict[str, Any]], None]] = None

    def set_synthetic_trade_callback(
        self, callback: Callable[[Dict[str, Any]], None]
    ) -> None:
        """Incremental fill payloads (see dhan_order_update_ws)."""
        self._callback = callback

    def _forward(self, payload: Dict[str, Any]) -> None:
        cb = self._callback
        if not cb:
            return
        try:
            cb(payload)
        except Exception as e:
            logger.debug("DhanOrderUpdateFeed callback error: %s", e)

    def start(self) -> None:
        if self._client:
            return
        self._client = DhanOrderUpdateClient(
            access_token=self.access_token,
            client_id=self.client_id,
            on_synthetic_trade=self._forward,
        )
        self._client.connect()

    def stop(self) -> None:
        if self._client:
            self._client.disconnect()
            self._client = None

    def is_connected(self) -> bool:
        return bool(self._client and self._client.is_connected())

    @property
    def connect_generation(self) -> int:
        return int(self._client.connect_generation) if self._client else 0

    @property
    def is_warm(self) -> bool:
        return bool(self._client and self._client.is_warm)
