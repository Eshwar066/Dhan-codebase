# .__init__

> 10 nodes

## Key Concepts

- **.__init__()** (5 connections) — `core/library/dhan_depth_websocket.py`
- **.get_depth()** (4 connections) — `core/library/dhan_depth_websocket.py`
- **_parse_depth_rows()** (4 connections) — `core/library/dhan_depth_websocket.py`
- **._rebuild_security_map_locked()** (3 connections) — `core/library/dhan_depth_websocket.py`
- **.replace_instruments()** (3 connections) — `core/library/dhan_depth_websocket.py`
- **Any** (3 connections)
- **instruments: list of {"ExchangeSegment": "NSE_EQ", "SecurityId": "11536",…** (1 connections) — `core/library/dhan_depth_websocket.py`
- **Thread-safe: update instruments; applied on next reconnect.** (1 connections) — `core/library/dhan_depth_websocket.py`
- **Return latest depth for symbol: {bids: [{price, quantity, num_orders}, ...],…** (1 connections) — `core/library/dhan_depth_websocket.py`
- **Parse num_rows of 16 bytes each: price (float64), quantity (uint32), num_orders…** (1 connections) — `core/library/dhan_depth_websocket.py`

## Relationships

- [DhanDepthWebSocket](DhanDepthWebSocket.md) (6 shared connections)
- [StallWatchdog](StallWatchdog.md) (1 shared connections)
- [logging.py](logging.py.md) (1 shared connections)

## Source Files

- `core/library/dhan_depth_websocket.py`

## Audit Trail

- EXTRACTED: 17 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*