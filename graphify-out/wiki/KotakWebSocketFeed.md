# KotakWebSocketFeed

> 35 nodes

## Key Concepts

- **KotakWebSocketFeed** (16 connections) — `core/data/feeds/kotak_feed.py`
- **KotakOrderUpdateFeed** (14 connections) — `core/data/feeds/kotak_order_update_feed.py`
- **normalize_kotak_tick()** (9 connections) — `core/data/feeds/kotak_feed.py`
- **normalize_kotak_order_update()** (9 connections) — `core/data/feeds/kotak_order_update_feed.py`
- **Any** (7 connections)
- **_as_dict()** (5 connections) — `core/data/feeds/kotak_order_update_feed.py`
- **Any** (5 connections)
- **_as_dict()** (4 connections) — `core/data/feeds/kotak_feed.py`
- **._emit_tick()** (4 connections) — `core/data/feeds/kotak_feed.py`
- **._run_feed()** (4 connections) — `core/data/feeds/kotak_feed.py`
- **._on_message()** (4 connections) — `core/data/feeds/kotak_order_update_feed.py`
- **TestKotakFeedNormalize** (3 connections) — `core/broker/internal/kotak/test_kotak_mappings.py`
- **._build_ws_tokens()** (3 connections) — `core/data/feeds/kotak_feed.py`
- **.__init__()** (3 connections) — `core/data/feeds/kotak_feed.py`
- **._run_feed()** (3 connections) — `core/data/feeds/kotak_order_update_feed.py`
- **.test_normalize_order_fill()** (2 connections) — `core/broker/internal/kotak/test_kotak_mappings.py`
- **.test_normalize_tick()** (2 connections) — `core/broker/internal/kotak/test_kotak_mappings.py`
- **.get_last_ticker()** (2 connections) — `core/data/feeds/kotak_feed.py`
- **.set_tick_queue()** (2 connections) — `core/data/feeds/kotak_feed.py`
- **._thread_main()** (2 connections) — `core/data/feeds/kotak_feed.py`
- **.__init__()** (2 connections) — `core/data/feeds/kotak_order_update_feed.py`
- **.set_synthetic_trade_callback()** (2 connections) — `core/data/feeds/kotak_order_update_feed.py`
- **._thread_main()** (2 connections) — `core/data/feeds/kotak_order_update_feed.py`
- **.is_connected()** (1 connections) — `core/data/feeds/kotak_feed.py`
- **.start()** (1 connections) — `core/data/feeds/kotak_feed.py`
- *... and 10 more nodes in this community*

## Relationships

- [logging.py](logging.py.md) (9 shared connections)
- [KotakBroker](KotakBroker.md) (3 shared connections)
- [.create_live_engine](create_live_engine.md) (3 shared connections)
- [factory.py](factory.py.md) (2 shared connections)

## Source Files

- `core/broker/internal/kotak/test_kotak_mappings.py`
- `core/data/feeds/kotak_feed.py`
- `core/data/feeds/kotak_order_update_feed.py`

## Audit Trail

- EXTRACTED: 68 (99%)
- INFERRED: 1 (1%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*