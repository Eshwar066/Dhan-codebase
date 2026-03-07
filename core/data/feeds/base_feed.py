"""
Abstract base for real-time market/account feeds (WebSocket).

Implementations: DeltaWebSocketFeed (Delta Exchange), DhanWebSocketFeed (Dhan).
Used by LiveEngine to consume real-time ticker/candles/orders/positions
instead of or in addition to REST polling. Optional tick queue for CandleAggregator:
feed pushes normalized ticks to engine-owned queue; processor loop drains and aggregates.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class RealtimeFeed(ABC):
    """
    Interface for a real-time feed (WebSocket) that can supply:
    - Ticker / LTP per symbol
    - Latest candle per symbol (for strategy-on-close)
    - Optional: order/position updates (for sync with broker)
    """

    @abstractmethod
    def start(self) -> None:
        """Connect and start receiving data (e.g. spawn background thread)."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Disconnect and stop the feed."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if the feed is connected and receiving."""
        pass

    def get_last_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Last ticker/LTP for symbol. Keys may include: close, mark_price, symbol, etc."""
        return None

    def get_last_candle(self, symbol: str, resolution: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Last closed (or latest) candle for symbol.
        resolution: e.g. "1m", "5m", "60" for 1h. Feed may ignore if only one resolution.
        Returns dict with open, high, low, close, volume, timestamp, symbol.
        """
        return None

    def get_orders(self, symbol: str) -> List[Dict[str, Any]]:
        """Open/pending orders for symbol (if private feed supported)."""
        return []

    def get_positions(self) -> Dict[str, Dict[str, Any]]:
        """Current positions by symbol (if private feed supported)."""
        return {}

    def set_tick_queue(self, queue: Any) -> None:
        """
        Optional: set engine-owned queue for tick streaming. When set, feed pushes
        normalized ticks {"symbol", "price", "volume", "timestamp"} (timestamp in Unix sec)
        so CandleAggregator can build 1m and higher timeframes. Broker-agnostic; same
        format for Dhan and Delta. Call before start() for effect.
        """
        pass
