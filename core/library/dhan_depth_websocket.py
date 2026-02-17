"""
Dhan Full Market Depth WebSocket client.

- 20 Level: wss://depth-api-feed.dhan.co/twentydepth (up to 50 instruments per connection).
- 200 Level: wss://full-depth-api.dhan.co/twohundreddepth (1 instrument per connection).
- Subscribe: JSON RequestCode 23; 20 level uses InstrumentList; 200 level uses single ExchangeSegment + SecurityId.
- Response: binary. Header 12 bytes (msg_len, response_code, segment, security_id, sequence); then N×16 bytes
  (float64 price, uint32 quantity, uint32 num_orders). Response code 41 = Bid, 51 = Ask.
- Keep alive: server pings every 10s; no response 40s -> server closes. Disconnect: JSON {"RequestCode": 12}.
"""

import json
import logging
import struct
import threading
import time
import urllib.parse
from typing import Any, Callable, Dict, List, Optional, Tuple

import websocket

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

        self._ws: Optional[websocket.WebSocketApp] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._security_to_symbol: Dict[int, str] = {}
        for inv in self.instruments:
            sid = inv.get("SecurityId")
            sym = inv.get("symbol") or inv.get("SecurityId")
            if sid is not None:
                try:
                    self._security_to_symbol[int(sid)] = str(sym)
                except (TypeError, ValueError):
                    self._security_to_symbol[int(sid)] = str(sid)

        # symbol -> {"bids": [...], "asks": [...], "exchange_segment", "security_id"}
        self._last_depth: Dict[str, Dict[str, Any]] = {}
        self._packet_size = HEADER_BYTES + (self.level * DEPTH_ROW_BYTES)

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
        for i in range(0, len(self.instruments), MAX_INSTRUMENTS_20_LEVEL):
            batch = self.instruments[i : i + MAX_INSTRUMENTS_20_LEVEL]
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

    def _subscribe_200(self) -> None:
        if not self.instruments:
            return
        item = self.instruments[0]
        msg = {
            "RequestCode": REQUEST_DEPTH_SUBSCRIBE,
            "ExchangeSegment": item["ExchangeSegment"],
            "SecurityId": str(item["SecurityId"]),
        }
        self._send_json(msg)
        logger.debug("Dhan Depth WS subscribe 200-level single instrument")

    def _subscribe_all(self) -> None:
        if self.level == 20:
            self._subscribe_20()
        else:
            self._subscribe_200()

    def _on_binary(self, ws: websocket.WebSocketApp, data: bytes) -> None:
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

    def _on_open(self, ws: websocket.WebSocketApp) -> None:
        logger.info("Dhan Depth WebSocket connected (level=%s)", self.level)
        time.sleep(0.5)
        self._subscribe_all()

    def _on_error(self, ws: websocket.WebSocketApp, error: Exception) -> None:
        logger.warning("Dhan Depth WebSocket error: %s", error)

    def _on_close(self, ws: websocket.WebSocketApp, close_status_code: Optional[int], close_msg: Optional[str]) -> None:
        logger.info("Dhan Depth WebSocket closed: %s %s", close_status_code, close_msg)

    def connect(self) -> None:
        url = self._build_url()
        self._ws = websocket.WebSocketApp(
            url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_forever, daemon=True)
        self._thread.start()
        time.sleep(2)

    def _run_forever(self) -> None:
        if self._ws:
            try:
                self._ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e:
                logger.warning("Dhan Depth WebSocket run_forever: %s", e)

    def disconnect(self) -> None:
        self._stop.set()
        self._send_json({"RequestCode": REQUEST_DISCONNECT})
        if self._ws:
            self._ws.close()
            self._ws = None

    def is_connected(self) -> bool:
        return self._ws is not None and self._ws.sock is not None and self._ws.sock.connected

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
