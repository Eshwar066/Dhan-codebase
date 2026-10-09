# delta_candlestick.py

> 20 nodes

## Key Concepts

- **delta_candlestick.py** (11 connections) — `core/data/feeds/delta_candlestick.py`
- **engine_timeframe_to_delta_resolution()** (10 connections) — `core/data/feeds/delta_candlestick.py`
- **._get_exchange_closed_candle()** (9 connections) — `core/engine/live_engine.py`
- **._reconcile_candle_with_exchange()** (8 connections) — `core/engine/live_engine.py`
- **resolutions_from_engine_timeframes()** (6 connections) — `core/data/feeds/delta_candlestick.py`
- **.get_exchange_candle_for_bucket()** (6 connections) — `core/data/feeds/delta_feed.py`
- **resolution_to_seconds()** (5 connections) — `core/data/feeds/delta_candlestick.py`
- **.is_exchange_candle_timeframe()** (5 connections) — `core/data/feeds/delta_feed.py`
- **._normalize_candlestick_resolutions()** (5 connections) — `core/data/feeds/delta_feed.py`
- **delta_ws_supports_timeframe()** (4 connections) — `core/data/feeds/delta_candlestick.py`
- **.get_last_candle()** (3 connections) — `core/data/feeds/delta_feed.py`
- **.__init__()** (3 connections) — `core/data/feeds/delta_feed.py`
- **_resolution_sort_key()** (2 connections) — `core/data/feeds/delta_candlestick.py`
- **Delta Exchange WebSocket candlestick resolutions (shared by feed + WS client).** (1 connections) — `core/data/feeds/delta_candlestick.py`
- **Map engine/strategy timeframe keys to unique Delta WS candlestick resolutions.…** (1 connections) — `core/data/feeds/delta_candlestick.py`
- **Unique, sorted Delta candlestick channel suffixes (e.g. 1m, 5m).** (1 connections) — `core/data/feeds/delta_feed.py`
- **Delta-only: TF has a native WS candlestick channel (else use tick aggregator).** (1 connections) — `core/data/feeds/delta_feed.py`
- **Delta WS candlestick OHLC for a bucket (same source as REST historical).** (1 connections) — `core/data/feeds/delta_feed.py`
- **Delta: closed bar OHLC from WS candlestick cache (authoritative vs aggregator).** (1 connections) — `core/engine/live_engine.py`
- **Delta-only: use WS candlestick OHLC when this TF has a native exchange channel.** (1 connections) — `core/engine/live_engine.py`

## Relationships

- [DeltaWebSocketFeed](DeltaWebSocketFeed.md) (8 shared connections)
- [logging.py](logging.py.md) (6 shared connections)
- [factory.py](factory.py.md) (5 shared connections)
- [Any](Any.md) (3 shared connections)
- [.start](start.md) (2 shared connections)
- [LiveEngine](LiveEngine.md) (2 shared connections)
- [CandleAggregator](CandleAggregator.md) (2 shared connections)
- [.create_live_engine](create_live_engine.md) (1 shared connections)
- [typing](typing.md) (1 shared connections)

## Source Files

- `core/data/feeds/delta_candlestick.py`
- `core/data/feeds/delta_feed.py`
- `core/engine/live_engine.py`

## Audit Trail

- EXTRACTED: 49 (86%)
- INFERRED: 8 (14%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*