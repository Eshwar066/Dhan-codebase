# ._on_pm_main_entry_fill_impl

> 26 nodes

## Key Concepts

- **._on_pm_main_entry_fill_impl()** (11 connections) — `core/engine/live_engine.py`
- **._strategy_obj_for_name()** (10 connections) — `core/engine/live_engine.py`
- **._process_entry_like_intent()** (9 connections) — `core/engine/live_engine.py`
- **.build_context_only()** (8 connections) — `core/engine/live_engine.py`
- **._force_close_position_missing_main_sl()** (8 connections) — `core/engine/live_engine.py`
- **._maybe_retry_delta_missing_main_sl()** (8 connections) — `core/engine/live_engine.py`
- **._on_pm_main_exit_fill()** (8 connections) — `core/engine/live_engine.py`
- **._enqueue_entry_intents_grouped()** (6 connections) — `core/engine/live_engine.py`
- **._on_pm_main_entry_fill()** (6 connections) — `core/engine/live_engine.py`
- **._process_strategy_exit_intent()** (6 connections) — `core/engine/live_engine.py`
- **._on_invalid_stop()** (5 connections) — `core/engine/live_engine.py`
- **._resolve_entry_price_map()** (5 connections) — `core/engine/live_engine.py`
- **._enqueue_intent()** (4 connections) — `core/engine/live_engine.py`
- **._process_rollover_intent()** (4 connections) — `core/engine/live_engine.py`
- **._refresh_bundle_entry_prices()** (4 connections) — `core/engine/live_engine.py`
- **._enqueue_intent_bundle()** (3 connections) — `core/engine/live_engine.py`
- **._on_latency_observed()** (3 connections) — `core/engine/live_engine.py`
- **._strategy_worker_loop()** (2 connections) — `core/engine/live_engine.py`
- **Delta only: if an open MAIN has no MAIN_SL (intent or exchange), re-arm every 3…** (1 connections) — `core/engine/live_engine.py`
- **Flatten MAIN after MAIN_SL placement retries are exhausted.** (1 connections) — `core/engine/live_engine.py`
- **Pause entries after N consecutive slow cycles; clear after N healthy ones.** (1 connections) — `core/engine/live_engine.py`
- **Best bid/ask (or fallbacks) for one ENTRY intent.** (1 connections) — `core/engine/live_engine.py`
- **Refresh bundle leg limit prices from live best bid/ask (LEAPS hedge retry).** (1 connections) — `core/engine/live_engine.py`
- **Group same-structure ENTRY legs and enqueue as bundle for hedge-aware margin.** (1 connections) — `core/engine/live_engine.py`
- **Post-fill safety: MAIN_SL invalid vs mark → force-exit the open MAIN. Pre-ENTRY…** (1 connections) — `core/engine/live_engine.py`
- *... and 1 more nodes in this community*

## Relationships

- [LiveEngine](LiveEngine.md) (18 shared connections)
- [Any](Any.md) (11 shared connections)
- [.option_identity_key](option_identity_key.md) (5 shared connections)
- [reentry_at_cost.py](reentry_at_cost.py.md) (4 shared connections)
- [.start](start.md) (3 shared connections)
- [normalize_underlying](normalize_underlying.md) (1 shared connections)
- [DeltaBroker](DeltaBroker.md) (1 shared connections)
- [ExitRolloverService](ExitRolloverService.md) (1 shared connections)

## Source Files

- `core/engine/live_engine.py`

## Audit Trail

- EXTRACTED: 77 (95%)
- INFERRED: 4 (5%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*