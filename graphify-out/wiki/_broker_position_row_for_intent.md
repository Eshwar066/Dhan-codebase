# ._broker_position_row_for_intent

> 11 nodes

## Key Concepts

- **._broker_position_row_for_intent()** (9 connections) — `core/orderExecution/order_router.py`
- **.sync_local_after_manual_broker_flat()** (9 connections) — `core/orderExecution/order_router.py`
- **._intent_trading_symbol()** (8 connections) — `core/orderExecution/order_router.py`
- **._intent_symbol_aliases()** (7 connections) — `core/orderExecution/order_router.py`
- **._alnum_symbol_key()** (5 connections) — `core/orderExecution/order_router.py`
- **.cancel_gtt_fallback_watch()** (5 connections) — `core/orderExecution/order_router.py`
- **.find_entry_intent_for_symbol()** (5 connections) — `core/orderExecution/order_router.py`
- **Manual Dhan exit: cancel resting local intents/orders for this leg and drop GTT…** (1 connections) — `core/orderExecution/order_router.py`
- **Cancel the broker Forever order for a hybrid GTT watch (this leg only).** (1 connections) — `core/orderExecution/order_router.py`
- **Best-match MAIN ENTRY intent for a symbol (FILLED, else pending SENT/VALIDATED).** (1 connections) — `core/orderExecution/order_router.py`
- **Match broker position row to intent (engine symbol or Dhan place-order name).** (1 connections) — `core/orderExecution/order_router.py`

## Relationships

- [OrderRouter](OrderRouter.md) (7 shared connections)
- [Any](Any.md) (6 shared connections)
- [.option_identity_key](option_identity_key.md) (4 shared connections)
- [GttFallbackWatch](GttFallbackWatch.md) (3 shared connections)
- [._set_order_state](_set_order_state.md) (3 shared connections)
- [Order Execution](Order_Execution.md) (1 shared connections)

## Source Files

- `core/orderExecution/order_router.py`

## Audit Trail

- EXTRACTED: 34 (89%)
- INFERRED: 4 (11%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*