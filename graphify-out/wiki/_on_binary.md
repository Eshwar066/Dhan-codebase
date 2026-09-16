# ._on_binary

> 20 nodes

## Key Concepts

- **._on_binary()** (12 connections) — `core/library/dhan_websocket.py`
- **WebSocketApp** (6 connections)
- **._on_message()** (4 connections) — `core/library/dhan_websocket.py`
- **._on_open()** (4 connections) — `core/library/dhan_websocket.py`
- **._touch_activity()** (4 connections) — `core/library/dhan_websocket.py`
- **_parse_full_packet()** (4 connections) — `core/library/dhan_websocket.py`
- **_parse_oi_packet()** (4 connections) — `core/library/dhan_websocket.py`
- **_parse_prev_close_packet()** (4 connections) — `core/library/dhan_websocket.py`
- **_parse_quote_packet()** (4 connections) — `core/library/dhan_websocket.py`
- **_parse_ticker_packet()** (4 connections) — `core/library/dhan_websocket.py`
- **_parse_disconnect_packet()** (3 connections) — `core/library/dhan_websocket.py`
- **_parse_header()** (3 connections) — `core/library/dhan_websocket.py`
- **._touch_market_tick()** (2 connections) — `core/library/dhan_websocket.py`
- **Packet code 5: OI int32.** (1 connections) — `core/library/dhan_websocket.py`
- **Packet code 6: prev close float32, OI int32.** (1 connections) — `core/library/dhan_websocket.py`
- **Packet code 8: LTP, LTQ, LTT, ATP, Vol, Sell, Buy, OI, OI high, OI low, Open,…** (1 connections) — `core/library/dhan_websocket.py`
- **Packet code 50: int16 disconnection reason.** (1 connections) — `core/library/dhan_websocket.py`
- **Parse 8-byte header: (response_code, msg_len, exchange_segment_byte,…** (1 connections) — `core/library/dhan_websocket.py`
- **Packet code 2: LTP (float32), LTT (int32).** (1 connections) — `core/library/dhan_websocket.py`
- **Packet code 4: LTP, LTQ int16, LTT, ATP, Vol, Sell, Buy, Open, Close, High, Low…** (1 connections) — `core/library/dhan_websocket.py`

## Relationships

- [DhanWebSocket](DhanWebSocket.md) (14 shared connections)
- [logging.py](logging.py.md) (7 shared connections)

## Source Files

- `core/library/dhan_websocket.py`

## Audit Trail

- EXTRACTED: 43 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*