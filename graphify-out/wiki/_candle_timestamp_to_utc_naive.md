# ._candle_timestamp_to_utc_naive

> 14 nodes

## Key Concepts

- **._candle_timestamp_to_utc_naive()** (10 connections) — `core/engine/live_engine_common.py`
- **._is_closed_candle()** (10 connections) — `core/engine/live_engine_common.py`
- **._closed_candle_diagnostics()** (7 connections) — `core/engine/live_engine_common.py`
- **datetime** (7 connections)
- **._now_utc_naive()** (5 connections) — `core/engine/live_engine_common.py`
- **._dhan_repair_naive_as_ist_wallclock()** (4 connections) — `core/engine/live_engine_common.py`
- **._numeric_ts_to_utc_seconds()** (4 connections) — `core/engine/live_engine_common.py`
- **._is_nse_index_candle()** (3 connections) — `core/engine/live_engine_common.py`
- **Normalize broker timestamps: unix seconds (~1e9), millis (~1e12), or micros…** (1 connections) — `core/engine/live_engine_common.py`
- **Dhan WS ``last_trade_time`` / naive datetimes are often **IST wall components**…** (1 connections) — `core/engine/live_engine_common.py`
- **Parse any candle timestamp to naive UTC datetime for consistent comparisons.** (1 connections) — `core/engine/live_engine_common.py`
- **Wall-clock 'now' as naive UTC (same basis as utcfromtimestamp outputs).** (1 connections) — `core/engine/live_engine_common.py`
- **True if candle timestamp is on timeframe boundary and not in the future. -…** (1 connections) — `core/engine/live_engine_common.py`
- **Structured fields for logs when ``_is_closed_candle`` fails (feed snapshot +…** (1 connections) — `core/engine/live_engine_common.py`

## Relationships

- [LiveEngineHelpersMixin](LiveEngineHelpersMixin.md) (7 shared connections)
- [Any](Any.md) (5 shared connections)
- [factory.py](factory.py.md) (3 shared connections)
- [indicator_history.py](indicator_history.py.md) (3 shared connections)
- [NiftySMA9Weekly](NiftySMA9Weekly.md) (1 shared connections)
- [._is_market_open_for_feed_health](_is_market_open_for_feed_health.md) (1 shared connections)

## Source Files

- `core/engine/live_engine_common.py`

## Audit Trail

- EXTRACTED: 38 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*