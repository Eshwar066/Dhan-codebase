"""
Delta Exchange WebSocket client.

Supports:
- Public channels: v2/ticker, l2_orderbook, l2_updates, all_trades, mark_price,
  candlestick_* (1m, 5m, etc.), spot_price, v2/spot_price, funding_rate,
  product_updates, system_status
- Private channels (after key-auth): orders, positions, margins, user_trades,
  v2/user_trades, portfolio_margins, mmp_trigger
- Authentication: key-auth (GET + timestamp + '/live', HMAC-SHA256)
- Heartbeat (recommended) or ping/pong for connection health
- Reconnect on heartbeat timeout or disconnect (429: wait 5–10 min)

URLs:
- Production India: wss://socket.india.delta.exchange
- Testnet (India & global): wss://socket.testnet.delta.exchange (India testnet DNS often fails; optional DELTA_WS_URL override)
- Limit: 150 connections per 5 min per IP; 60s inactivity disconnect.
"""

import hashlib
import hmac
import json
import logging
import os
import socket
import threading
import time
import pdb
from typing import Any, Callable, Dict, List, Optional

import websocket

from core.library.delta_rest_client import generate_signature
from core.utils.lag_diag import (
    print_ws_tick_vs_now,
    ws_tick_diag_enabled,
    ws_tick_should_drop_stale,
)

logger = logging.getLogger(__name__)


def _is_delta_ticker_message(msg: dict) -> bool:
    """
    Match Delta ``v2/ticker`` updates. Some builds use different ``type`` casing
    or omit it; fallback: ``symbol`` + ``quotes`` (order book) present.
    """
    mt = msg.get("type")
    if mt is not None:
        s = str(mt).lower()
        if s.startswith("candlestick"):
            return False
        if s == "v2/ticker" or "ticker" in s:
            return True
    if msg.get("symbol") and isinstance(msg.get("quotes"), dict):
        return True
    return False


# WebSocket base URLs
DELTA_WS_INDIA_PROD = "wss://socket.india.delta.exchange"
DELTA_WS_INDIA_TEST = "wss://socket-ind.testnet.deltaex.org"
DELTA_WS_GLOBAL_PROD = "wss://socket.delta.exchange"
DELTA_WS_GLOBAL_TEST = "wss://socket.testnet.delta.exchange"

# Heartbeat: server sends every 30s; client should reconnect if no heartbeat in 35s
HEARTBEAT_TIMEOUT_SEC = 35
# Warn if no tick/candle received for this many seconds (feed stall)
FEED_STALL_SEC = 10
# Reconnect backoff after 429
RECONNECT_AFTER_429_SEC = 300  # 5 min
# Stop reconnecting after this many consecutive connection failures (e.g. DNS unreachable)
MAX_CONNECT_FAILURES = 5


def _ws_signature(api_secret: str) -> tuple:
    """Generate timestamp and signature for key-auth. Payload: GET + timestamp + '/live'."""
    timestamp = str(int(time.time()))
    message = "GET" + timestamp + "/live"
    sig = generate_signature(api_secret, message)
    return timestamp, sig


