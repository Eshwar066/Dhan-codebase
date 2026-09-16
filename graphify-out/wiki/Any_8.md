# Any

> 24 nodes

## Key Concepts

- **Any** (16 connections)
- **._candle_bucket_start_unix()** (8 connections) — `core/engine/live_engine_common.py`
- **._coerce_scalar_to_float()** (5 connections) — `core/engine/live_engine_common.py`
- **._live_bar_is_stale_or_replay()** (5 connections) — `core/engine/live_engine_common.py`
- **._normalize_candle_timestamp_utc_naive()** (5 connections) — `core/engine/live_engine_common.py`
- **._should_log_closed_candle()** (4 connections) — `core/engine/live_engine_common.py`
- **._should_log_closed_candle_skip()** (4 connections) — `core/engine/live_engine_common.py`
- **._sync_candle_timestamp_from_bucket_ts()** (4 connections) — `core/engine/live_engine_common.py`
- **._enrich_candle_depth()** (3 connections) — `core/engine/live_engine_common.py`
- **._intent_place_order_symbol()** (3 connections) — `core/engine/live_engine_common.py`
- **._log_signal()** (3 connections) — `core/engine/live_engine_common.py`
- **._signal_hash()** (3 connections) — `core/engine/live_engine_common.py`
- **._validate_lot_size()** (3 connections) — `core/engine/live_engine_common.py`
- **Raise ValueError if intent.qty (lots) is invalid for the instrument.** (1 connections) — `core/engine/live_engine_common.py`
- **Log a strategy-generated signal (entry or exit) as structured JSON.** (1 connections) — `core/engine/live_engine_common.py`
- **Hash for duplicate signal detection. Override candle_ts for bar identity.** (1 connections) — `core/engine/live_engine_common.py`
- **Best-effort: Python int/float/numpy scalars → float; else None.** (1 connections) — `core/engine/live_engine_common.py`
- **Canonical bar open time from ``bucket_ts`` (aggregator / logs).** (1 connections) — `core/engine/live_engine_common.py`
- **Rewrite candle['timestamp'] to normalized naive UTC (DHAN IST fix included).** (1 connections) — `core/engine/live_engine_common.py`
- **Dhan order/depth symbol: SEM_CUSTOM_SYMBOL when set on Instrument.** (1 connections) — `core/engine/live_engine_common.py`
- **For Delta: set candle['best_bid'] and candle['best_ask'] from L2.** (1 connections) — `core/engine/live_engine_common.py`
- **When ticks + CandleAggregator are active, reject: - REST fallback rows without…** (1 connections) — `core/engine/live_engine_common.py`
- **Log one candle per (symbol, timeframe, bucket). Prevents writing the same…** (1 connections) — `core/engine/live_engine_common.py`
- **Rate-limit ``closed_candle_skip`` JSON logs. Without this, a non-aligned or…** (1 connections) — `core/engine/live_engine_common.py`

## Relationships

- [LiveEngineHelpersMixin](LiveEngineHelpersMixin.md) (14 shared connections)
- [._candle_timestamp_to_utc_naive](_candle_timestamp_to_utc_naive.md) (5 shared connections)
- [._should_disconnect_market_ws](_should_disconnect_market_ws.md) (1 shared connections)
- [factory.py](factory.py.md) (1 shared connections)

## Source Files

- `core/engine/live_engine_common.py`

## Audit Trail

- EXTRACTED: 49 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*