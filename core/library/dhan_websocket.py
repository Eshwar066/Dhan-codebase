"""
Dhan Live Market Feed WebSocket client.

- Connect: wss://api-feed.dhan.co?version=2&token=...&clientId=...&authType=2
- Subscribe: JSON RequestCode 15, InstrumentList (ExchangeSegment, SecurityId); max 100 per message, 5000 per connection.
- Responses: binary Little Endian. Header 8 bytes (response_code, msg_len, exchange_segment, security_id); payload by code.
- Keep alive: server pings every 10s; client pong (handled by library). No response 40s -> server closes.
- Disconnect: JSON {"RequestCode": 12}
- Reconnect: on drop, background loop recreates the socket with the same URL and calls
  subscribe again from on_open (same pattern as Delta WS recovery).
"""

import json
import logging
import struct
import threading
import time
import urllib.parse
from typing import Any, Callable, Dict, List, Optional

import websocket

from core.library.dhan_ws_common import StallWatchdog, reconnect_sleep_with_jitter

logger = logging.getLogger(__name__)

DHAN_FEED_WS_URL = "wss://api-feed.dhan.co"

# Response codes (Annexure)
FEED_RESPONSE_TICKER = 2
FEED_RESPONSE_QUOTE = 4
FEED_RESPONSE_OI = 5
FEED_RESPONSE_PREV_CLOSE = 6
FEED_RESPONSE_FULL = 8
FEED_RESPONSE_DISCONNECT = 50

# Request codes
REQUEST_SUBSCRIBE = 15
REQUEST_DISCONNECT = 12

MAX_INSTRUMENTS_PER_MESSAGE = 100


def _parse_header(data: bytes) -> tuple:
    """Parse 8-byte header: (response_code, msg_len, exchange_segment_byte, security_id). Little Endian."""
    if len(data) < 8:
        return (0, 0, 0, 0)
    response_code = data[0]
    msg_len = struct.unpack_from("<H", data, 1)[0]  # int16
    exchange_segment = data[3]
    security_id = struct.unpack_from("<I", data, 4)[0]  # int32
    return (response_code, msg_len, exchange_segment, security_id)


def _parse_ticker_packet(data: bytes) -> Optional[Dict[str, Any]]:
    """Packet code 2: LTP (float32), LTT (int32)."""
    if len(data) < 8 + 8:
        return None
    ltp = struct.unpack_from("<f", data, 8)[0]
    ltt = struct.unpack_from("<i", data, 12)[0]
    return {"last_price": ltp, "last_trade_time": ltt}


def _parse_quote_packet(data: bytes) -> Optional[Dict[str, Any]]:
    """Packet code 4: LTP, LTQ int16, LTT, ATP, Vol, Sell, Buy, Open, Close, High, Low (all float32 except LTQ)."""
    if len(data) < 8 + 38:  # 8 header + 4+2+4+4+4+4+4+4+4+4+4+4
        return None
    o = 8
    ltp = struct.unpack_from("<f", data, o)[0]
    o += 4
    ltq = struct.unpack_from("<h", data, o)[0]
    o += 2
    ltt = struct.unpack_from("<i", data, o)[0]
    o += 4
    atp = struct.unpack_from("<f", data, o)[0]
    o += 4
    volume = struct.unpack_from("<i", data, o)[0]
    o += 4
    sell_qty = struct.unpack_from("<i", data, o)[0]
    o += 4
    buy_qty = struct.unpack_from("<i", data, o)[0]
    o += 4
    day_open = struct.unpack_from("<f", data, o)[0]
    o += 4
    day_close = struct.unpack_from("<f", data, o)[0]
    o += 4
    day_high = struct.unpack_from("<f", data, o)[0]
    o += 4
    day_low = struct.unpack_from("<f", data, o)[0]
    return {
        "last_price": ltp,
        "last_traded_quantity": ltq,
        "last_trade_time": ltt,
        "average_price": atp,
        "volume": volume,
        "sell_quantity": sell_qty,
        "buy_quantity": buy_qty,
        "open": day_open,
        "close": day_close,
        "high": day_high,
        "low": day_low,
    }