class DeltaWebSocket:
    """
    Delta Exchange WebSocket client with subscribe/unsubscribe, auth, heartbeat, reconnect.
    Runs the connection in a background thread. Use callbacks or poll last_* for data.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        testnet: bool = False,
        india: bool = True,
        on_message: Optional[Callable[[Dict], None]] = None,
        on_auth: Optional[Callable[[bool, Dict], None]] = None,
        on_subscriptions: Optional[Callable[[Dict], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_close: Optional[Callable[[int, str], None]] = None,
        on_tick: Optional[Callable[[str, float, float, float], None]] = None,
        on_feed_stall: Optional[Callable[[float], None]] = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.on_tick = on_tick

        self.ws_url = DELTA_WS_INDIA_TEST if testnet else DELTA_WS_INDIA_PROD
        logger.info("Delta WebSocket URL: %s", self.ws_url)
        self.on_message = on_message
        self.on_auth = on_auth
        self.on_subscriptions = on_subscriptions
        self.on_error_cb = on_error
        self.on_close_cb = on_close
        self.on_feed_stall = on_feed_stall

        self._ws: Optional[websocket.WebSocketApp] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last_heartbeat = 0.0
        self._heartbeat_timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        self._authenticated = False
        self._subscribed_channels: List[Dict] = []
        self._connect_failures = 0
        self._gave_up = False
        self._reconnecting = False
        self._feed_data_logged = False
        self._last_feed_log_time = 0.0
        self._last_tick_time = 0.0
        self._feed_stall_warned = False

        # Last received data (for polling from live engine)
        self._last_ticker: Dict[str, Dict] = {}
        self._last_candle: Dict[str, Dict] = {}
        self._last_l2: Dict[str, Dict] = {}
        self._last_orderbook_l2: Dict[str, Dict] = {}
        self._orders: Dict[str, List[Dict]] = {}
        self._positions: Dict[str, Dict] = {}
        self._ws_msg_sample_count = 0

    def _send(self, payload: Dict) -> None:
        if self._ws and self._ws.sock and self._ws.sock.connected:
            self._ws.send(json.dumps(payload))

    def _enable_heartbeat(self) -> None:
        self._send({"type": "enable_heartbeat"})
        self._last_heartbeat = time.time()
        self._schedule_heartbeat_check()

    def _schedule_heartbeat_check(self) -> None:
        def check():
            if self._stop.is_set():
                return
            with self._lock:
                elapsed = time.time() - self._last_heartbeat
                if elapsed >= HEARTBEAT_TIMEOUT_SEC:
                    logger.warning(
                        "Delta WebSocket: no heartbeat in %.0fs, reconnecting",
                        elapsed,
                    )
                    self._reconnect()
                    return
                # Feed stall: warn if we had data before but no ticks for FEED_STALL_SEC
                if (
                    self._feed_data_logged
                    and self._last_tick_time > 0
                    and time.time() - self._last_tick_time > FEED_STALL_SEC
                ):
                    if not self._feed_stall_warned:
                        self._feed_stall_warned = True
                        stall_sec = time.time() - self._last_tick_time
                        logger.warning(
                            "[WARNING] No ticks received for %.0f seconds!",
                            stall_sec,
                        )
                        if self.on_feed_stall:
                            try:
                                self.on_feed_stall(stall_sec)
                            except Exception as e:
                                logger.debug(
                                    "Delta WS feed_stall callback error: %s", e
                                )
            self._heartbeat_timer = threading.Timer(15, check)
            self._heartbeat_timer.daemon = True
            self._heartbeat_timer.start()

        self._heartbeat_timer = threading.Timer(15, check)
        self._heartbeat_timer.daemon = True
        self._heartbeat_timer.start()

    def _on_ws_message(self, _ws, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.debug("Delta WS invalid JSON: %s", e)
            return

        msg_type = msg.get("type")
        if ws_tick_diag_enabled() and self._ws_msg_sample_count < 12:
            self._ws_msg_sample_count += 1
            logger.info(
                "Delta WS msg #%s type=%r symbol=%r",
                self._ws_msg_sample_count,
                msg_type,
                msg.get("symbol"),
            )

        if msg_type == "heartbeat":
            with self._lock:
                self._last_heartbeat = time.time()
            if self.on_message:
                self.on_message(msg)
            return

        if msg_type == "pong":
            with self._lock:
                self._last_heartbeat = time.time()
            if self.on_message:
                self.on_message(msg)
            return

        if msg_type == "key-auth":
            success = msg.get("success", False)
            self._authenticated = success
            if not success and msg.get("status") == "api_key_not_found":
                logger.warning(
                    "Delta WebSocket key-auth failed: ApiKey not found. "
                    "Demo/testnet keys from India testnet do not work on global testnet WebSocket "
                    "(wss://socket.testnet.delta.exchange). Create API keys at https://testnet.delta.exchange "
                    "for the same environment as the WebSocket URL, or set DELTA_WS_URL if using India testnet."
                )
            if self.on_auth:
                self.on_auth(success, msg)
            if self.on_message:
                self.on_message(msg)
            return

        if msg_type == "subscriptions":
            channels = msg.get("channels", [])
            self._subscribed_channels = channels
            if self.on_subscriptions:
                self.on_subscriptions(msg)
            if self.on_message:
                self.on_message(msg)
            return

        # Public market data
        if _is_delta_ticker_message(msg):
            if ws_tick_should_drop_stale(msg):
                return
            print_ws_tick_vs_now(msg)
            self._last_tick_time = time.time()
            self._feed_stall_warned = False
            if not self._feed_data_logged:
                self._feed_data_logged = True
                self._last_feed_log_time = self._last_tick_time
                logger.info(
                    "Delta WebSocket feed: receiving market data (ticker/candle)."
                )
            else:
                now = self._last_tick_time
                if now - self._last_feed_log_time >= 30:
                    self._last_feed_log_time = now
                    logger.info("Delta WebSocket feed: receiving data.")
            sym = msg.get("symbol")
            if sym:
                with self._lock:
                    self._last_ticker[sym] = msg
                if self.on_tick:
                    try:
                        price = float(
                            msg.get("mark_price")
                            or msg.get("close")
                            or msg.get("last_price")
                            or 0
                        )
                        vol = float(msg.get("volume") or msg.get("size") or 0)
                        ts = (
                            msg.get("timestamp")
                            or msg.get("generated_at")
                            or time.time()
                        )
                        if isinstance(ts, (int, float)) and ts > 1e12:
                            ts = ts / 1e6
                        elif not isinstance(ts, (int, float)):
                            ts = time.time()
                        self.on_tick(sym, price, vol, float(ts))
                    except Exception as e:
                        logger.debug("Delta WS on_tick callback error: %s", e)
            if self.on_message:
                self.on_message(msg)
            return

        if msg_type and msg_type.startswith("candlestick_"):
            if ws_tick_should_drop_stale(msg):
                return
            print_ws_tick_vs_now(msg)
            self._last_tick_time = time.time()
            self._feed_stall_warned = False
            if not self._feed_data_logged:
                self._feed_data_logged = True
                self._last_feed_log_time = self._last_tick_time
                logger.info(
                    "Delta WebSocket feed: receiving market data (ticker/candle)."
                )
            else:
                now = self._last_tick_time
                if now - self._last_feed_log_time >= 30:
                    self._last_feed_log_time = now
                    logger.info("Delta WebSocket feed: receiving data.")
            sym = msg.get("symbol")
            if sym:
                candle = {
                    "symbol": sym,
                    "open": msg.get("open"),
                    "high": msg.get("high"),
                    "low": msg.get("low"),
                    "close": msg.get("close"),
                    "volume": msg.get("volume"),
                    "timestamp": msg.get("candle_start_time") or msg.get("timestamp"),
                    "resolution": msg.get("resolution", ""),
                }
                with self._lock:
                    self._last_candle[sym] = candle
            if self.on_message:
                self.on_message(msg)
            return

        if msg_type == "l2_orderbook":
            sym = msg.get("symbol")
            if sym:
                with self._lock:
                    self._last_l2[sym] = msg
            if self.on_message:
                self.on_message(msg)
            return

        if msg_type == "l2_updates":
            sym = msg.get("symbol")
            if sym:
                with self._lock:
                    self._last_orderbook_l2[sym] = msg
            if self.on_message:
                self.on_message(msg)
            return

        if msg_type == "all_trades" or msg_type == "all_trades_snapshot":
            if self.on_message:
                self.on_message(msg)
            return

        if (
            msg_type == "mark_price"
            or msg_type == "spot_price"
            or msg_type == "v2/spot_price"
        ):
            if self.on_message:
                self.on_message(msg)
            return

        if msg_type == "funding_rate" or msg_type == "product_updates":
            if self.on_message:
                self.on_message(msg)
            return

        if msg_type == "system_status" or msg_type == "announcements":
            if self.on_message:
                self.on_message(msg)
            return

        # Private
        if msg_type == "orders":
            sym = msg.get("symbol") or msg.get("symbols", [])
            if isinstance(sym, str):
                with self._lock:
                    if sym not in self._orders:
                        self._orders[sym] = []
                    result = msg.get("result", [])
                    if msg.get("action") == "snapshot" and result:
                        self._orders[sym] = result
                    elif msg.get("action") in ("create", "update", "delete"):
                        # Could merge into list; for now just notify
                        pass
            if self.on_message:
                self.on_message(msg)
            return

        if msg_type == "positions":
            sym = msg.get("symbol")
            if sym:
                with self._lock:
                    self._positions[sym] = msg
            if msg.get("action") == "snapshot" and msg.get("result"):
                for p in msg["result"]:
                    s = p.get("symbol") or p.get("product_symbol")
                    if s:
                        with self._lock:
                            self._positions[s] = p
            if self.on_message:
                self.on_message(msg)
            return

        if msg_type in (
            "margins",
            "v2/user_trades",
            "user_trades",
            "portfolio_margins",
            "mmp_trigger",
        ):
            if self.on_message:
                self.on_message(msg)
            return

        if self.on_message:
            self.on_message(msg)

    def _on_open(self, _ws) -> None:
        self._connect_failures = 0  # reset on successful connect
        logger.info("Delta WebSocket connected to %s", self.ws_url)
        self._enable_heartbeat()
        timestamp, signature = _ws_signature(self.api_secret)
        self._send(
            {
                "type": "key-auth",
                "payload": {
                    "api-key": self.api_key,
                    "timestamp": timestamp,
                    "signature": signature,
                },
            }
        )

    def _on_error(self, _ws, error: Exception) -> None:
        self._connect_failures += 1
        if self._connect_failures == 1:
            logger.warning(
                "Delta WebSocket connection failed: %s. Engine will use candle_service/REST for data. Reconnects will be attempted in background.",
                error,
            )
        elif self._connect_failures >= MAX_CONNECT_FAILURES:
            if not self._gave_up:
                self._gave_up = True
                logger.info(
                    "Delta WebSocket unavailable after %s attempts. Using REST/candle fallback; reconnect stopped.",
                    MAX_CONNECT_FAILURES,
                )
        else:
            logger.debug(
                "Delta WebSocket reconnect attempt %s failed: %s",
                self._connect_failures,
                error,
            )
        if self.on_error_cb:
            self.on_error_cb(error)

    def _on_close(self, _ws, close_status_code: int, close_msg: str) -> None:
        logger.info("Delta WebSocket closed: %s %s", close_status_code, close_msg)
        if self._heartbeat_timer:
            self._heartbeat_timer.cancel()
            self._heartbeat_timer = None
        if self.on_close_cb:
            self.on_close_cb(close_status_code, close_msg or "")
        if close_status_code == 429:
            logger.warning("Rate limited (429). Wait 5–10 min before reconnecting.")
            time.sleep(RECONNECT_AFTER_429_SEC)
        if not self._stop.is_set() and not self._gave_up:
            self._reconnect()

    def _make_ws_app(self) -> websocket.WebSocketApp:
        """Create a new WebSocketApp (used by connect() and _reconnect())."""
        return websocket.WebSocketApp(
            self.ws_url,
            on_message=self._on_ws_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open,
        )

    def connect(self) -> None:
        """Start WebSocket connection in a background thread."""
        logger.info("Delta WebSocket URL: %s", self.ws_url)
        self._stop.clear()
        if self._thread is None:
            self._gave_up = False
            self._connect_failures = 0
        self._ws = self._make_ws_app()
        self._thread = threading.Thread(target=self._run_forever, daemon=True)
        self._thread.start()

    def _reconnect(self) -> None:
        """Replace WebSocket app and let the same thread run run_forever again (no second thread)."""
        if self._heartbeat_timer:
            self._heartbeat_timer.cancel()
            self._heartbeat_timer = None
        if self._ws:
            try:
                self._ws.close()
            except Exception as e:
                logger.debug("Delta WS close during reconnect: %s", e)
            self._ws = None
        logger.debug("Delta WebSocket: reconnecting in 2s...")
        time.sleep(2)
        if self._stop.is_set() or self._gave_up:
            return
        self._ws = self._make_ws_app()

    def _run_forever(self) -> None:
        while not self._stop.is_set() and self._ws and not self._gave_up:
            try:
                self._ws.run_forever(ping_interval=30, ping_timeout=5)
            except Exception as e:
                if not self._gave_up:
                    logger.warning("Delta WebSocket run_forever: %s", e)
            if self._stop.is_set() or self._gave_up:
                break
            time.sleep(2)

    def disconnect(self) -> None:
        """Stop the WebSocket connection."""
        self._stop.set()
        if self._heartbeat_timer:
            self._heartbeat_timer.cancel()
            self._heartbeat_timer = None
        if self._ws:
            try:
                self._ws.close()
            except Exception as e:
                logger.debug("Delta WS close during disconnect: %s", e)
            self._ws = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def subscribe(
        self,
        channels: List[Dict[str, Any]],
    ) -> None:
        """
        Subscribe to channels. Each item: {"name": "v2/ticker", "symbols": ["BTCUSD"]}.
        Use symbols: ["all"] for channels that support it (no snapshot for "all").
        """
        if not self._ws or not self._ws.sock or not self._ws.sock.connected:
            logger.warning("Delta WebSocket: not connected, cannot subscribe")
            return
        payload = {"type": "subscribe", "payload": {"channels": channels}}
        self._send(payload)

    def unsubscribe(self, channels: List[Dict[str, Any]]) -> None:
        """Unsubscribe. Same structure as subscribe; omit symbols to unsubscribe from entire channel."""
        if not self._ws or not self._ws.sock or not self._ws.sock.connected:
            return
        payload = {"type": "unsubscribe", "payload": {"channels": channels}}
        self._send(payload)

    def ping(self) -> None:
        """Send ping (server responds with pong). Alternative to heartbeat."""
        self._send({"type": "ping"})

    def unauth(self) -> None:
        """Unsubscribe from all private channels."""
        self._send({"type": "unauth", "payload": {}})

    def get_last_ticker(self, symbol: str) -> Optional[Dict]:
        with self._lock:
            return self._last_ticker.get(symbol)

    def get_last_candle(self, symbol: str) -> Optional[Dict]:
        with self._lock:
            return self._last_candle.get(symbol)

    def get_last_l2_orderbook(self, symbol: str) -> Optional[Dict]:
        with self._lock:
            return self._last_l2.get(symbol) or self._last_orderbook_l2.get(symbol)

    def get_orders(self, symbol: str) -> List[Dict]:
        with self._lock:
            return list(self._orders.get(symbol, []))

    def get_positions(self) -> Dict[str, Dict]:
        with self._lock:
            return dict(self._positions)

    def is_connected(self) -> bool:
        return (
            self._ws is not None
            and self._ws.sock is not None
            and getattr(self._ws.sock, "connected", False)
        )

    def is_authenticated(self) -> bool:
        return self._authenticated
