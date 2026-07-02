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
from typing import Any, Callable, Dict, List, Optional

import websocket

from core.library.delta_rest_client import generate_signature
from core.data.feeds.delta_candlestick import resolution_to_seconds
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
FEED_STALL_SEC = 90
# Reconnect backoff after 429
RECONNECT_AFTER_429_SEC = 300  # 5 min
# Stop reconnecting after this many consecutive connection failures (e.g. DNS unreachable)
MAX_CONNECT_FAILURES = 5


def _candle_start_to_bucket_ts(raw_ts: Any, tf_seconds: int = 60) -> Optional[int]:
    """Normalize Delta candle_start_time to UTC epoch seconds (bar open for ``tf_seconds``)."""
    if raw_ts is None:
        return None
    try:
        ts = float(raw_ts)
    except (TypeError, ValueError):
        return None
    if ts > 1e12:
        ts = ts / 1e6
    elif ts > 1e10:
        ts = ts / 1000.0
    sec = int(ts)
    tf = max(60, int(tf_seconds or 60))
    return sec - (sec % tf) if sec > 0 else None


def _resolution_from_candlestick_msg_type(msg_type: str) -> Optional[str]:
    """``candlestick_5m`` → ``5m``."""
    s = str(msg_type or "").strip().lower()
    if not s.startswith("candlestick_"):
        return None
    res = s.split("_", 1)[-1]
    return res or None


# Align with DeltaBroker.get_open_orders and REST get_order_list normalization.
_DELTA_OPEN_ORDER_STATES = frozenset(
    {"open", "pending", "placed", "trigger pending", "live", "untriggered"}
)
_DELTA_TERMINAL_ORDER_STATES = frozenset(
    {"closed", "cancelled", "canceled", "filled", "rejected", "expired", "done"}
)


def _delta_order_status(raw: Dict[str, Any]) -> str:
    return str(raw.get("state") or raw.get("status") or "").strip().lower()


def _delta_is_open_order(raw: Dict[str, Any]) -> bool:
    status = _delta_order_status(raw)
    if not status:
        return True
    if status in _DELTA_TERMINAL_ORDER_STATES:
        return False
    if status in _DELTA_OPEN_ORDER_STATES:
        return True
    return status not in _DELTA_TERMINAL_ORDER_STATES


def _delta_order_id(raw: Dict[str, Any]) -> Optional[str]:
    oid = raw.get("id") or raw.get("order_id")
    if oid is None:
        return None
    s = str(oid).strip()
    return s or None


