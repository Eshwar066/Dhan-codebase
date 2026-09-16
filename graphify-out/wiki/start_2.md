# .start

> 26 nodes

## Key Concepts

- **.start()** (39 connections) — `core/engine/live_engine.py`
- **._maybe_run_scheduled_evaluations()** (15 connections) — `core/engine/live_engine.py`
- **._current_ist_now()** (7 connections) — `core/engine/live_engine.py`
- **._run_strategy()** (7 connections) — `core/engine/live_engine.py`
- **._log_entry_skipped_if_paused()** (6 connections) — `core/engine/live_engine.py`
- **._run_gtt_fallback_tick()** (6 connections) — `core/engine/live_engine.py`
- **._build_scheduled_candle()** (5 connections) — `core/engine/live_engine.py`
- **._event_bus_has_subscribers()** (5 connections) — `core/engine/live_engine.py`
- **._maybe_flush_session_end_candles()** (5 connections) — `core/engine/live_engine.py`
- **._entry_pause_reasons()** (4 connections) — `core/engine/live_engine.py`
- **._get_last_closed_from_aggregator()** (4 connections) — `core/engine/live_engine.py`
- **._handle_startup_failure()** (4 connections) — `core/engine/live_engine.py`
- **._normalize_scheduled_time()** (4 connections) — `core/engine/live_engine.py`
- **._extract_spot_close()** (3 connections) — `core/engine/live_engine.py`
- **._is_continuous_market_venue()** (3 connections) — `core/engine/live_engine.py`
- **._symbols_for_strategy()** (3 connections) — `core/engine/live_engine.py`
- **datetime** (3 connections)
- **._symbol_tf_eval_key()** (2 connections) — `core/engine/live_engine.py`
- **dt_time** (2 connections)
- **Log and return True when ENTRY routing is blocked by engine pause flags.** (1 connections) — `core/engine/live_engine.py`
- **Resolve ``CandleAggregator`` state by symbol. Tick callbacks may register a…** (1 connections) — `core/engine/live_engine.py`
- **After configured session close (e.g. NSE 15:30 IST, MCX 23:30 IST), finalize…** (1 connections) — `core/engine/live_engine.py`
- **GTT maintenance (fill sync + active_until) every cycle. Quote triggers are…** (1 connections) — `core/engine/live_engine.py`
- **IST now; dummy feed uses simulated ``start_datetime`` when set.** (1 connections) — `core/engine/live_engine.py`
- **24×7 venues (Delta crypto) skip NSE-style session alignment stitching.** (1 connections) — `core/engine/live_engine.py`
- *... and 1 more nodes in this community*

## Relationships

- [LiveEngine](LiveEngine.md) (20 shared connections)
- [Any](Any.md) (12 shared connections)
- [indicator_history.py](indicator_history.py.md) (6 shared connections)
- [._maybe_tick_reentry_at_cost](_maybe_tick_reentry_at_cost.md) (4 shared connections)
- [make_event](make_event.md) (3 shared connections)
- [._on_pm_main_entry_fill_impl](_on_pm_main_entry_fill_impl.md) (3 shared connections)
- [test_economic_events.py](test_economic_events.py.md) (2 shared connections)
- [engine_restart_budget.py](engine_restart_budget.py.md) (2 shared connections)
- [CandleAggregator](CandleAggregator.md) (2 shared connections)
- [ExitRolloverService](ExitRolloverService.md) (2 shared connections)
- [.option_identity_key](option_identity_key.md) (2 shared connections)
- [._log_intent_filled](_log_intent_filled.md) (2 shared connections)

## Source Files

- `core/engine/live_engine.py`

## Audit Trail

- EXTRACTED: 94 (93%)
- INFERRED: 7 (7%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*