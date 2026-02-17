"""
Dhan Live Market Feed WebSocket implementing RealtimeFeed (cursor.md).

- Connects to wss://api-feed.dhan.co (version=2, token, clientId, authType=2).
- Subscribes to instruments (ExchangeSegment + SecurityId); max 100 per message, 5000 per connection.
- Receives binary packets (Ticker, Quote, Full, OI, Prev close); exposes get_last_ticker(symbol), get_last_candle(symbol).
- Used by LiveEngine when broker is DHAN and credentials are set.
"""

from typing import Any, Dict, List, Optional

from core.data.feeds.base_feed import RealtimeFeed
from core.library.dhan_websocket import DhanWebSocket


class DhanWebSocketFeed(RealtimeFeed):
    """
    Real-time feed using Dhan Live Market Feed WebSocket.
    Subscribes to ticker/quote data for given instruments; get_last_ticker(symbol), get_last_candle(symbol).
    """

    def __init__(
        self,
        access_token: str,
        client_id: str,
        instruments: List[Dict[str, str]],
    ):
        """
        instruments: list of {"ExchangeSegment": "NSE_EQ", "SecurityId": "11536", "symbol": "RELIANCE"}.
        Use instrument_store.get_feed_instruments(symbols) to resolve symbols.
        """
        self.access_token = access_token
        self.client_id = client_id
        self.instruments = list(instruments)
        self._ws: Optional[DhanWebSocket] = None

    def start(self) -> None:
        if self._ws:
            return
        if not self.instruments:
            return
        self._ws = DhanWebSocket(
            access_token=self.access_token,
            client_id=self.client_id,
            instruments=self.instruments,
        )
        self._ws.connect()

    def stop(self) -> None:
        if self._ws:
            self._ws.disconnect()
            self._ws = None

    def is_connected(self) -> bool:
        return self._ws is not None and self._ws.is_connected()

    def get_last_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        if not self._ws:
            return None
        raw = self._ws.get_last_ticker(symbol.upper())
        if not raw:
            return None
        price = raw.get("last_price")
        if price is None:
            return None
        return {
            "symbol": raw.get("symbol", symbol),
            "close": float(price),
            "mark_price": float(price),
            "open": raw.get("open"),
            "high": raw.get("high"),
            "low": raw.get("low"),
            "volume": raw.get("volume"),
            "timestamp": raw.get("last_trade_time"),
        }

    def get_last_candle(self, symbol: str, resolution: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if not self._ws:
            return None
        quote = self._ws.get_last_quote(symbol.upper())
        if quote:
            return {
                "symbol": quote.get("symbol", symbol),
                "open": quote.get("open"),
                "high": quote.get("high"),
                "low": quote.get("low"),
                "close": quote.get("last_price") or quote.get("close"),
                "volume": quote.get("volume", 0),
                "timestamp": quote.get("last_trade_time"),
            }
        ticker = self._ws.get_last_ticker(symbol.upper())
        if ticker:
            price = ticker.get("last_price")
            if price is not None:
                return {
                    "symbol": ticker.get("symbol", symbol),
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": 0,
                    "timestamp": ticker.get("last_trade_time"),
                }
        return None

    def get_orders(self, symbol: str) -> List[Dict[str, Any]]:
        return []

    def get_positions(self) -> Dict[str, Dict[str, Any]]:
        return {}
