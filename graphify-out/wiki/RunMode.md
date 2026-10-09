# RunMode

> 102 nodes

## Key Concepts

- **RunMode** (71 connections) — `run/config.py`
- **order_router.py** (57 connections) — `core/orderExecution/order_router.py`
- **types.py** (54 connections) — `core/events/types.py`
- **pathlib** (42 connections)
- **IntentStatus** (38 connections) — `core/orderExecution/intent_store.py`
- **gtt_fallback_book.py** (36 connections) — `core/orderExecution/gtt_fallback_book.py`
- **config.py** (36 connections) — `run/config.py`
- **OrderIntent** (33 connections) — `core/models/order_intent.py`
- **position_manager.py** (30 connections) — `core/orderExecution/position_manager.py`
- **engine_config.py** (25 connections) — `run/engine_config.py`
- **reentry_at_cost_book.py** (24 connections) — `core/orderExecution/reentry_at_cost_book.py`
- **retry_leaps_main.py** (24 connections) — `core/strategies/IBBM/Leaps/emergency/retry_leaps_main.py`
- **OrderState** (23 connections) — `core/orderExecution/order_router.py`
- **unittest** (23 connections)
- **test_ownership_claim_guard.py** (22 connections) — `core/orderExecution/test_ownership_claim_guard.py`
- **unittest_mock** (22 connections)
- **test_gtt_broker_position_adopt.py** (21 connections) — `core/orderExecution/test_gtt_broker_position_adopt.py`
- **test_manual_broker_flat_sync.py** (20 connections) — `core/orderExecution/test_manual_broker_flat_sync.py`
- **test_four_hour_liquidity_sweep.py** (20 connections) — `core/strategies/crypto/LiquiditySweepStrategy/tests/test_four_hour_liquidity_sweep.py`
- **delta.py** (20 connections) — `core/utils/instruments/delta.py`
- **zoneinfo** (20 connections)
- **intent_store.py** (19 connections) — `core/orderExecution/intent_store.py`
- **dhan.py** (19 connections) — `core/utils/instruments/dhan.py`
- **test_directional_option_selling.py** (17 connections) — `core/strategies/crypto/DirectionalOptionSelling/tests/test_directional_option_selling.py`
- **instrument_store.py** (17 connections) — `core/utils/instruments/instrument_store.py`
- *... and 77 more nodes in this community*

## Relationships

- [typing](typing.md) (131 shared connections)
- [logging.py](logging.py.md) (47 shared connections)
- [factory.py](factory.py.md) (44 shared connections)
- [ReentryAtCostBook](ReentryAtCostBook.md) (16 shared connections)
- [force_leaps_cycle.py](force_leaps_cycle.py.md) (14 shared connections)
- [EngineConfig](EngineConfig.md) (12 shared connections)
- [OrderRouter](OrderRouter.md) (11 shared connections)
- [roll_leaps_hedge.py](roll_leaps_hedge.py.md) (11 shared connections)
- [Instrument](Instrument.md) (11 shared connections)
- [ExecutionValidator](ExecutionValidator.md) (10 shared connections)
- [GttFallbackBook](GttFallbackBook.md) (9 shared connections)
- [main.py](main.py.md) (9 shared connections)

## Source Files

- `core/broker/internal/dhan/test_dh906_sl_pricing.py`
- `core/broker/internal/simulated/broker.py`
- `core/data/option_chain_service.py`
- `core/engine/tests/test_delta_main_sl_retry.py`
- `core/engine/tests/test_extra_timeframe_live_append.py`
- `core/events/types.py`
- `core/models/order_intent.py`
- `core/orderExecution/bracket_orders.py`
- `core/orderExecution/gtt_fallback_book.py`
- `core/orderExecution/intent_store.py`
- `core/orderExecution/order_router.py`
- `core/orderExecution/position_manager.py`
- `core/orderExecution/reentry_at_cost_book.py`
- `core/orderExecution/test_broker_no_open_position_sync.py`
- `core/orderExecution/test_gtt_broker_position_adopt.py`
- `core/orderExecution/test_main_sl_keeps_strategy_limit.py`
- `core/orderExecution/test_manual_broker_flat_sync.py`
- `core/orderExecution/test_overnight_reconcile_symbol_map.py`
- `core/orderExecution/test_ownership_claim_guard.py`
- `core/orderExecution/test_process_trade_reentry_bus.py`

## Audit Trail

- EXTRACTED: 771 (92%)
- INFERRED: 69 (8%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*