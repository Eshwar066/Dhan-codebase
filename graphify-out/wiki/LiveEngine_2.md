# LiveEngine

> God node · 148 connections · `core/engine/live_engine.py`

**Community:** [LiveEngine](LiveEngine.md)

## Connections by Relation

### contains
- live_engine.py `EXTRACTED`

### imports
- [factory.py](factory.py.md) `EXTRACTED`
- [test_economic_events.py](test_economic_events.py.md) `EXTRACTED`
- test_manual_broker_flat_sync.py `EXTRACTED`
- supervisor.py `EXTRACTED`
- test_broker_no_open_position_sync.py `EXTRACTED`
- engine/__init__.py `EXTRACTED`
- test_delta_main_sl_retry.py `EXTRACTED`
- test_extra_timeframe_live_append.py `EXTRACTED`

### inherits
- [LiveEngineHelpersMixin](LiveEngineHelpersMixin.md) `EXTRACTED`
- BaseEngine `EXTRACTED`

### method
- .start() `EXTRACTED`
- ._maybe_run_scheduled_evaluations() `EXTRACTED`
- ._evaluate_strategies_parallel() `EXTRACTED`
- .__init__() `EXTRACTED`
- .reconcile_positions_on_start() `EXTRACTED`
- ._ensure_bracket_legs_after_reconcile() `EXTRACTED`
- ._apply_manual_flat_closes_after_reconcile() `EXTRACTED`
- ._on_pm_main_entry_fill_impl() `EXTRACTED`
- ._maybe_tick_reentry_at_cost() `EXTRACTED`
- ._strategy_obj_for_name() `EXTRACTED`
- ._get_exchange_closed_candle() `EXTRACTED`
- ._process_entry_like_intent() `EXTRACTED`
- ._maybe_retry_delta_missing_main_sl() `EXTRACTED`
- ._force_close_position_missing_main_sl() `EXTRACTED`
- ._reconcile_candle_with_exchange() `EXTRACTED`
- ._configure_gtt_fallback_book() `EXTRACTED`
- ._is_scheduled_strategy() `EXTRACTED`
- .build_context_only() `EXTRACTED`
- ._run_exits_and_rollover() `EXTRACTED`
- ._on_pm_main_exit_fill() `EXTRACTED`
- *…and 89 more `method` connection(s) not listed (lowest-degree first to go)*

### rationale_for
- Live/paper engine. Uses realtime_feed (WebSocket/aggregator) candle flow in… `EXTRACTED`

### references
- .create_live_engine() `EXTRACTED`
- Services (logic ownership) `INFERRED`
- .create_engine() `EXTRACTED`
- [OMS Flow](OMS_Flow.md) `INFERRED`
- High-Level Architecture `INFERRED`
- ._run_live_engine() `EXTRACTED`

### uses
- [ExpiryResolver](ExpiryResolver.md) `INFERRED`
- [RunMode](RunMode.md) `INFERRED`
- [IndicatorManager](IndicatorManager.md) `INFERRED`
- [PositionManager](PositionManager.md) `INFERRED`
- [EventType](EventType.md) `INFERRED`
- EngineFactory `INFERRED`
- IntentStatus `INFERRED`
- OrderState `INFERRED`
- [ExecutionEngine](ExecutionEngine.md) `INFERRED`
- [AccountRouter](AccountRouter.md) `INFERRED`
- [ExitRolloverService](ExitRolloverService.md) `INFERRED`
- [Supervisor](Supervisor.md) `INFERRED`
- [RestQuoteProvider](RestQuoteProvider.md) `INFERRED`
- [TestExtraTimeframeLiveAppend](TestExtraTimeframeLiveAppend.md) `INFERRED`
- TestBrokerNoOpenPositionSync `INFERRED`
- [TestManualFlatSessionGate](TestManualFlatSessionGate.md) `INFERRED`
- FeedQuoteProvider `INFERRED`
- CompositeQuoteProvider `INFERRED`
- [TestDeltaMainSlRetry](TestDeltaMainSlRetry.md) `INFERRED`
- ExitBudgetExceeded `INFERRED`
- *…and 1 more `uses` connection(s) not listed (lowest-degree first to go)*

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*