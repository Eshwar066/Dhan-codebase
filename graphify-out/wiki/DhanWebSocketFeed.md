# DhanWebSocketFeed

> 26 nodes

## Key Concepts

- **DhanWebSocketFeed** (27 connections) — `core/data/feeds/dhan_feed.py`
- **Any** (8 connections)
- **._push_tick()** (5 connections) — `core/data/feeds/dhan_feed.py`
- **._normalized_tick_ts()** (4 connections) — `core/data/feeds/dhan_feed.py`
- **.__init__()** (3 connections) — `core/data/feeds/dhan_feed.py`
- **.set_tick_queue()** (3 connections) — `core/data/feeds/dhan_feed.py`
- **.start()** (3 connections) — `core/data/feeds/dhan_feed.py`
- **.get_best_ask()** (2 connections) — `core/data/feeds/dhan_feed.py`
- **.get_best_bid()** (2 connections) — `core/data/feeds/dhan_feed.py`
- **.get_last_candle()** (2 connections) — `core/data/feeds/dhan_feed.py`
- **.get_last_ticker()** (2 connections) — `core/data/feeds/dhan_feed.py`
- **.get_orders()** (2 connections) — `core/data/feeds/dhan_feed.py`
- **.get_positions()** (2 connections) — `core/data/feeds/dhan_feed.py`
- **.replace_instruments()** (2 connections) — `core/data/feeds/dhan_feed.py`
- **.connect_generation()** (1 connections) — `core/data/feeds/dhan_feed.py`
- **.is_connected()** (1 connections) — `core/data/feeds/dhan_feed.py`
- **.is_warm()** (1 connections) — `core/data/feeds/dhan_feed.py`
- **.last_market_tick_ts()** (1 connections) — `core/data/feeds/dhan_feed.py`
- **.stop()** (1 connections) — `core/data/feeds/dhan_feed.py`
- **.subscribe_generation()** (1 connections) — `core/data/feeds/dhan_feed.py`
- **Update subscription list thread-safely; next reconnect uses this list.** (1 connections) — `core/data/feeds/dhan_feed.py`
- **Best bid from last quote/full packet depth (only if symbol is subscribed).** (1 connections) — `core/data/feeds/dhan_feed.py`
- **Best ask from last quote/full packet depth (only if symbol is subscribed).** (1 connections) — `core/data/feeds/dhan_feed.py`
- **Real-time feed using Dhan Live Market Feed WebSocket. Subscribes to…** (1 connections) — `core/data/feeds/dhan_feed.py`
- **instruments: list of {"ExchangeSegment": "NSE_EQ", "SecurityId": "11536",…** (1 connections) — `core/data/feeds/dhan_feed.py`
- *... and 1 more nodes in this community*

## Relationships

- [logging.py](logging.py.md) (5 shared connections)
- [DhanWebSocket](DhanWebSocket.md) (2 shared connections)
- [.create_live_engine](create_live_engine.md) (1 shared connections)
- [factory.py](factory.py.md) (1 shared connections)
- [Runtime notes](Runtime_notes.md) (1 shared connections)
- [._run_watches](_run_watches.md) (1 shared connections)

## Source Files

- `core/data/feeds/dhan_feed.py`

## Audit Trail

- EXTRACTED: 42 (93%)
- INFERRED: 3 (7%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*