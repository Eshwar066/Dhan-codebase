"""
Dhan Full Market Depth WebSocket client.

- 20 Level: wss://depth-api-feed.dhan.co/twentydepth (up to 50 instruments per connection).
- 200 Level: wss://full-depth-api.dhan.co/twohundreddepth (1 instrument per connection).
- Subscribe: JSON RequestCode 23; 20 level uses InstrumentList; 200 level uses single ExchangeSegment + SecurityId.
- Response: binary. Header 12 bytes (msg_len, response_code, segment, security_id, sequence); then N×16 bytes
  (float64 price, uint32 quantity, uint32 num_orders). Response code 41 = Bid, 51 = Ask.
- Keep alive: server pings every 10s; no response 40s -> server closes. Disconnect: JSON {"RequestCode": 12}.
- Reconnect: background loop recreates socket; on_open re-subscribes (same pattern as Dhan market WS).
"""

import json
import logging
import struct
import threading
import time
import urllib.parse
from typing import Any, Callable, Dict, List, Optional, Tuple

import websocket

from core.library.dhan_ws_common import StallWatchdog, reconnect_sleep_with_jitter

logger = logging.getLogger(__name__)

# Endpoints
DHAN_DEPTH_20_URL = "wss://depth-api-feed.dhan.co/twentydepth"
DHAN_DEPTH_200_URL = "wss://full-depth-api.dhan.co/twohundreddepth"

REQUEST_DEPTH_SUBSCRIBE = 23
REQUEST_DISCONNECT = 12

FEED_RESPONSE_BID = 41
FEED_RESPONSE_ASK = 51
FEED_RESPONSE_DISCONNECT = 50

MAX_INSTRUMENTS_20_LEVEL = 50
DEPTH_LEVEL_20 = 20
DEPTH_LEVEL_200 = 200
DEPTH_ROW_BYTES = 16  # float64 (8) + uint32 (4) + uint32 (4)
HEADER_BYTES = 12


def _parse_depth_header(data: bytes, offset: int = 0) -> Tuple[int, int, int, int, int]:
    """
    Parse 12-byte header. Returns (msg_len, response_code, exchange_segment, security_id, sequence_or_rows).
    Little Endian.
    """
    if len(data) < offset + HEADER_BYTES:
        return (0, 0, 0, 0, 0)
    msg_len = struct.unpack_from("<H", data, offset)[0]
    response_code = data[offset + 2]
    exchange_segment = data[offset + 3]
    security_id = struct.unpack_from("<i", data, offset + 4)[0]
    sequence = struct.unpack_from("<I", data, offset + 8)[0]
    return (msg_len, response_code, exchange_segment, security_id, sequence)


def _parse_depth_rows(data: bytes, offset: int, num_rows: int) -> List[Dict[str, Any]]:
    """Parse num_rows of 16 bytes each: price (float64), quantity (uint32), num_orders (uint32)."""
    rows = []
    for i in range(num_rows):
        o = offset + i * DEPTH_ROW_BYTES
        if len(data) < o + DEPTH_ROW_BYTES:
            break
        price = struct.unpack_from("<d", data, o)[0]
        quantity = struct.unpack_from("<I", data, o + 8)[0]
        num_orders = struct.unpack_from("<I", data, o + 12)[0]
        rows.append({"price": price, "quantity": quantity, "num_orders": num_orders})
    return rows


def _parse_disconnect_packet(data: bytes, offset: int = 0) -> Optional[int]:
    """Packet code 50: int16 disconnection reason at offset 12."""
    if len(data) < offset + HEADER_BYTES + 2:
        return None
    return struct.unpack_from("<h", data, offset + HEADER_BYTES)[0]


