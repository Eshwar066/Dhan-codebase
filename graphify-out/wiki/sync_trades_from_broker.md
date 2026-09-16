# .sync_trades_from_broker

> 26 nodes

## Key Concepts

- **.sync_trades_from_broker()** (12 connections) — `core/orderExecution/order_router.py`
- **._process_external_close_fill()** (11 connections) — `core/orderExecution/order_router.py`
- **._find_position_for_external_close()** (7 connections) — `core/orderExecution/order_router.py`
- **._external_close_confidence_score()** (6 connections) — `core/orderExecution/order_router.py`
- **._close_qty_from_fill()** (5 connections) — `core/orderExecution/order_router.py`
- **._fill_product_symbol()** (5 connections) — `core/orderExecution/order_router.py`
- **._fill_timestamp_unix()** (5 connections) — `core/orderExecution/order_router.py`
- **._is_delta_liquidation_fill()** (5 connections) — `core/orderExecution/order_router.py`
- **._is_adl_fill()** (4 connections) — `core/orderExecution/order_router.py`
- **._orphan_fill_fails_time_gates()** (4 connections) — `core/orderExecution/order_router.py`
- **._known_broker_order_ids()** (3 connections) — `core/orderExecution/order_router.py`
- **._string_indicates_exchange_liquidation()** (3 connections) — `core/orderExecution/order_router.py`
- **._symbol_keys_close_enough()** (3 connections) — `core/orderExecution/order_router.py`
- **_rank_tuple()** (2 connections) — `core/orderExecution/order_router.py`
- **True only for explicit liquidation semantics — not bare 'liquid' (matches…** (1 connections) — `core/orderExecution/order_router.py`
- **True if broker fill is an exchange-driven liquidation (no client_order_id /…** (1 connections) — `core/orderExecution/order_router.py`
- **Auto-deleverage close (future-proof; Delta/metadata may expose flags later).** (1 connections) — `core/orderExecution/order_router.py`
- **All broker order IDs we have recorded on intents (own orders).** (1 connections) — `core/orderExecution/order_router.py`
- **Confidence for treating a fill as EXTERNAL_CLOSE (not boolean) — reduces false…** (1 connections) — `core/orderExecution/order_router.py`
- **Parse broker fill time to UTC unix seconds (float). None if missing or…** (1 connections) — `core/orderExecution/order_router.py`
- **True => do not run orphan EXTERNAL_CLOSE / LIQUIDATION / ADL for this fill.** (1 connections) — `core/orderExecution/order_router.py`
- **Case-insensitive match for option contract symbols (e.g. C-BTC-65000-030426).** (1 connections) — `core/orderExecution/order_router.py`
- **Contracts to apply for this fill: supports partial liquidation when size is in…** (1 connections) — `core/orderExecution/order_router.py`
- **Match external close to an open leg. Priority when multiple: exact size,…** (1 connections) — `core/orderExecution/order_router.py`
- **Liquidation / ADL / orphan reduce-only fills without intent linkage.…** (1 connections) — `core/orderExecution/order_router.py`
- *... and 1 more nodes in this community*

## Relationships

- [OrderRouter](OrderRouter.md) (14 shared connections)
- [Any](Any.md) (9 shared connections)
- [._set_order_state](_set_order_state.md) (3 shared connections)
- [RiskManager](RiskManager.md) (1 shared connections)

## Source Files

- `core/orderExecution/order_router.py`

## Audit Trail

- EXTRACTED: 55 (96%)
- INFERRED: 2 (4%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*