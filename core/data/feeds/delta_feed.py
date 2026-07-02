"""
Delta Exchange WebSocket feed implementing RealtimeFeed.

Subscribes to v2/ticker and candlestick_* for symbols, optional private channels.
Used by LiveEngine when BROKER_NAME == "DELTA" for real-time data.
"""

import logging
import queue
import threading
from typing import Any, Dict, List, Optional

from core.data.feeds.base_feed import RealtimeFeed

logger = logging.getLogger(__name__)
from core.library.delta_websocket import FEED_STALL_SEC, DeltaWebSocket

from core.data.feeds.delta_candlestick import (
    delta_ws_supports_timeframe,
    engine_timeframe_to_delta_resolution,
    resolution_to_seconds,
)


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
        candlestick_resolutions: Optional[List[str]] = None,
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
        self._candlestick_resolutions = self._normalize_candlestick_resolutions(
            candlestick_resolutions, timeframe=self.timeframe
        )
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
        self._candle_queue: Optional[Any] = None
        self._public_sub_gen_applied: int = -1
        self._stall_reconnect_triggered: bool = False
        self._user_trade_callback: Optional[Any] = None

    def set_tick_queue(self, queue: Any) -> None:
        """Push normalized ticks to queue for CandleAggregator. Set before start()."""
        self._tick_queue = queue

    def set_candle_queue(self, queue: Any) -> None:
        """Push exchange candlestick OHLC (matches REST) into the live candle pipeline."""
        self._candle_queue = queue

    def _push_candle(self, symbol: str, candle: Dict[str, Any]) -> None:
        if self._candle_queue is None:
            return
        bucket_ts = candle.get("bucket_ts")
        resolution = candle.get("resolution")
        if bucket_ts is None or not resolution:
            return
        try:
            self._candle_queue.put_nowait(
                {
                    "symbol": symbol,
                    "resolution": str(resolution),
                    "bucket_ts": int(bucket_ts),
                    "open": candle.get("open"),
                    "high": candle.get("high"),
                    "low": candle.get("low"),
                    "close": candle.get("close"),
                    "volume": candle.get("volume", 0),
                }
            )
        except queue.Full:
            if self._engine_logger:
                self._engine_logger.log(
                    "candle_dropped_queue_full",
                    f"Delta candle dropped due to full queue symbol={symbol}",
                    symbol=symbol,
                )
        except Exception as e:
            logger.debug("Delta feed: candle queue put failed: %s", e)

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
        except queue.Full:
            if self._engine_logger:
                self._engine_logger.log(
                    "tick_dropped_queue_full",
                    f"Delta tick dropped due to full queue symbol={symbol}",
                    symbol=symbol,
                )
        except Exception as e:
            logger.debug("Delta feed: tick queue put failed: %s", e)

    @staticmethod
    def _normalize_candlestick_resolutions(
        resolutions: Optional[List[str]],
        *,
        timeframe: str,
    ) -> List[str]:
        """Unique, sorted Delta candlestick channel suffixes (e.g. 1m, 5m)."""
        out: List[str] = []
        seen: set[str] = set()
        for raw in resolutions or []:
            res = engine_timeframe_to_delta_resolution(str(raw or "").strip())
            if res and res not in seen:
                seen.add(res)
                out.append(res)
        if not out:
            fallback = engine_timeframe_to_delta_resolution(timeframe)
            if fallback:
                out = [fallback]
        out.sort(key=resolution_to_seconds)
        return out

    def _channel_candlestick(self, resolution: str) -> str:
        return f"candlestick_{resolution}"

    def _candlestick_channels(
        self, symbols: List[str], resolutions: List[str]
    ) -> List[Dict[str, Any]]:
        return [
            {"name": self._channel_candlestick(res), "symbols": symbols}
            for res in resolutions
        ]

    def is_exchange_candle_timeframe(self, timeframe: Optional[str]) -> bool:
        """Delta-only: TF has a native WS candlestick channel (else use tick aggregator)."""
        return delta_ws_supports_timeframe(timeframe)

    def start(self) -> None:
        if self._ws:
            return
        on_tick = self._push_tick if self._tick_queue else None
        on_candle = self._push_candle if self._candle_queue else None

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
                and stall_sec >= FEED_STALL_SEC
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
            on_candle=on_candle,
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
            on_user_trade=self._forward_user_trade,
        )
        self._ws.connect()
        # Public subscriptions happen from _on_open (including reconnects).
        # Private subscriptions happen from _on_auth after successful key-auth.

    def _on_auth(self, success: bool, msg: Dict) -> None:
        self._auth_done = success
        if success:
            self._do_subscribe_private()

    def set_user_trade_callback(self, callback: Any) -> None:
        """Set event-driven callback for private user-trade events."""
        self._user_trade_callback = callback

    def _forward_user_trade(self, trade: Dict[str, Any]) -> None:
        cb = self._user_trade_callback
        if not cb:
            return
        try:
            cb(trade)
        except Exception as e:
            logger.debug("Delta feed: user trade callback failed: %s", e)

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
            *self._candlestick_channels(symbols, self._candlestick_resolutions),
            {"name": "l2_orderbook", "symbols": symbols},
        ]
        self._ws.subscribe(channels)
        self._public_sub_gen_applied = gen
        logger.info(
            "Delta feed: re-subscribed public channels after reconnect (gen=%s)",
            gen,
        )
        logger.info(
            "Delta feed: subscribed symbols=%s candlestick_resolutions=%s",
            symbols,
            list(self._candlestick_resolutions),
        )
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
                {"name": "v2/user_trades", "symbols": ["all"]},
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

    def get_exchange_candle_for_bucket(
        self,
        symbol: str,
        bucket_ts: int,
        timeframe: Optional[str] = None,
        resolution: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Delta WS candlestick OHLC for a bucket (same source as REST historical)."""
        if not self._ws:
            return None
        res = resolution or engine_timeframe_to_delta_resolution(timeframe)
        if not res:
            return None
        raw = self._ws.get_candle_for_bucket(symbol, int(bucket_ts), res)
        if not raw:
            return None
        try:
            return {
                "symbol": raw.get("symbol", symbol),
                "resolution": res,
                "bucket_ts": int(raw.get("bucket_ts") or bucket_ts),
                "open": float(raw.get("open") or 0),
                "high": float(raw.get("high") or 0),
                "low": float(raw.get("low") or 0),
                "close": float(raw.get("close") or 0),
                "volume": float(raw.get("volume") or 0),
            }
        except (TypeError, ValueError):
            return None

    def get_last_candle(
        self, symbol: str, resolution: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        if not self._ws:
            return None
        res = engine_timeframe_to_delta_resolution(resolution) if resolution else None
        if not res:
            res = engine_timeframe_to_delta_resolution(self.timeframe)
        raw = self._ws.get_last_candle(symbol, res)
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
        """Open orders for symbol from WS snapshot (empty when WS not ready)."""
        if not self._ws:
            return []
        return self._ws.get_open_orders_ws(symbol=symbol)

    def get_open_orders_ws(self) -> Optional[List[Dict[str, Any]]]:
        """
        All open orders from Delta WS snapshot.
        Returns None when WS is not connected or orders snapshot not received yet (caller should use REST).
        """
        if not self._ws or not self._ws.is_connected() or not self._ws.ws_open_orders_ready():
            return None
        return self._ws.get_open_orders_ws()

    def ws_open_orders_ready(self) -> bool:
        return bool(
            self._ws and self._ws.is_connected() and self._ws.ws_open_orders_ready()
        )

    def ws_positions_ready(self) -> bool:
        return bool(
            self._ws and self._ws.is_connected() and self._ws.ws_positions_ready()
        )

    def get_positions(self) -> Dict[str, Dict[str, Any]]:
        if not self._ws:
            return {}
        return self._ws.get_positions()

    def get_positions_for_recon(self) -> Optional[Dict[str, Dict[str, Any]]]:
        """
        Broker-style position map from WS snapshot.
        Returns None when WS positions snapshot is not ready (caller should use REST).
        """
        if not self._ws or not self._ws.is_connected() or not self._ws.ws_positions_ready():
            return None
        rows = self._ws.get_positions_rows_ws()
        out: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            sym = str(row.get("tradingSymbol") or "").strip()
            if not sym:
                continue
            out[sym] = {
                "qty": int(row.get("netQty", 0)),
                "avg_price": float(row.get("avgPrice", 0)),
                "segment": row.get("segment", "DELTA"),
                "lot_size": int(row.get("lotSize", 1)),
            }
        return out

    def get_recent_user_trades(self, limit: int = 200) -> List[Dict[str, Any]]:
        """Drain recent private user-trade events from WebSocket buffer."""
        if not self._ws:
            return []
        return self._ws.pop_user_trades(limit=limit)
