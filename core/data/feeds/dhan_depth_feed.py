"""
Dhan Full Market Depth WebSocket feed.

- 20 level: up to 50 instruments per connection (NSE_EQ, NSE_FNO).
- 200 level: 1 instrument per connection.
- Exposes get_market_depth(symbol) for demand/supply zones and strategies beyond 5-level depth.
"""

from typing import Any, Dict, List, Optional

from core.data.feeds.base_feed import RealtimeFeed
from core.library.dhan_depth_websocket import DhanDepthWebSocket


class DhanDepthFeed(RealtimeFeed):
    """
    Real-time Full Market Depth feed for Dhan (20 or 200 level).
    Use get_market_depth(symbol) for bids/asks; get_last_ticker derives from best bid/ask.
    """

    def __init__(
        self,
        access_token: str,
        client_id: str,
        instruments: List[Dict[str, str]],
        level: int = 20,
    ):
        """
        instruments: list of {"ExchangeSegment": "NSE_EQ", "SecurityId": "11536", "symbol": "RELIANCE"}.
        Use instrument_store.get_feed_instruments(symbols) (NSE_EQ / NSE_FNO only for depth).
        level: 20 (up to 50 instruments) or 200 (1 instrument per connection).
        """
        self.access_token = access_token
        self.client_id = client_id
        self.instruments = list(instruments)
        self.level = level
        self._ws: Optional[DhanDepthWebSocket] = None

    def start(self) -> None:
        if self._ws:
            return
        if not self.instruments:
            return
        self._ws = DhanDepthWebSocket(
            access_token=self.access_token,
            client_id=self.client_id,
            instruments=self.instruments,
            level=self.level,
        )
        self._ws.connect()

    def stop(self) -> None:
        if self._ws:
            self._ws.disconnect()
            self._ws = None

    def is_connected(self) -> bool:
        return self._ws is not None and self._ws.is_connected()

    def replace_instruments(self, instruments: List[Dict[str, str]]) -> None:
        self.instruments = list(instruments)
        if self._ws:
            self._ws.replace_instruments(self.instruments)

    @property
    def connect_generation(self) -> int:
        return int(self._ws.connect_generation) if self._ws else 0

    @property
    def subscribe_generation(self) -> int:
        return int(self._ws.subscribe_generation) if self._ws else 0

    @property
    def is_warm(self) -> bool:
        return bool(self._ws and self._ws.is_warm)

    def get_market_depth(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Return latest market depth for symbol: {symbol, bids: [{price, quantity, num_orders}, ...], asks: [...]}.
        Bids/asks are sorted by price (bids desc, asks asc) from the exchange.
        """
        if not self._ws:
            return None
        return self._ws.get_depth(symbol.upper())

    def get_last_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Derive LTP from best bid/ask mid or last available level."""
        depth = self.get_market_depth(symbol)
        if not depth:
            return None
        bids = depth.get("bids") or []
        asks = depth.get("asks") or []
        if bids and asks:
            mid = (bids[0]["price"] + asks[0]["price"]) / 2.0
        elif bids:
            mid = bids[0]["price"]
        elif asks:
            mid = asks[0]["price"]
        else:
            return None
        return {
            "symbol": depth.get("symbol", symbol),
            "close": mid,
            "mark_price": mid,
        }

    def get_last_candle(self, symbol: str, resolution: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Depth feed does not provide OHLC; return None or best-effort from depth."""
        ticker = self.get_last_ticker(symbol)
        if not ticker:
            return None
        return {
            "symbol": ticker.get("symbol", symbol),
            "open": ticker.get("close"),
            "high": ticker.get("close"),
            "low": ticker.get("close"),
            "close": ticker.get("close"),
            "volume": 0,
            "timestamp": None,
        }

    def get_orders(self, symbol: str) -> List[Dict[str, Any]]:
        return []

    def get_positions(self) -> Dict[str, Dict[str, Any]]:
        return {}
