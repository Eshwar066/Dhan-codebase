# DhanDepthFeed

> 22 nodes

## Key Concepts

- **DhanDepthFeed** (20 connections) — `core/data/feeds/dhan_depth_feed.py`
- **.get_market_depth()** (6 connections) — `core/data/feeds/dhan_depth_feed.py`
- **.get_last_ticker()** (5 connections) — `core/data/feeds/dhan_depth_feed.py`
- **Any** (5 connections)
- **.get_last_candle()** (4 connections) — `core/data/feeds/dhan_depth_feed.py`
- **.get_best_ask()** (2 connections) — `core/data/feeds/dhan_depth_feed.py`
- **.get_best_bid()** (2 connections) — `core/data/feeds/dhan_depth_feed.py`
- **.get_orders()** (2 connections) — `core/data/feeds/dhan_depth_feed.py`
- **.get_positions()** (2 connections) — `core/data/feeds/dhan_depth_feed.py`
- **.__init__()** (2 connections) — `core/data/feeds/dhan_depth_feed.py`
- **.start()** (2 connections) — `core/data/feeds/dhan_depth_feed.py`
- **.connect_generation()** (1 connections) — `core/data/feeds/dhan_depth_feed.py`
- **.is_connected()** (1 connections) — `core/data/feeds/dhan_depth_feed.py`
- **.is_warm()** (1 connections) — `core/data/feeds/dhan_depth_feed.py`
- **.replace_instruments()** (1 connections) — `core/data/feeds/dhan_depth_feed.py`
- **.stop()** (1 connections) — `core/data/feeds/dhan_depth_feed.py`
- **.subscribe_generation()** (1 connections) — `core/data/feeds/dhan_depth_feed.py`
- **Return latest market depth for symbol: {symbol, bids: [{price, quantity,…** (1 connections) — `core/data/feeds/dhan_depth_feed.py`
- **Derive LTP from best bid/ask mid or last available level.** (1 connections) — `core/data/feeds/dhan_depth_feed.py`
- **Depth feed does not provide OHLC; return None or best-effort from depth.** (1 connections) — `core/data/feeds/dhan_depth_feed.py`
- **Real-time Full Market Depth feed for Dhan (20 or 200 level). Use…** (1 connections) — `core/data/feeds/dhan_depth_feed.py`
- **instruments: list of {"ExchangeSegment": "NSE_EQ", "SecurityId": "11536",…** (1 connections) — `core/data/feeds/dhan_depth_feed.py`

## Relationships

- [logging.py](logging.py.md) (3 shared connections)
- [DhanDepthWebSocket](DhanDepthWebSocket.md) (2 shared connections)

## Source Files

- `core/data/feeds/dhan_depth_feed.py`

## Audit Trail

- EXTRACTED: 33 (97%)
- INFERRED: 1 (3%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*