def _parse_oi_packet(data: bytes) -> Optional[Dict[str, Any]]:
    """Packet code 5: OI int32."""
    if len(data) < 8 + 4:
        return None
    oi = struct.unpack_from("<i", data, 8)[0]
    return {"oi": oi}


def _parse_prev_close_packet(data: bytes) -> Optional[Dict[str, Any]]:
    """Packet code 6: prev close float32, OI int32."""
    if len(data) < 8 + 8:
        return None
    prev_close = struct.unpack_from("<f", data, 8)[0]
    oi = struct.unpack_from("<i", data, 12)[0]
    return {"prev_close": prev_close, "oi": oi}


def _parse_full_packet(data: bytes) -> Optional[Dict[str, Any]]:
    """Packet code 8: LTP, LTQ, LTT, ATP, Vol, Sell, Buy, OI, OI high, OI low, Open, Close, High, Low, then 5*20 depth."""
    if len(data) < 8 + 56:  # up to day_low
        return None
    o = 8
    ltp = struct.unpack_from("<f", data, o)[0]
    o += 4
    ltq = struct.unpack_from("<h", data, o)[0]
    o += 2
    ltt = struct.unpack_from("<i", data, o)[0]
    o += 4
    atp = struct.unpack_from("<f", data, o)[0]
    o += 4
    volume = struct.unpack_from("<i", data, o)[0]
    o += 4
    sell_qty = struct.unpack_from("<i", data, o)[0]
    o += 4
    buy_qty = struct.unpack_from("<i", data, o)[0]
    o += 4
    oi = struct.unpack_from("<i", data, o)[0]
    o += 4
    oi_high = struct.unpack_from("<i", data, o)[0]
    o += 4
    oi_low = struct.unpack_from("<i", data, o)[0]
    o += 4
    day_open = struct.unpack_from("<f", data, o)[0]
    o += 4
    day_close = struct.unpack_from("<f", data, o)[0]
    o += 4
    day_high = struct.unpack_from("<f", data, o)[0]
    o += 4
    day_low = struct.unpack_from("<f", data, o)[0]
    o += 4
    out = {
        "last_price": ltp,
        "last_traded_quantity": ltq,
        "last_trade_time": ltt,
        "average_price": atp,
        "volume": volume,
        "sell_quantity": sell_qty,
        "buy_quantity": buy_qty,
        "oi": oi,
        "oi_day_high": oi_high,
        "oi_day_low": oi_low,
        "open": day_open,
        "close": day_close,
        "high": day_high,
        "low": day_low,
    }
    # Optional: parse 5 * 20 bytes market depth (bid_qty, ask_qty, bid_orders, ask_orders, bid_price, ask_price)
    depth = []
    if len(data) >= o + 100:
        for _ in range(5):
            if len(data) < o + 20:
                break
            bq = struct.unpack_from("<i", data, o)[0]
            o += 4
            aq = struct.unpack_from("<i", data, o)[0]
            o += 4
            bo = struct.unpack_from("<h", data, o)[0]
            o += 2
            ao = struct.unpack_from("<h", data, o)[0]
            o += 2
            bp = struct.unpack_from("<f", data, o)[0]
            o += 4
            ap = struct.unpack_from("<f", data, o)[0]
            o += 4
            depth.append({"bid_quantity": bq, "ask_quantity": aq, "bid_orders": bo, "ask_orders": ao, "bid_price": bp, "ask_price": ap})
    if depth:
        out["depth"] = depth
    return out


def _parse_disconnect_packet(data: bytes) -> Optional[int]:
    """Packet code 50: int16 disconnection reason."""
    if len(data) < 8 + 2:
        return None
    return struct.unpack_from("<h", data, 8)[0]


