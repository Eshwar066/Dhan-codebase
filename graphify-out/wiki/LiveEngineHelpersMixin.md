# LiveEngineHelpersMixin

> 30 nodes

## Key Concepts

- **LiveEngineHelpersMixin** (59 connections) — `core/engine/live_engine_common.py`
- **._publish_quote_updated_from_tick()** (7 connections) — `core/engine/live_engine_common.py`
- **._quote_update_symbols()** (6 connections) — `core/engine/live_engine_common.py`
- **._drain_tick_queue()** (5 connections) — `core/engine/live_engine_common.py`
- **._drain_candle_queue()** (4 connections) — `core/engine/live_engine_common.py`
- **._quote_fields_from_feed()** (4 connections) — `core/engine/live_engine_common.py`
- **._strategy_quote_symbols()** (4 connections) — `core/engine/live_engine_common.py`
- **._reentry_watch_symbols()** (3 connections) — `core/engine/live_engine_common.py`
- **._tf_to_minutes()** (3 connections) — `core/engine/live_engine_common.py`
- **._do_entry_order_refresh()** (2 connections) — `core/engine/live_engine_common.py`
- **._do_exit_order_refresh()** (2 connections) — `core/engine/live_engine_common.py`
- **._gtt_watch_symbols()** (2 connections) — `core/engine/live_engine_common.py`
- **._intent_has_entry()** (2 connections) — `core/engine/live_engine_common.py`
- **._log_startup_balance_snapshot()** (2 connections) — `core/engine/live_engine_common.py`
- **._positive_price()** (2 connections) — `core/engine/live_engine_common.py`
- **._validate_candle_integrity()** (2 connections) — `core/engine/live_engine_common.py`
- **._check_memory()** (1 connections) — `core/engine/live_engine_common.py`
- **Every 30s, re-quote open exit / force-exit limits at best bid/ask until fill.** (1 connections) — `core/engine/live_engine_common.py`
- **Every 30 seconds, re-quote unfilled entry limits at best bid/ask.** (1 connections) — `core/engine/live_engine_common.py`
- **One-time startup balance check/log for observability before live loop.** (1 connections) — `core/engine/live_engine_common.py`
- **Drain ticks into candles and publish subscribed ``QuoteUpdated`` events.** (1 connections) — `core/engine/live_engine_common.py`
- **Underlying symbols explicitly subscribed to strategy quote hooks.** (1 connections) — `core/engine/live_engine_common.py`
- **Best bid/ask/ltp from realtime feed cache for QuoteUpdated payload.** (1 connections) — `core/engine/live_engine_common.py`
- **Push ``QuoteUpdated`` for GTT or strategy-subscribed symbols.** (1 connections) — `core/engine/live_engine_common.py`
- **Apply Delta exchange candlestick OHLC over tick-built bars (per resolution).** (1 connections) — `core/engine/live_engine_common.py`
- *... and 5 more nodes in this community*

## Relationships

- [Any](Any.md) (14 shared connections)
- [._rest_option_quote](_rest_option_quote.md) (7 shared connections)
- [._candle_timestamp_to_utc_naive](_candle_timestamp_to_utc_naive.md) (7 shared connections)
- [._should_disconnect_market_ws](_should_disconnect_market_ws.md) (5 shared connections)
- [._is_market_open_for_feed_health](_is_market_open_for_feed_health.md) (4 shared connections)
- [factory.py](factory.py.md) (3 shared connections)
- [LiveEngine](LiveEngine.md) (1 shared connections)
- [._export_eod](_export_eod.md) (1 shared connections)
- [EventType](EventType.md) (1 shared connections)
- [RestQuoteProvider](RestQuoteProvider.md) (1 shared connections)
- [NiftySMA9Weekly](NiftySMA9Weekly.md) (1 shared connections)
- [CandleAggregator](CandleAggregator.md) (1 shared connections)

## Source Files

- `core/engine/live_engine_common.py`

## Audit Trail

- EXTRACTED: 81 (94%)
- INFERRED: 5 (6%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*