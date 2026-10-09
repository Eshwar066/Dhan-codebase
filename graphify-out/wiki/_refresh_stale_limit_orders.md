# ._refresh_stale_limit_orders

> 6 nodes

## Key Concepts

- **._refresh_stale_limit_orders()** (5 connections) — `core/orderExecution/order_router.py`
- **.refresh_stale_entry_orders()** (3 connections) — `core/orderExecution/order_router.py`
- **.refresh_stale_exit_orders()** (3 connections) — `core/orderExecution/order_router.py`
- **Re-quote open EXIT / FORCE_EXIT limits at best bid (SELL) or ask (BUY).** (1 connections) — `core/orderExecution/order_router.py`
- **Re-quote open ENTRY limits at best bid for SELL / best ask for BUY.** (1 connections) — `core/orderExecution/order_router.py`
- **Modify matching open limit orders in place; never cancel or duplicate them.** (1 connections) — `core/orderExecution/order_router.py`

## Relationships

- [OrderRouter](OrderRouter.md) (3 shared connections)
- [._set_order_state](_set_order_state.md) (1 shared connections)

## Source Files

- `core/orderExecution/order_router.py`

## Audit Trail

- EXTRACTED: 9 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*