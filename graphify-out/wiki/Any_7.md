# Any

> 28 nodes

## Key Concepts

- **Any** (62 connections)
- **._evaluate_strategies_parallel()** (13 connections) — `core/engine/live_engine.py`
- **.__init__()** (13 connections) — `core/engine/live_engine.py`
- **._is_scheduled_strategy()** (8 connections) — `core/engine/live_engine.py`
- **._collect_feed_symbols()** (7 connections) — `core/engine/live_engine.py`
- **._candle_strategy_for()** (6 connections) — `core/engine/live_engine.py`
- **._eval_mode_for_strategy()** (6 connections) — `core/engine/live_engine.py`
- **._resolve_underlying_for_fill_hook()** (6 connections) — `core/engine/live_engine.py`
- **._collect_engine_timeframes_from_strategies()** (5 connections) — `core/engine/live_engine.py`
- **._recent_candles_for_strategy()** (5 connections) — `core/engine/live_engine.py`
- **._underlying_from_strategy_meta()** (5 connections) — `core/engine/live_engine.py`
- **._enrich_candle_for_strategy()** (4 connections) — `core/engine/live_engine.py`
- **.needs_candle_aggregator()** (4 connections) — `core/engine/live_engine.py`
- **._strategy_owns_timeframe()** (4 connections) — `core/engine/live_engine.py`
- **._collect_engine_timeframes()** (3 connections) — `core/engine/live_engine.py`
- **._graceful_shutdown_handler()** (3 connections) — `core/engine/live_engine.py`
- **._is_scheduled_timeframe()** (3 connections) — `core/engine/live_engine.py`
- **._normalize_eval_mode()** (3 connections) — `core/engine/live_engine.py`
- **._safe_queue_put()** (3 connections) — `core/engine/live_engine.py`
- **._underlying_from_structure_id()** (3 connections) — `core/engine/live_engine.py`
- **_position_allows_strategy_exit()** (3 connections) — `core/engine/live_engine.py`
- **._append_intent_journal()** (2 connections) — `core/engine/live_engine.py`
- **._process_intent_with_retry()** (2 connections) — `core/engine/live_engine.py`
- **Symbols that require websocket tick aggregation (excludes scheduled-only…** (1 connections) — `core/engine/live_engine.py`
- **MAIN book and post-partial trail legs (tag may become MAIN_TARGET after TARGET…** (1 connections) — `core/engine/live_engine.py`
- *... and 3 more nodes in this community*

## Relationships

- [LiveEngine](LiveEngine.md) (30 shared connections)
- [.start](start.md) (12 shared connections)
- [._on_pm_main_entry_fill_impl](_on_pm_main_entry_fill_impl.md) (11 shared connections)
- [.option_identity_key](option_identity_key.md) (6 shared connections)
- [._log_intent_filled](_log_intent_filled.md) (6 shared connections)
- [ExitRolloverService](ExitRolloverService.md) (3 shared connections)
- [.create_live_engine](create_live_engine.md) (2 shared connections)
- [._maybe_tick_reentry_at_cost](_maybe_tick_reentry_at_cost.md) (2 shared connections)
- [factory.py](factory.py.md) (2 shared connections)
- [delta_candlestick.py](delta_candlestick.py.md) (2 shared connections)
- [Remaining optimizations (priority order)](Remaining_optimizations_priority_order.md) (1 shared connections)
- [normalize_underlying](normalize_underlying.md) (1 shared connections)

## Source Files

- `core/engine/live_engine.py`

## Audit Trail

- EXTRACTED: 127 (96%)
- INFERRED: 5 (4%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*