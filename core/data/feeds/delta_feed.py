"""
Delta Exchange WebSocket feed implementing RealtimeFeed.

Subscribes to v2/ticker and candlestick_* for symbols, optional private channels.
Used by LiveEngine when BROKER_NAME == "DELTA" for real-time data.
"""

import logging
import threading
from typing import Any, Dict, List, Optional

from core.data.feeds.base_feed import RealtimeFeed

logger = logging.getLogger(__name__)
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
        engine_logger: Optional[Any] = None,
        telegram_alert: Optional[Any] = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.symbols = list(symbols) if symbols else []
        self.timeframe = str(timeframe)
        self.testnet = testnet
        self.india = india
        self.subscribe_private = subscribe_private
        self._engine_logger = engine_logger
        self._telegram_alert = telegram_alert

        # l2_orderbook is per-instrument on Delta; underlying (e.g. BTCUSD) is subscribed in
        # _do_subscribe_public. Option symbols are added on demand.
        self._l2_sub_lock = threading.Lock()
        self._subscribed_l2_symbols: set[str] = set()
        self._l2_gen_applied: int = -1

        self._ws: Optional[DeltaWebSocket] = None
        self._auth_done = False
        self._tick_queue: Optional[Any] = None
        self._public_sub_gen_applied: int = -1
        self._stall_reconnect_triggered: bool = False

    def set_tick_queue(self, queue: Any) -> None:
        """Push normalized ticks to queue for CandleAggregator. Set before start()."""
        self._tick_queue = queue

    def _push_tick(
        self, symbol: str, price: float, volume: float, timestamp_sec: float
    ) -> None:
        if self._tick_queue is None:
            return
        try:
            self._tick_queue.put_nowait(
                {
                    "symbol": symbol,
                    "price": price,
                    "volume": volume,
                    "timestamp": timestamp_sec,
                }
            )
        except Exception as e:
            logger.debug("Delta feed: tick queue put failed: %s", e)

    def _channel_candlestick(self) -> str:
        res = RESOLUTION_MAP.get(self.timeframe, "1h")
        return f"candlestick_{res}"

    def start(self) -> None:
        if self._ws:
            return
        on_tick = self._push_tick if self._tick_queue else None

        def _on_feed_stall(stall_sec: float) -> None:
            msg = f"Delta feed stall: no ticks received for {stall_sec:.0f}s"
            if self._engine_logger:
                self._engine_logger.feed_health_warning(message=msg)
            if self._telegram_alert:
                try:
                    self._telegram_alert(f"⚠️ {msg}")
                except Exception as e:
                    logger.debug("Delta feed: telegram stall alert failed: %s", e)
            # Watchdog: force reconnect once per stall window.
            if (
                self._ws
                and stall_sec >= 10
                and not self._stall_reconnect_triggered
            ):
                self._stall_reconnect_triggered = True
                self._ws.request_reconnect(reason=f"feed_stall_{int(stall_sec)}s")

        def _on_feed_recovered() -> None:
            msg = "Delta feed recovered: ticks resumed after stall (feed healthy)"
            if self._engine_logger:
                self._engine_logger.feed_health_recovered(message=msg)
            if self._telegram_alert:
                try:
                    self._telegram_alert(f"✅ {msg}")
                except Exception as e:
                    logger.debug("Delta feed: telegram recovered alert failed: %s", e)
            self._stall_reconnect_triggered = False

        def _on_open() -> None:
            # Re-subscribe on every websocket open (initial connect + reconnect).
            def _subscribe_after_ready() -> None:
                import time

                for _ in range(20):
                    if self._ws and self._ws.is_connected():
                        break
                    time.sleep(0.25)
                self._do_subscribe_public()
                if self._auth_done:
                    self._do_subscribe_private()

            threading.Thread(target=_subscribe_after_ready, daemon=True).start()

        def _on_subscriptions(msg: Dict[str, Any]) -> None:
            channels = msg.get("channels", []) if isinstance(msg, dict) else []
            logger.info("Delta feed subscription ack: channels=%s", channels)

        self._ws = DeltaWebSocket(
            api_key=self.api_key,
            api_secret=self.api_secret,
            testnet=self.testnet,
            india=self.india,
            on_open=_on_open,
            on_auth=self._on_auth,
            on_subscriptions=_on_subscriptions,
            on_tick=on_tick,
            on_feed_stall=(
                _on_feed_stall
                if (self._engine_logger or self._telegram_alert)
                else None
            ),
            on_feed_recovered=(
                _on_feed_recovered
                if (self._engine_logger or self._telegram_alert)
                else None
            ),
        )
        self._ws.connect()
        # Public subscriptions happen from _on_open (including reconnects).
        # Private subscriptions happen from _on_auth after successful key-auth.

    def _on_auth(self, success: bool, msg: Dict) -> None:
        self._auth_done = success
        if success:
            self._do_subscribe_private()

    def _do_subscribe_public(self) -> None:
        if not self._ws or not self._ws.is_connected():
            return
        symbols = list(self.symbols) if self.symbols else []
        if not symbols:
            return
        gen = self._ws.connect_generation
        if self._public_sub_gen_applied == gen:
            return
        channels = [
            {"name": "v2/ticker", "symbols": symbols},
            {"name": self._channel_candlestick(), "symbols": symbols},
            {"name": "l2_orderbook", "symbols": symbols},
        ]
        self._ws.subscribe(channels)
        self._public_sub_gen_applied = gen
        logger.info(
            "Delta feed: re-subscribed public channels after reconnect (gen=%s)",
            gen,
        )
        logger.info("Delta feed: subscribed symbols=%s", symbols)
        with self._l2_sub_lock:
            self._subscribed_l2_symbols = {str(s).strip().upper() for s in symbols}
            self._l2_gen_applied = gen

    def ensure_l2_orderbook_subscription(self, symbol: str) -> None:
        """
        Subscribe to ``l2_orderbook`` for ``symbol`` if not already covered.

        Underlying symbols from ``self.symbols`` are subscribed at startup; each option
        contract (e.g. ``C-BTC-70000-100426``) must be subscribed explicitly—Delta does
        not inherit depth from BTCUSD.
        """
        if not symbol or not self._ws:
            return
        raw = str(symbol).strip()
        if not raw:
            return
        key = raw.upper()
        if not self._ws.is_connected():
            return
        gen = self._ws.connect_generation
        with self._l2_sub_lock:
            if self._l2_gen_applied != gen:
                self._subscribed_l2_symbols = {str(s).strip().upper() for s in self.symbols}
                self._l2_gen_applied = gen
            if key in self._subscribed_l2_symbols:
                return
            self._ws.subscribe([{"name": "l2_orderbook", "symbols": [raw]}])
            self._subscribed_l2_symbols.add(key)
            logger.info("DeltaWebSocketFeed: subscribed l2_orderbook for %s", raw)

    def _do_subscribe_private(self) -> None:
        if (
            not self._ws
            or not self._ws.is_connected()
            or not self._ws.is_authenticated()
        ):
            return
        if not self.subscribe_private:
            return
        self._ws.subscribe(
            [
                {"name": "orders", "symbols": ["all"]},
                {"name": "positions", "symbols": ["all"]},
            ]
        )

    def stop(self) -> None:
        if self._ws:
            self._ws.disconnect()
            self._ws = None
        self._auth_done = False
        self._public_sub_gen_applied = -1
        self._stall_reconnect_triggered = False

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
        price = (
            float(mark)
            if mark is not None
            else (float(close) if close is not None else None)
        )
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

    def get_last_candle(
        self, symbol: str, resolution: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
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

    def get_last_l2_orderbook(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Raw L2 order book for symbol (bids/asks). Used for best bid/ask."""
        if not self._ws:
            return None
        self.ensure_l2_orderbook_subscription(symbol)
        return self._ws.get_last_l2_orderbook(symbol)

    def get_best_bid(self, symbol: str) -> Optional[float]:
        """Best bid price for symbol from L2 order book. For Delta limit BUY at best bid."""
        if not self._ws:
            return None
        self.ensure_l2_orderbook_subscription(symbol)
        ob = self._ws.get_last_l2_orderbook(symbol)
        if not ob:
            return None
        bids = ob.get("bids") or ob.get("buy") or []
        if not bids:
            return None
        first = bids[0]
        if isinstance(first, (list, tuple)) and len(first) >= 1:
            return float(first[0])
        if isinstance(first, dict):
            return float(
                first.get("price")
                or first.get("limit_price")
                or first.get("price_str")
                or 0
            )
        return None

    def get_best_ask(self, symbol: str) -> Optional[float]:
        """Best ask price for symbol from L2 order book. For Delta limit SELL at best ask."""
        if not self._ws:
            return None
        self.ensure_l2_orderbook_subscription(symbol)
        ob = self._ws.get_last_l2_orderbook(symbol)
        if not ob:
            return None
        asks = ob.get("asks") or ob.get("sell") or []
        if not asks:
            return None
        first = asks[0]
        if isinstance(first, (list, tuple)) and len(first) >= 1:
            return float(first[0])
        if isinstance(first, dict):
            return float(
                first.get("price")
                or first.get("limit_price")
                or first.get("price_str")
                or 0
            )
        return None

    def get_orders(self, symbol: str) -> List[Dict[str, Any]]:
        if not self._ws:
            return []
        return self._ws.get_orders(symbol)

    def get_positions(self) -> Dict[str, Dict[str, Any]]:
        if not self._ws:
            return {}
        return self._ws.get_positions()
