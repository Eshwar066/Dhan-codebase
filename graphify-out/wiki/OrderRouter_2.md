# OrderRouter

> God node · 138 connections · `core/orderExecution/order_router.py`

**Community:** [OrderRouter](OrderRouter.md)

## Connections by Relation

### calls
- .create_live_engine() `EXTRACTED`
- .create_backtest_engine() `EXTRACTED`

### contains
- order_router.py `EXTRACTED`

### imports
- [factory.py](factory.py.md) `EXTRACTED`
- test_gtt_broker_position_adopt.py `EXTRACTED`
- test_manual_broker_flat_sync.py `EXTRACTED`
- test_execution_validator.py `EXTRACTED`
- test_overnight_reconcile_symbol_map.py `EXTRACTED`
- test_broker_no_open_position_sync.py `EXTRACTED`
- [test_order_repricing.py](test_order_repricing.py.md) `EXTRACTED`
- test_process_trade_reentry_bus.py `EXTRACTED`
- test_main_sl_keeps_strategy_limit.py `EXTRACTED`

### method
- .process_intent() `EXTRACTED`
- ._set_order_state() `EXTRACTED`
- .verify_open_orders_with_broker() `EXTRACTED`
- .process_trade() `EXTRACTED`
- ._process_dhan_hedge_gated_bundle() `EXTRACTED`
- .process_fill() `EXTRACTED`
- .process_intent_bundle() `EXTRACTED`
- .sync_trades_from_broker() `EXTRACTED`
- ._poll_and_sync_intent_terminal() `EXTRACTED`
- ._process_delta_bracket_bundle() `EXTRACTED`
- ._instrument_trading_symbol() `EXTRACTED`
- ._process_external_close_fill() `EXTRACTED`
- ._resolve_exec_price() `EXTRACTED`
- ._apply_gtt_fill_from_intent() `EXTRACTED`
- .sync_local_after_manual_broker_flat() `EXTRACTED`
- ._try_sync_gtt_intent_fill() `EXTRACTED`
- ._broker_position_row_for_intent() `EXTRACTED`
- ._log_oms_step() `EXTRACTED`
- ._persist_order_state() `EXTRACTED`
- ._intent_trading_symbol() `EXTRACTED`
- *…and 80 more `method` connection(s) not listed (lowest-degree first to go)*

### references
- High-Level Architecture `INFERRED`
- Operational notes `INFERRED`
- Phase 2 — Must-build for real multi-account (platform) `INFERRED`

### uses
- [ExpiryResolver](ExpiryResolver.md) `INFERRED`
- [PositionManager](PositionManager.md) `INFERRED`
- [GttFallbackBook](GttFallbackBook.md) `INFERRED`
- [EventType](EventType.md) `INFERRED`
- EngineFactory `INFERRED`
- IntentStatus `INFERRED`
- [ReentryAtCostBook](ReentryAtCostBook.md) `INFERRED`
- OrderIntent `INFERRED`
- [GttFallbackWatch](GttFallbackWatch.md) `INFERRED`
- [IntentStore](IntentStore.md) `INFERRED`
- [ExecutionValidator](ExecutionValidator.md) `INFERRED`
- MarketSnapshot `INFERRED`
- ExecutionValidatorConfig `INFERRED`
- [BracketLegRegistry](BracketLegRegistry.md) `INFERRED`
- [TestGttBrokerPositionAdopt](TestGttBrokerPositionAdopt.md) `INFERRED`
- ValidationResult `INFERRED`
- TestOvernightReconcileSymbolMap `INFERRED`
- TestBrokerNoOpenPositionSync `INFERRED`
- TestManualBrokerFlatSync `INFERRED`
- _router_for_entry() `INFERRED`
- *…and 3 more `uses` connection(s) not listed (lowest-degree first to go)*

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*