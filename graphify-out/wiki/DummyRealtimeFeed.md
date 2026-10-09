# DummyRealtimeFeed

> 15 nodes

## Key Concepts

- **DummyRealtimeFeed** (16 connections) — `core/data/feeds/dummy_feed.py`
- **.get_simulated_datetime_ist()** (4 connections) — `core/data/feeds/dummy_feed.py`
- **.get_last_candle()** (3 connections) — `core/data/feeds/dummy_feed.py`
- **.get_last_ticker()** (3 connections) — `core/data/feeds/dummy_feed.py`
- **Any** (3 connections)
- **datetime** (3 connections)
- **.__init__()** (2 connections) — `core/data/feeds/dummy_feed.py`
- **._next_price()** (2 connections) — `core/data/feeds/dummy_feed.py`
- **._run()** (2 connections) — `core/data/feeds/dummy_feed.py`
- **.set_tick_queue()** (2 connections) — `core/data/feeds/dummy_feed.py`
- **.is_connected()** (1 connections) — `core/data/feeds/dummy_feed.py`
- **.start()** (1 connections) — `core/data/feeds/dummy_feed.py`
- **.stop()** (1 connections) — `core/data/feeds/dummy_feed.py`
- **Current simulated wall time in IST when ``start_datetime`` was set.** (1 connections) — `core/data/feeds/dummy_feed.py`
- **Deterministic synthetic feed that emits normalized ticks: {"symbol", "price",…** (1 connections) — `core/data/feeds/dummy_feed.py`

## Relationships

- [logging.py](logging.py.md) (4 shared connections)
- [dummy_live.py](dummy_live.py.md) (2 shared connections)
- [.start](start.md) (1 shared connections)

## Source Files

- `core/data/feeds/dummy_feed.py`

## Audit Trail

- EXTRACTED: 25 (96%)
- INFERRED: 1 (4%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*