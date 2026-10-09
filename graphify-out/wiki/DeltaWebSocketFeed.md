# DeltaWebSocketFeed

> 41 nodes

## Key Concepts

- **DeltaWebSocketFeed** (40 connections) — `core/data/feeds/delta_feed.py`
- **Any** (16 connections)
- **.ensure_l2_orderbook_subscription()** (5 connections) — `core/data/feeds/delta_feed.py`
- **._candlestick_channels()** (4 connections) — `core/data/feeds/delta_feed.py`
- **.get_last_l2_orderbook()** (4 connections) — `core/data/feeds/delta_feed.py`
- **._do_subscribe_private()** (3 connections) — `core/data/feeds/delta_feed.py`
- **._do_subscribe_public()** (3 connections) — `core/data/feeds/delta_feed.py`
- **.get_best_ask()** (3 connections) — `core/data/feeds/delta_feed.py`
- **.get_best_bid()** (3 connections) — `core/data/feeds/delta_feed.py`
- **.get_open_orders_ws()** (3 connections) — `core/data/feeds/delta_feed.py`
- **.get_orders()** (3 connections) — `core/data/feeds/delta_feed.py`
- **.get_positions_for_recon()** (3 connections) — `core/data/feeds/delta_feed.py`
- **.get_recent_user_trades()** (3 connections) — `core/data/feeds/delta_feed.py`
- **.set_candle_queue()** (3 connections) — `core/data/feeds/delta_feed.py`
- **.set_tick_queue()** (3 connections) — `core/data/feeds/delta_feed.py`
- **.set_user_trade_callback()** (3 connections) — `core/data/feeds/delta_feed.py`
- **_subscribe_after_ready()** (3 connections) — `core/data/feeds/delta_feed.py`
- **._channel_candlestick()** (2 connections) — `core/data/feeds/delta_feed.py`
- **._forward_user_trade()** (2 connections) — `core/data/feeds/delta_feed.py`
- **.get_last_ticker()** (2 connections) — `core/data/feeds/delta_feed.py`
- **.get_positions()** (2 connections) — `core/data/feeds/delta_feed.py`
- **._on_auth()** (2 connections) — `core/data/feeds/delta_feed.py`
- **._push_candle()** (2 connections) — `core/data/feeds/delta_feed.py`
- **_on_open()** (2 connections) — `core/data/feeds/delta_feed.py`
- **.is_connected()** (1 connections) — `core/data/feeds/delta_feed.py`
- *... and 16 more nodes in this community*

## Relationships

- [delta_candlestick.py](delta_candlestick.py.md) (8 shared connections)
- [logging.py](logging.py.md) (3 shared connections)
- [.start](start.md) (2 shared connections)
- [.create_live_engine](create_live_engine.md) (1 shared connections)
- [factory.py](factory.py.md) (1 shared connections)
- [Runtime notes](Runtime_notes.md) (1 shared connections)
- [._run_watches](_run_watches.md) (1 shared connections)
- [DeltaWebSocket](DeltaWebSocket.md) (1 shared connections)

## Source Files

- `core/data/feeds/delta_feed.py`

## Audit Trail

- EXTRACTED: 72 (94%)
- INFERRED: 5 (6%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*