class DhanDepthWebSocket:
    """
    Dhan Full Market Depth WebSocket. Supports 20 level (up to 50 instruments) or 200 level (1 instrument).
    NSE Equity and Derivatives only. Exposes get_depth(symbol) -> {"bids": [...], "asks": [...]}.
    """

    def __init__(
        self,
        access_token: str,
        client_id: str,
        instruments: List[Dict[str, str]],
        level: int = 20,
        on_depth: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        on_disconnect: Optional[Callable[[int], None]] = None,
        stall_timeout_seconds: float = 40.0,
    ):
        """
        instruments: list of {"ExchangeSegment": "NSE_EQ", "SecurityId": "11536", "symbol": "RELIANCE"}.
        level: 20 or 200. For 200, only first instrument is used (1 per connection).
        """
        if level not in (20, 200):
            raise ValueError("level must be 20 or 200")
        self.access_token = access_token
        self.client_id = str(client_id)
        self.level = level
        self.instruments = list(instruments) if level == 20 else (list(instruments)[:1] if instruments else [])
        self.on_depth = on_depth
        self.on_disconnect = on_disconnect
        self._stall_timeout_seconds = float(stall_timeout_seconds)

        self._ws: Optional[websocket.WebSocketApp] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._security_to_symbol: Dict[int, str] = {}
        self._rebuild_security_map_locked()

        # symbol -> {"bids": [...], "asks": [...], "exchange_segment", "security_id"}
        self._last_depth: Dict[str, Dict[str, Any]] = {}
        self._packet_size = HEADER_BYTES + (self.level * DEPTH_ROW_BYTES)
        self._connect_generation = 0
        self._subscribe_generation = 0
        self._reconnect_backoff_sec = 2.0
        self._last_activity_ts = time.time()
        self._is_warm = False
        self._stall = StallWatchdog(
            name="DhanDepthWS",
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
        """Thread-safe: update instruments; applied on next reconnect."""
        with self._lock:
            if self.level == 20:
                self.instruments = list(instruments)
            else:
                self.instruments = list(instruments)[:1] if instruments else []
            self._rebuild_security_map_locked()

    def _touch_activity(self) -> None:
        self._last_activity_ts = time.time()

    def _build_url(self) -> str:
        q = urllib.parse.urlencode({
            "token": self.access_token,
            "clientId": self.client_id,
            "authType": "2",
        })
        base = DHAN_DEPTH_20_URL if self.level == 20 else DHAN_DEPTH_200_URL
        return f"{base}?{q}"

    def _send_json(self, payload: dict) -> None:
        if self._ws and self._ws.sock and self._ws.sock.connected:
            self._ws.send(json.dumps(payload))

    def _subscribe_20(self) -> None:
        with self._lock:
            inst = list(self.instruments)
            self._subscribe_generation += 1
            sgen = self._subscribe_generation
        for i in range(0, len(inst), MAX_INSTRUMENTS_20_LEVEL):
            batch = inst[i : i + MAX_INSTRUMENTS_20_LEVEL]
            msg = {
                "RequestCode": REQUEST_DEPTH_SUBSCRIBE,
                "InstrumentCount": len(batch),
                "InstrumentList": [
                    {"ExchangeSegment": item["ExchangeSegment"], "SecurityId": str(item["SecurityId"])}
                    for item in batch
                ],
            }
            self._send_json(msg)
            logger.debug("Dhan Depth WS subscribe 20-level batch size %s", len(batch))
            time.sleep(0.2)
        logger.info(
            "Dhan Depth WS 20-level subscribed (subscribe_generation=%s, n=%s)",
            sgen,
            len(inst),
        )

    def _subscribe_200(self) -> None:
        with self._lock:
            if not self.instruments:
                return
            self._subscribe_generation += 1
            sgen = self._subscribe_generation
            item = self.instruments[0]
        msg = {
            "RequestCode": REQUEST_DEPTH_SUBSCRIBE,
            "ExchangeSegment": item["ExchangeSegment"],
            "SecurityId": str(item["SecurityId"]),
        }
        self._send_json(msg)
        logger.info(
            "Dhan Depth WS 200-level subscribed (subscribe_generation=%s)",
            sgen,
        )

    def _subscribe_all(self) -> None:
        if self.level == 20:
            self._subscribe_20()
        else:
            self._subscribe_200()

    def _on_binary(self, ws: websocket.WebSocketApp, data: bytes) -> None:
        self._touch_activity()
        self._is_warm = True
        offset = 0
        while offset + self._packet_size <= len(data):
            msg_len, response_code, _seg, security_id, _seq = _parse_depth_header(data, offset)
            symbol = self._security_to_symbol.get(security_id, str(security_id))

            if response_code == FEED_RESPONSE_DISCONNECT:
                reason = _parse_disconnect_packet(data, offset)
                logger.warning("Dhan Depth WS disconnection reason=%s", reason)
                if self.on_disconnect:
                    self.on_disconnect(reason or 0)
                offset += HEADER_BYTES + 2
                continue

            if response_code not in (FEED_RESPONSE_BID, FEED_RESPONSE_ASK):
                offset += HEADER_BYTES + (msg_len if msg_len > 0 else self.level * DEPTH_ROW_BYTES)
                continue

            payload_start = offset + HEADER_BYTES
            num_rows = min(self.level, msg_len // DEPTH_ROW_BYTES) if msg_len else self.level
            rows = _parse_depth_rows(data, payload_start, num_rows)

            with self._lock:
                if symbol not in self._last_depth:
                    self._last_depth[symbol] = {"bids": [], "asks": [], "exchange_segment": _seg, "security_id": security_id}
                if response_code == FEED_RESPONSE_BID:
                    self._last_depth[symbol]["bids"] = rows
                else:
                    self._last_depth[symbol]["asks"] = rows

            if self.on_depth:
                depth = self.get_depth(symbol)
                if depth:
                    self.on_depth(symbol, depth)

            offset += self._packet_size

        if offset < len(data) and offset + HEADER_BYTES <= len(data):
            msg_len, response_code, _seg, security_id, _seq = _parse_depth_header(data, offset)
            if response_code == FEED_RESPONSE_DISCONNECT:
                reason = _parse_disconnect_packet(data, offset)
                if self.on_disconnect:
                    self.on_disconnect(reason or 0)

    def _on_message(self, ws: websocket.WebSocketApp, message) -> None:
        if isinstance(message, bytes):
            self._on_binary(ws, message)

    def _make_ws_app(self) -> websocket.WebSocketApp:
        return websocket.WebSocketApp(
            self._build_url(),
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )

    def _on_open(self, ws: websocket.WebSocketApp) -> None:
        with self._lock:
            self._connect_generation += 1
            gen = self._connect_generation
        self._reconnect_backoff_sec = 2.0
        self._is_warm = False
        self._touch_activity()
        logger.info(
            "Dhan Depth WebSocket connected (level=%s, generation=%s)",
            self.level,
            gen,
        )
        time.sleep(0.5)
        self._subscribe_all()

    def _on_error(self, ws: websocket.WebSocketApp, error: Exception) -> None:
        logger.warning("Dhan Depth WebSocket error: %s", error)

    def _on_close(self, ws: websocket.WebSocketApp, close_status_code: Optional[int], close_msg: Optional[str]) -> None:
        logger.info("Dhan Depth WebSocket closed: %s %s", close_status_code, close_msg)

    def connect(self) -> None:
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
                    logger.warning("Dhan Depth WebSocket run_forever: %s", e)
            if self._stop.is_set():
                break
            logger.info("Dhan Depth WebSocket scheduling reconnect (jittered backoff)")
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

    def get_depth(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Return latest depth for symbol: {bids: [{price, quantity, num_orders}, ...], asks: [...]}."""
        with self._lock:
            raw = self._last_depth.get(symbol)
            if not raw:
                return None
            return {
                "symbol": symbol,
                "bids": list(raw.get("bids", [])),
                "asks": list(raw.get("asks", [])),
            }