def normalize_delta_ws_order(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize Delta WS/REST order dict to engine broker shape."""
    if not isinstance(raw, dict):
        return None
    oid = _delta_order_id(raw)
    if not oid:
        return None
    product = raw.get("product") if isinstance(raw.get("product"), dict) else {}
    try:
        qty = int(raw.get("size") or raw.get("qty") or 0)
    except (TypeError, ValueError):
        qty = 0
    try:
        remaining = int(raw.get("unfilled_size") or raw.get("remaining_qty") or qty)
    except (TypeError, ValueError):
        remaining = qty
    try:
        price = float(raw.get("limit_price") or raw.get("price") or 0)
    except (TypeError, ValueError):
        price = 0.0
    return {
        "order_id": oid,
        "tag": raw.get("client_order_id") or raw.get("tag"),
        "product_id": raw.get("product_id") or product.get("id"),
        "symbol": raw.get("product_symbol")
        or raw.get("symbol")
        or product.get("symbol"),
        "status": _delta_order_status(raw),
        "side": str(raw.get("side") or "").lower(),
        "qty": qty,
        "remaining_qty": remaining,
        "price": price,
        "reduce_only": bool(raw.get("reduce_only")),
        "created_at": raw.get("created_at") or raw.get("timestamp"),
    }


def normalize_delta_ws_position(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize Delta WS/REST position to DeltaSource.get_positions row shape."""
    if not isinstance(raw, dict):
        return None
    product = raw.get("product") if isinstance(raw.get("product"), dict) else {}
    try:
        size = int(raw.get("size") or raw.get("netQty") or 0)
    except (TypeError, ValueError):
        size = 0
    try:
        entry_price = float(
            raw.get("entry_price")
            or raw.get("average_fill_price")
            or raw.get("avgPrice")
            or 0
        )
    except (TypeError, ValueError):
        entry_price = 0.0
    product_id = raw.get("product_id") or product.get("id") or raw.get("id")
    trading_sym = (
        raw.get("product_symbol")
        or raw.get("tradingSymbol")
        or raw.get("symbol")
        or product.get("symbol")
    )
    if not trading_sym and product_id is not None:
        trading_sym = str(product_id)
    if trading_sym is None and size == 0:
        return None
    return {
        "tradingSymbol": str(trading_sym or "").strip(),
        "product_id": product_id,
        "netQty": size,
        "avgPrice": entry_price,
        "segment": "DELTA",
        "lotSize": 1,
    }


def _delta_position_key(raw: Dict[str, Any]) -> Optional[str]:
    norm = normalize_delta_ws_position(raw)
    if not norm:
        return None
    pid = norm.get("product_id")
    if pid is not None:
        return f"pid:{pid}"
    sym = str(norm.get("tradingSymbol") or "").strip().upper()
    return f"sym:{sym}" if sym else None


def _delta_ws_result_entries(msg: Dict[str, Any]) -> List[Dict[str, Any]]:
    result = msg.get("result")
    if isinstance(result, list):
        return [e for e in result if isinstance(e, dict)]
    if isinstance(result, dict):
        return [result]
    if any(
        k in msg
        for k in (
            "id",
            "order_id",
            "product_id",
            "size",
            "entry_price",
            "client_order_id",
        )
    ):
        return [msg]
    return []


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
        on_open: Optional[Callable[[], None]] = None,
        on_message: Optional[Callable[[Dict], None]] = None,
        on_auth: Optional[Callable[[bool, Dict], None]] = None,
        on_subscriptions: Optional[Callable[[Dict], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_close: Optional[Callable[[int, str], None]] = None,
        on_tick: Optional[Callable[[str, float, float, float], None]] = None,
        on_candle: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        on_feed_stall: Optional[Callable[[float], None]] = None,
        on_feed_recovered: Optional[Callable[[], None]] = None,
        on_user_trade: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.on_tick = on_tick
        self.on_candle = on_candle

        self.ws_url = DELTA_WS_INDIA_TEST if testnet else DELTA_WS_INDIA_PROD
        logger.info("Delta WebSocket URL: %s", self.ws_url)
        self.on_open_cb = on_open
        self.on_message = on_message
        self.on_auth = on_auth
        self.on_subscriptions = on_subscriptions
        self.on_error_cb = on_error
        self.on_close_cb = on_close
        self.on_feed_stall = on_feed_stall
        self.on_feed_recovered = on_feed_recovered
        self.on_user_trade = on_user_trade

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
        self._last_candle: Dict[str, Dict[str, Dict]] = {}
        # symbol -> resolution (e.g. 5m) -> bucket_ts -> candle
        self._candles_by_bucket: Dict[str, Dict[str, Dict[int, Dict[str, Any]]]] = {}
        self._last_l2: Dict[str, Dict] = {}
        self._last_orderbook_l2: Dict[str, Dict] = {}
        self._orders_by_id: Dict[str, Dict[str, Any]] = {}
        self._positions_by_key: Dict[str, Dict[str, Any]] = {}
        self._orders_ws_snapshot_ready = False
        self._positions_ws_snapshot_ready = False
        self._orders_ws_last_update = 0.0
        self._positions_ws_last_update = 0.0
        self._user_trades: List[Dict] = []
        self._ws_msg_sample_count = 0
        # Incremented on each successful WebSocket open (incl. reconnect); feeds use to re-apply L2 subs.
        self._connect_generation = 0

    def _reset_private_ws_state(self) -> None:
        with self._lock:
            self._orders_by_id.clear()
            self._positions_by_key.clear()
            self._orders_ws_snapshot_ready = False
            self._positions_ws_snapshot_ready = False
            self._orders_ws_last_update = 0.0
            self._positions_ws_last_update = 0.0

    def _apply_orders_ws_message(self, msg: Dict[str, Any]) -> None:
        action = str(msg.get("action") or "").strip().lower()
        now = time.time()
        with self._lock:
            if action == "snapshot":
                self._orders_by_id.clear()
                for raw in _delta_ws_result_entries(msg):
                    norm = normalize_delta_ws_order(raw)
                    if norm and _delta_is_open_order(raw):
                        self._orders_by_id[norm["order_id"]] = norm
                self._orders_ws_snapshot_ready = True
                self._orders_ws_last_update = now
                return

            if action == "delete":
                oid = _delta_order_id(msg) or _delta_order_id(
                    msg.get("result") if isinstance(msg.get("result"), dict) else {}
                )
                if oid:
                    self._orders_by_id.pop(oid, None)
                self._orders_ws_last_update = now
                return

            entries = _delta_ws_result_entries(msg)
            if not entries and action in ("create", "update", ""):
                entries = [msg]
            for raw in entries:
                norm = normalize_delta_ws_order(raw)
                if not norm:
                    continue
                oid = norm["order_id"]
                if _delta_is_open_order(raw):
                    self._orders_by_id[oid] = norm
                else:
                    self._orders_by_id.pop(oid, None)
            if entries:
                self._orders_ws_last_update = now

    def _apply_positions_ws_message(self, msg: Dict[str, Any]) -> None:
        action = str(msg.get("action") or "").strip().lower()
        now = time.time()
        with self._lock:
            if action == "snapshot":
                self._positions_by_key.clear()
                for raw in _delta_ws_result_entries(msg):
                    key = _delta_position_key(raw)
                    norm = normalize_delta_ws_position(raw)
                    if key and norm and int(norm.get("netQty") or 0) != 0:
                        self._positions_by_key[key] = norm
                self._positions_ws_snapshot_ready = True
                self._positions_ws_last_update = now
                return

            if action == "delete":
                key = _delta_position_key(msg)
                if not key and isinstance(msg.get("result"), dict):
                    key = _delta_position_key(msg["result"])
                if key:
                    self._positions_by_key.pop(key, None)
                self._positions_ws_last_update = now
                return

            entries = _delta_ws_result_entries(msg)
            if not entries and action in ("create", "update", ""):
                entries = [msg]
            for raw in entries:
                key = _delta_position_key(raw)
                norm = normalize_delta_ws_position(raw)
                if not key or not norm:
                    continue
                if int(norm.get("netQty") or 0) == 0:
                    self._positions_by_key.pop(key, None)
                else:
                    self._positions_by_key[key] = norm
            if entries:
                self._positions_ws_last_update = now

    def _mark_feed_tick_received(self) -> None:
        """Update tick time and clear stall flag; notify if we are resuming after a stall warning."""
        was_stalled = self._feed_stall_warned
        self._last_tick_time = time.time()
        self._feed_stall_warned = False
        if was_stalled and self.on_feed_recovered:
            try:
                self.on_feed_recovered()
            except Exception as e:
                logger.debug("Delta WS on_feed_recovered callback error: %s", e)

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
            self._mark_feed_tick_received()
            if not self._feed_data_logged:
                self._feed_data_logged = True
                self._last_feed_log_time = self._last_tick_time
                logger.info(
                    "Delta WebSocket feed: receiving market data (ticker/candle)."
                )
            else:
                now = self._last_tick_time
                if now - self._last_feed_log_time >= 1800:
                    self._last_feed_log_time = now
                    logger.info("Delta WebSocket feed: receiving data.")
            sym = msg.get("symbol")
            if sym:
                with self._lock:
                    self._last_ticker[sym] = msg
                if self.on_tick:
                    try:
                        price = float(
                            msg.get("close")
                            or msg.get("last_price")
                            or msg.get("mark_price")
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
            self._mark_feed_tick_received()
            if not self._feed_data_logged:
                self._feed_data_logged = True
                self._last_feed_log_time = self._last_tick_time
                logger.info(
                    "Delta WebSocket feed: receiving market data (ticker/candle)."
                )
            else:
                now = self._last_tick_time
                if now - self._last_feed_log_time >= 1800:
                    self._last_feed_log_time = now
                    logger.info("Delta WebSocket feed: receiving data.")
            sym = msg.get("symbol")
            if sym:
                resolution = _resolution_from_candlestick_msg_type(msg_type or "")
                if not resolution:
                    resolution = str(msg.get("resolution") or "").strip().lower() or "1m"
                tf_sec = resolution_to_seconds(resolution)
                bucket_ts = _candle_start_to_bucket_ts(
                    msg.get("candle_start_time") or msg.get("timestamp"),
                    tf_sec,
                )
                candle = {
                    "symbol": sym,
                    "open": msg.get("open"),
                    "high": msg.get("high"),
                    "low": msg.get("low"),
                    "close": msg.get("close"),
                    "volume": msg.get("volume"),
                    "timestamp": msg.get("candle_start_time") or msg.get("timestamp"),
                    "bucket_ts": bucket_ts,
                    "resolution": resolution,
                }
                with self._lock:
                    by_res = self._last_candle.setdefault(sym, {})
                    by_res[resolution] = candle
                    if bucket_ts is not None:
                        sym_buckets = self._candles_by_bucket.setdefault(sym, {})
                        res_buckets = sym_buckets.setdefault(resolution, {})
                        res_buckets[int(bucket_ts)] = dict(candle)
                        if len(res_buckets) > 30:
                            for old_key in sorted(res_buckets.keys())[:-30]:
                                res_buckets.pop(old_key, None)
                if self.on_candle:
                    try:
                        self.on_candle(sym, dict(candle))
                    except Exception as e:
                        logger.debug("Delta WS on_candle callback error: %s", e)
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
            try:
                self._apply_orders_ws_message(msg)
            except Exception as e:
                logger.debug("Delta WS orders apply failed: %s", e)
            if self.on_message:
                self.on_message(msg)
            return

        if msg_type == "positions":
            try:
                self._apply_positions_ws_message(msg)
            except Exception as e:
                logger.debug("Delta WS positions apply failed: %s", e)
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
            if msg_type in ("v2/user_trades", "user_trades"):
                result = msg.get("result")
                entries: List[Dict[str, Any]] = []
                if isinstance(result, list):
                    entries = [e for e in result if isinstance(e, dict)]
                elif isinstance(result, dict):
                    entries = [result]
                elif isinstance(msg, dict):
                    # Some payloads may arrive as a flat trade event.
                    entries = [msg]
                if entries:
                    with self._lock:
                        for e in entries:
                            rec = dict(e)
                            rec.setdefault("_ws_msg_type", msg_type)
                            rec.setdefault("_ws_action", msg.get("action"))
                            self._user_trades.append(rec)
                            if self.on_user_trade:
                                try:
                                    self.on_user_trade(rec)
                                except Exception as cb_err:
                                    logger.debug("Delta WS on_user_trade callback error: %s", cb_err)
                        if len(self._user_trades) > 2000:
                            self._user_trades = self._user_trades[-2000:]
            if self.on_message:
                self.on_message(msg)
            return

        if self.on_message:
            self.on_message(msg)

    def _on_open(self, _ws) -> None:
        self._connect_failures = 0  # reset on successful connect
        self._reset_private_ws_state()
        with self._lock:
            self._connect_generation += 1
        logger.info("Delta WebSocket connected to %s", self.ws_url)
        if self.on_open_cb:
            try:
                self.on_open_cb()
            except Exception as e:
                logger.debug("Delta WS on_open callback error: %s", e)
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
        if self._reconnecting:
            return
        self._reconnecting = True
        if self._heartbeat_timer:
            self._heartbeat_timer.cancel()
            self._heartbeat_timer = None
        try:
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
        finally:
            self._reconnecting = False

    def request_reconnect(self, reason: str = "manual") -> None:
        """Public reconnect trigger used by feed watchdog/recovery logic."""
        if self._stop.is_set() or self._gave_up:
            return
        logger.info("Delta WebSocket reconnect requested: %s", reason)
        self._reconnect()

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

    def get_last_candle(
        self, symbol: str, resolution: Optional[str] = None
    ) -> Optional[Dict]:
        with self._lock:
            by_res = self._last_candle.get(symbol) or {}
            if resolution:
                return by_res.get(str(resolution).strip().lower())
            if not by_res:
                return None
            # Most recently updated resolution (any one is fine for legacy callers).
            return next(iter(by_res.values()))

    def get_candle_for_bucket(
        self, symbol: str, bucket_ts: int, resolution: str
    ) -> Optional[Dict]:
        res = str(resolution or "").strip().lower()
        if not res:
            return None
        with self._lock:
            res_buckets = (self._candles_by_bucket.get(symbol) or {}).get(res) or {}
            out = res_buckets.get(int(bucket_ts))
            if out is not None:
                return dict(out)
            last = (self._last_candle.get(symbol) or {}).get(res)
            if last and int(last.get("bucket_ts") or 0) == int(bucket_ts):
                return dict(last)
            return None

    def get_last_l2_orderbook(self, symbol: str) -> Optional[Dict]:
        with self._lock:
            if not symbol:
                return None
            s = str(symbol).strip()
            su = s.upper()
            return (
                self._last_l2.get(s)
                or self._last_orderbook_l2.get(s)
                or self._last_l2.get(su)
                or self._last_orderbook_l2.get(su)
            )

    @property
    def connect_generation(self) -> int:
        with self._lock:
            return int(self._connect_generation)

    def ws_open_orders_ready(self) -> bool:
        with self._lock:
            return bool(self._orders_ws_snapshot_ready)

    def ws_positions_ready(self) -> bool:
        with self._lock:
            return bool(self._positions_ws_snapshot_ready)

    def get_open_orders_ws(
        self, symbol: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        sym_filter = str(symbol or "").strip().upper()
        with self._lock:
            orders = list(self._orders_by_id.values())
        if not sym_filter:
            return orders
        out: List[Dict[str, Any]] = []
        for o in orders:
            sym = str(o.get("symbol") or "").strip().upper()
            if sym == sym_filter:
                out.append(o)
        return out

    def get_positions_rows_ws(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._positions_by_key.values())

    def get_orders(self, symbol: str) -> List[Dict[str, Any]]:
        return self.get_open_orders_ws(symbol=symbol)

    def get_positions(self) -> Dict[str, Dict[str, Any]]:
        rows = self.get_positions_rows_ws()
        out: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            sym = str(row.get("tradingSymbol") or "").strip()
            if sym:
                out[sym] = dict(row)
        return out

    def pop_user_trades(self, limit: int = 200) -> List[Dict]:
        """Drain up to ``limit`` recent private user-trade events."""
        if limit <= 0:
            return []
        with self._lock:
            n = min(int(limit), len(self._user_trades))
            if n <= 0:
                return []
            out = self._user_trades[:n]
            self._user_trades = self._user_trades[n:]
            return out

    def is_connected(self) -> bool:
        return (
            self._ws is not None
            and self._ws.sock is not None
            and getattr(self._ws.sock, "connected", False)
        )

    def is_authenticated(self) -> bool:
        return self._authenticated
