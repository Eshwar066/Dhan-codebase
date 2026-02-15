"""
Delta Exchange WebSocket feed implementing RealtimeFeed.

Subscribes to v2/ticker and candlestick_* for symbols, optional private channels.
Used by LiveEngine when BROKER_NAME == "DELTA" for real-time data.
"""

from typing import Any, Dict, List, Optional

from core.data.feeds.base_feed import RealtimeFeed
from core.library.delta_websocket import DeltaWebSocket

# Map strategy timeframe to Delta candlestick channel name
RESOLUTION_MAP = {
    "1": "1m",
    "3": "3m",
    "5": "5m",
    "15": "15m",
    "30": "30m",
    "60": "1h",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "6h": "6h",
    "12h": "12h",
    "1d": "1d",
    "1w": "1w",
}


class DeltaWebSocketFeed(RealtimeFeed):
    """
    Real-time feed using Delta Exchange WebSocket.
    Subscribes to ticker and candlesticks for given symbols; optionally orders/positions after auth.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        symbols: List[str],
        timeframe: str = "60",
        testnet: bool = True,
        india: bool = True,
        subscribe_private: bool = True,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.symbols = list(symbols) if symbols else []
        self.timeframe = str(timeframe)
        self.testnet = testnet
        self.india = india
        self.subscribe_private = subscribe_private

        self._ws: Optional[DeltaWebSocket] = None
        self._auth_done = False

    def _channel_candlestick(self) -> str:
        res = RESOLUTION_MAP.get(self.timeframe, "1h")
        return f"candlestick_{res}"

    def start(self) -> None:
        if self._ws:
            return
        self._ws = DeltaWebSocket(
            api_key=self.api_key,
            api_secret=self.api_secret,
            testnet=self.testnet,
            india=self.india,
            on_auth=self._on_auth,
        )
        self._ws.connect()
        # Subscribe to public channels after socket is ready; private after auth success.
        import threading
        import time
        def subscribe_public_after_delay():
            time.sleep(1.5)
            self._do_subscribe_public()
        t = threading.Thread(target=subscribe_public_after_delay, daemon=True)
        t.start()

    def _on_auth(self, success: bool, msg: Dict) -> None:
        self._auth_done = success
        if success:
            self._do_subscribe_private()

    def _do_subscribe_public(self) -> None:
        if not self._ws or not self._ws.is_connected():
            return
        if not self.symbols:
            return
        channels = [
            {"name": "v2/ticker", "symbols": self.symbols},
            {"name": self._channel_candlestick(), "symbols": self.symbols},
        ]
        self._ws.subscribe(channels)

    def _do_subscribe_private(self) -> None:
        if not self._ws or not self._ws.is_connected() or not self._ws.is_authenticated():
            return
        if not self.subscribe_private:
            return
        self._ws.subscribe([
            {"name": "orders", "symbols": ["all"]},
            {"name": "positions", "symbols": ["all"]},
        ])

    def stop(self) -> None:
        if self._ws:
            self._ws.disconnect()
            self._ws = None
        self._auth_done = False

    def is_connected(self) -> bool:
        return self._ws is not None and self._ws.is_connected()

    def get_last_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        if not self._ws:
            return None
        raw = self._ws.get_last_ticker(symbol)
        if not raw:
            return None
        # Normalize to common shape for live engine (close/mark_price as price)
        mark = raw.get("mark_price")
        close = raw.get("close")
        price = float(mark) if mark is not None else (float(close) if close is not None else None)
        if price is None:
            return None
        return {
            "symbol": raw.get("symbol", symbol),
            "close": price,
            "mark_price": price,
            "open": raw.get("open"),
            "high": raw.get("high"),
            "low": raw.get("low"),
            "volume": raw.get("volume"),
            "timestamp": raw.get("timestamp"),
        }

    def get_last_candle(self, symbol: str, resolution: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if not self._ws:
            return None
        raw = self._ws.get_last_candle(symbol)
        if not raw:
            return None
        ts = raw.get("timestamp")
        if ts and isinstance(ts, (int, float)):
            # Microseconds to datetime string or keep as-is for engine
            from datetime import datetime
            if ts > 1e12:
                ts = datetime.utcfromtimestamp(ts / 1e6).isoformat() + "Z"
            else:
                ts = datetime.utcfromtimestamp(ts).isoformat() + "Z"
        return {
            "symbol": raw.get("symbol", symbol),
            "open": raw.get("open"),
            "high": raw.get("high"),
            "low": raw.get("low"),
            "close": raw.get("close"),
            "volume": raw.get("volume", 0),
            "timestamp": ts or raw.get("timestamp"),
        }

    def get_orders(self, symbol: str) -> List[Dict[str, Any]]:
        if not self._ws:
            return []
        return self._ws.get_orders(symbol)

    def get_positions(self) -> Dict[str, Dict[str, Any]]:
        if not self._ws:
            return {}
        return self._ws.get_positions()
