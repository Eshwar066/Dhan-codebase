# Order Execution

> 24 nodes

## Key Concepts

- **Order Execution** (11 connections) — `core/orderExecution/README.md`
- **._try_sync_gtt_intent_fill()** (9 connections) — `core/orderExecution/order_router.py`
- **.adopt_gtt_intent_from_broker_positions()** (8 connections) — `core/orderExecution/order_router.py`
- **.cancel_unfilled_strategy_orders()** (8 connections) — `core/orderExecution/order_router.py`
- **._intent_is_gtt()** (8 connections) — `core/orderExecution/order_router.py`
- **._sync_gtt_pending_fills()** (7 connections) — `core/orderExecution/order_router.py`
- **.adopt_pending_entries_from_broker_positions()** (6 connections) — `core/orderExecution/order_router.py`
- **._intent_execution_mode()** (3 connections) — `core/orderExecution/order_router.py`
- **Dependencies** (3 connections) — `core/orderExecution/README.md`
- **Execution modes (`metadata_extras.execution_mode`)** (3 connections) — `core/orderExecution/README.md`
- **Re-entry at cost (`reentry_at_cost`)** (3 connections) — `core/orderExecution/README.md`
- **Files** (2 connections) — `core/orderExecution/README.md`
- **Live pricing** (2 connections) — `core/orderExecution/README.md`
- **Multi-leg bundles** (2 connections) — `core/orderExecution/README.md`
- **orderExecution/README.md** (1 connections) — `core/orderExecution/README.md`
- **Flow** (1 connections) — `core/orderExecution/README.md`
- **Future / design notes (not implemented)** (1 connections) — `core/orderExecution/README.md`
- **Intent lifecycle** (1 connections) — `core/orderExecution/README.md`
- **Risk manager** (1 connections) — `core/orderExecution/README.md`
- **Cancel unfilled broker orders for in-flight intents (SENT/VALIDATED) owned by…** (1 connections) — `core/orderExecution/order_router.py`
- **Poll Forever order book / fills API for a single pending GTT intent.** (1 connections) — `core/orderExecution/order_router.py`
- **Sync fills for pending GTT ENTRY intents; returns count applied.** (1 connections) — `core/orderExecution/order_router.py`
- **Adopt a single pending GTT ENTRY fill from broker position truth. Used when…** (1 connections) — `core/orderExecution/order_router.py`
- **When broker holds qty for a symbol with a pending GTT ENTRY intent locally,…** (1 connections) — `core/orderExecution/order_router.py`

## Relationships

- [OrderRouter](OrderRouter.md) (11 shared connections)
- [Any](Any.md) (8 shared connections)
- [._set_order_state](_set_order_state.md) (3 shared connections)
- [.option_identity_key](option_identity_key.md) (2 shared connections)
- [._broker_position_row_for_intent](_broker_position_row_for_intent.md) (1 shared connections)
- [IntentStore](IntentStore.md) (1 shared connections)
- [RunMode](RunMode.md) (1 shared connections)
- [StrategyContext](StrategyContext.md) (1 shared connections)
- [GttFallbackBook](GttFallbackBook.md) (1 shared connections)
- [RiskManager](RiskManager.md) (1 shared connections)
- [DeltaBroker](DeltaBroker.md) (1 shared connections)
- [ReentryAtCostBook](ReentryAtCostBook.md) (1 shared connections)

## Source Files

- `core/orderExecution/README.md`
- `core/orderExecution/order_router.py`

## Audit Trail

- EXTRACTED: 48 (81%)
- INFERRED: 11 (19%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*