class DhanWebSocket:
    """
    Dhan Live Market Feed WebSocket. Connect, subscribe with InstrumentList (max 100 per message),
    receive binary packets, parse and expose last ticker/quote per security.
    """

    def __init__(
        self,
        access_token: str,
        client_id: str,
        instruments: List[Dict[str, str]],
        on_ticker: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        on_quote: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        on_disconnect: Optional[Callable[[int], None]] = None,
        stall_timeout_seconds: float = 35.0,
    ):
        """
        instruments: list of {"ExchangeSegment": "NSE_EQ", "SecurityId": "11536", "symbol": "RELIANCE"}.
        SecurityId as string; symbol used for get_last_ticker(symbol).
        stall_timeout_seconds: if >0, force-close socket when no inbound packets for this long (zombie detection).
        """
        self.access_token = access_token
        self.client_id = str(client_id)
        self.instruments = list(instruments)
        self.on_ticker = on_ticker
        self.on_quote = on_quote
        self.on_disconnect = on_disconnect
        self._stall_timeout_seconds = float(stall_timeout_seconds)

        self._ws: Optional[websocket.WebSocketApp] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        # security_id (int) -> symbol (str) for mapping parsed packets to symbol
        self._security_to_symbol: Dict[int, str] = {}
        self._rebuild_security_map_locked()

        self._last_ticker: Dict[str, Dict[str, Any]] = {}
        self._last_quote: Dict[str, Dict[str, Any]] = {}
        self._connect_generation = 0
        self._subscribe_generation = 0
        self._reconnect_backoff_sec = 2.0
        self._last_activity_ts = time.time()
        self._is_warm = False
        self._stall = StallWatchdog(
            name="DhanMarketWS",
            stall_sec=self._stall_timeout_seconds,
            get_last_activity_ts=lambda: self._last_activity_ts,
            get_ws=lambda: self._ws,
            should_run=lambda: not self._stop.is_set(),
        )

    def _rebuild_security_map_locked(self) -> None:
        self._security_to_symbol = {}
        for inv in self.instruments:
            sid = inv.get("SecurityId")
            sym = inv.get("symbol") or inv.get("SecurityId")
            if sid is not None:
                try:
                    self._security_to_symbol[int(sid)] = str(sym)
                except (TypeError, ValueError):
                    self._security_to_symbol[int(sid)] = str(sid)

    def replace_instruments(self, instruments: List[Dict[str, str]]) -> None:
        """Thread-safe: update subscription list; applied on next reconnect or call connect after disconnect."""
        with self._lock:
            self.instruments = list(instruments)
            self._rebuild_security_map_locked()

    def _touch_activity(self) -> None:
        self._last_activity_ts = time.time()

    def _build_url(self) -> str:
        q = urllib.parse.urlencode({
            "version": "2",
            "token": self.access_token,
            "clientId": self.client_id,
            "authType": "2",
        })
        return f"{DHAN_FEED_WS_URL}?{q}"

    def _send_json(self, payload: dict) -> None:
        if self._ws and self._ws.sock and self._ws.sock.connected:
            self._ws.send(json.dumps(payload))

    def _subscribe_batch(self, batch: List[Dict[str, str]]) -> None:
        msg = {
            "RequestCode": REQUEST_SUBSCRIBE,
            "InstrumentCount": len(batch),
            "InstrumentList": [
                {"ExchangeSegment": item["ExchangeSegment"], "SecurityId": str(item["SecurityId"])}
                for item in batch
            ],
        }
        self._send_json(msg)
        logger.debug("Dhan WS subscribe batch size %s", len(batch))

    def _make_ws_app(self) -> websocket.WebSocketApp:
        return websocket.WebSocketApp(
            self._build_url(),
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )

    def _subscribe_all(self) -> None:
        with self._lock:
            inst = list(self.instruments)
            self._subscribe_generation += 1
            sub_gen = self._subscribe_generation
        for i in range(0, len(inst), MAX_INSTRUMENTS_PER_MESSAGE):
            batch = inst[i : i + MAX_INSTRUMENTS_PER_MESSAGE]
            self._subscribe_batch(batch)
            time.sleep(0.2)
        logger.info(
            "Dhan market WS subscribed (subscribe_generation=%s, instruments=%s)",
            sub_gen,
            len(inst),
        )

    def _on_binary(self, ws: websocket.WebSocketApp, data: bytes) -> None:
        self._touch_activity()
        self._is_warm = True
        if len(data) < 8:
            return
        code, msg_len, _seg, security_id = _parse_header(data)
        symbol = self._security_to_symbol.get(security_id, str(security_id))

        if code == FEED_RESPONSE_TICKER:
            parsed = _parse_ticker_packet(data)
            if parsed:
                with self._lock:
                    self._last_ticker[symbol] = {**parsed, "symbol": symbol}
                if self.on_ticker:
                    self.on_ticker(symbol, parsed)
        elif code == FEED_RESPONSE_QUOTE:
            parsed = _parse_quote_packet(data)
            if parsed:
                with self._lock:
                    self._last_quote[symbol] = {**parsed, "symbol": symbol}
                    self._last_ticker[symbol] = {"last_price": parsed["last_price"], "last_trade_time": parsed.get("last_trade_time"), "symbol": symbol}
                if self.on_quote:
                    self.on_quote(symbol, parsed)
        elif code == FEED_RESPONSE_FULL:
            parsed = _parse_full_packet(data)
            if parsed:
                with self._lock:
                    self._last_quote[symbol] = {**parsed, "symbol": symbol}
                    self._last_ticker[symbol] = {"last_price": parsed["last_price"], "last_trade_time": parsed.get("last_trade_time"), "symbol": symbol}
                if self.on_quote:
                    self.on_quote(symbol, parsed)
        elif code == FEED_RESPONSE_OI:
            parsed = _parse_oi_packet(data)
            if parsed:
                with self._lock:
                    if symbol in self._last_quote:
                        self._last_quote[symbol] = {**self._last_quote[symbol], **parsed}
        elif code == FEED_RESPONSE_PREV_CLOSE:
            parsed = _parse_prev_close_packet(data)
            if parsed:
                with self._lock:
                    if symbol in self._last_ticker:
                        self._last_ticker[symbol]["prev_close"] = parsed.get("prev_close")
        elif code == FEED_RESPONSE_DISCONNECT:
            reason = _parse_disconnect_packet(data)
            logger.warning("Dhan WS disconnection packet reason=%s", reason)
            if self.on_disconnect:
                self.on_disconnect(reason or 0)

    def _on_message(self, ws: websocket.WebSocketApp, message) -> None:
        if isinstance(message, bytes):
            self._on_binary(ws, message)
        # else text (e.g. JSON) – ignore or log

    def _on_open(self, ws: websocket.WebSocketApp) -> None:
        with self._lock:
            self._connect_generation += 1
            gen = self._connect_generation
        self._reconnect_backoff_sec = 2.0
        self._is_warm = False
        self._touch_activity()
        logger.info(
            "Dhan market WebSocket connected (generation=%s); subscribing instruments",
            gen,
        )
        time.sleep(0.5)
        self._subscribe_all()

    def _on_error(self, ws: websocket.WebSocketApp, error: Exception) -> None:
        logger.warning("Dhan WebSocket error: %s", error)

    def _on_close(self, ws: websocket.WebSocketApp, close_status_code: Optional[int], close_msg: Optional[str]) -> None:
        logger.info(
            "Dhan market WebSocket closed: code=%s msg=%s",
            close_status_code,
            close_msg,
        )

    def connect(self) -> None:
        """Start background thread; reconnects with fresh socket and re-subscribes after each drop."""
        self._stop.clear()
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._thread_main, daemon=True)
        self._thread.start()
        self._stall.start()
        time.sleep(0.5)

    def _thread_main(self) -> None:
        try:
            self._run_forever()
        finally:
            with self._lock:
                self._thread = None

    def _run_forever(self) -> None:
        while not self._stop.is_set():
            self._ws = self._make_ws_app()
            try:
                self._ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e:
                if not self._stop.is_set():
                    logger.warning("Dhan market WebSocket run_forever: %s", e)
            if self._stop.is_set():
                break
            logger.info("Dhan market WebSocket scheduling reconnect (jittered backoff)")
            self._reconnect_backoff_sec = reconnect_sleep_with_jitter(self._reconnect_backoff_sec)

    def disconnect(self) -> None:
        self._stop.set()
        self._stall.stop()
        try:
            self._send_json({"RequestCode": REQUEST_DISCONNECT})
        except Exception:
            pass
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

    def is_connected(self) -> bool:
        return self._ws is not None and self._ws.sock is not None and self._ws.sock.connected

    @property
    def connect_generation(self) -> int:
        with self._lock:
            return int(self._connect_generation)

    @property
    def subscribe_generation(self) -> int:
        with self._lock:
            return int(self._subscribe_generation)

    @property
    def is_warm(self) -> bool:
        return bool(self._is_warm)

    def get_last_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._last_ticker.get(symbol)

    def get_last_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._last_quote.get(symbol)
