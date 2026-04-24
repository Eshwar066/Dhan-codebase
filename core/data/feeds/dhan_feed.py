"""
Dhan Live Market Feed WebSocket implementing RealtimeFeed.

- Connects to wss://api-feed.dhan.co (version=2, token, clientId, authType=2).
- Subscribes to instruments (ExchangeSegment + SecurityId); max 100 per message, 5000 per connection.
- Receives binary packets (Ticker, Quote, Full, OI, Prev close); exposes get_last_ticker(symbol), get_last_candle(symbol).
- Optional set_tick_queue(queue): pushes normalized ticks for CandleAggregator. Used by LiveEngine when broker is DHAN.
"""

import time
import queue
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
        engine_logger: Optional[Any] = None,
    ):
        """
        instruments: list of {"ExchangeSegment": "NSE_EQ", "SecurityId": "11536", "symbol": "RELIANCE"}.
        Use instrument_store.get_feed_instruments(symbols) to resolve symbols.
        """
        self.access_token = access_token
        self.client_id = client_id
        self.instruments = list(instruments)
        self._ws: Optional[DhanWebSocket] = None
        self._tick_queue: Optional[Any] = None
        self._engine_logger = engine_logger

    def set_tick_queue(self, queue: Any) -> None:
        """Push normalized ticks to queue for CandleAggregator. Set before start()."""
        self._tick_queue = queue

    def _push_tick(self, symbol: str, data: Dict[str, Any]) -> None:
        if self._tick_queue is None:
            return
        try:
            price = data.get("last_price")
            if price is None:
                return
            price = float(price)
            vol = float(data.get("volume") or data.get("last_traded_quantity") or 0)
            ts = data.get("last_trade_time")
            if ts is not None and isinstance(ts, (int, float)):
                if ts > 1e12:
                    ts = ts / 1e3
                elif ts > 1e9:
                    pass
                else:
                    ts = time.time()
            else:
                ts = time.time()
            self._tick_queue.put_nowait({
                "symbol": symbol,
                "price": price,
                "volume": vol,
                "timestamp": float(ts),
            })
        except queue.Full:
            if self._engine_logger:
                self._engine_logger.log(
                    "tick_dropped_queue_full",
                    f"Dhan tick dropped due to full queue symbol={symbol}",
                    symbol=symbol,
                )
        except Exception:
            pass

    def start(self) -> None:
        if self._ws:
            return
        if not self.instruments:
            return
        on_ticker = (lambda s, d: self._push_tick(s, d)) if self._tick_queue else None
        on_quote = (lambda s, d: self._push_tick(s, d)) if self._tick_queue else None
        self._ws = DhanWebSocket(
            access_token=self.access_token,
            client_id=self.client_id,
            instruments=self.instruments,
            on_ticker=on_ticker,
            on_quote=on_quote,
        )
        self._ws.connect()

    def stop(self) -> None:
        if self._ws:
            self._ws.disconnect()
            self._ws = None

    def is_connected(self) -> bool:
        return self._ws is not None and self._ws.is_connected()

    def replace_instruments(self, instruments: List[Dict[str, str]]) -> None:
        """Update subscription list thread-safely; next reconnect uses this list."""
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
