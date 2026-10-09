# LiveEngine

> 30 nodes

## Key Concepts

- **LiveEngine** (148 connections) — `core/engine/live_engine.py`
- **._do_order_state_check()** (5 connections) — `core/engine/live_engine.py`
- **._ensure_strategy_worker()** (5 connections) — `core/engine/live_engine.py`
- **._can_restart_worker()** (4 connections) — `core/engine/live_engine.py`
- **._gtt_fallback_subscribe()** (4 connections) — `core/engine/live_engine.py`
- **._market_snapshot_for_symbol()** (4 connections) — `core/engine/live_engine.py`
- **._on_broker_no_open_position()** (4 connections) — `core/engine/live_engine.py`
- **._subscribe_open_option_legs()** (4 connections) — `core/engine/live_engine.py`
- **._worker_id()** (4 connections) — `core/engine/live_engine.py`
- **.build_context()** (3 connections) — `core/engine/live_engine.py`
- **._configure_execution_validator()** (3 connections) — `core/engine/live_engine.py`
- **._configure_reentry_at_cost_book()** (3 connections) — `core/engine/live_engine.py`
- **._is_transient_broker_reconcile_error()** (3 connections) — `core/engine/live_engine.py`
- **._merge_feed_instruments()** (3 connections) — `core/engine/live_engine.py`
- **._prune_runtime_memory()** (3 connections) — `core/engine/live_engine.py`
- **._start_execution_pipeline()** (3 connections) — `core/engine/live_engine.py`
- **._ticker_has_mark()** (3 connections) — `core/engine/live_engine.py`
- **_premium()** (1 connections) — `core/engine/live_engine.py`
- **._ensure_workers_healthy()** (1 connections) — `core/engine/live_engine.py`
- **._process_account_symbol_queue()** (1 connections) — `core/engine/live_engine.py`
- **._route_intents_worker()** (1 connections) — `core/engine/live_engine.py`
- **._token_bucket_wait()** (1 connections) — `core/engine/live_engine.py`
- **.update_risk_metrics()** (1 connections) — `core/engine/live_engine.py`
- **._watchdog_loop()** (1 connections) — `core/engine/live_engine.py`
- **Broker says no open position while placing bracket/SL — sync local state.** (1 connections) — `core/engine/live_engine.py`
- *... and 5 more nodes in this community*

## Relationships

- [Any](Any.md) (30 shared connections)
- [.start](start.md) (20 shared connections)
- [._on_pm_main_entry_fill_impl](_on_pm_main_entry_fill_impl.md) (18 shared connections)
- [.option_identity_key](option_identity_key.md) (11 shared connections)
- [._log_intent_filled](_log_intent_filled.md) (8 shared connections)
- [RunMode](RunMode.md) (7 shared connections)
- [factory.py](factory.py.md) (6 shared connections)
- [ExitRolloverService](ExitRolloverService.md) (4 shared connections)
- [.create_live_engine](create_live_engine.md) (3 shared connections)
- [indicator_history.py](indicator_history.py.md) (3 shared connections)
- [test_economic_events.py](test_economic_events.py.md) (2 shared connections)
- [Supervisor](Supervisor.md) (2 shared connections)

## Source Files

- `core/engine/live_engine.py`

## Audit Trail

- EXTRACTED: 154 (86%)
- INFERRED: 26 (14%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*