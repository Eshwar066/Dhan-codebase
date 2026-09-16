# Any

> 46 nodes

## Key Concepts

- **Any** (62 connections)
- **.process_intent()** (23 connections) — `core/orderExecution/order_router.py`
- **._process_dhan_hedge_gated_bundle()** (15 connections) — `core/orderExecution/order_router.py`
- **.process_intent_bundle()** (13 connections) — `core/orderExecution/order_router.py`
- **._process_delta_bracket_bundle()** (11 connections) — `core/orderExecution/order_router.py`
- **._resolve_exec_price()** (10 connections) — `core/orderExecution/order_router.py`
- **._log_oms_step()** (9 connections) — `core/orderExecution/order_router.py`
- **._validate_intent_execution()** (8 connections) — `core/orderExecution/order_router.py`
- **._cancel_hedge_intent_and_verify()** (7 connections) — `core/orderExecution/order_router.py`
- **._handle_broker_no_open_position()** (7 connections) — `core/orderExecution/order_router.py`
- **._intent_keeps_strategy_limit()** (6 connections) — `core/orderExecution/order_router.py`
- **._reject_execution_validation()** (6 connections) — `core/orderExecution/order_router.py`
- **._submit_hedge_with_retry_price()** (6 connections) — `core/orderExecution/order_router.py`
- **._await_intent_terminal()** (5 connections) — `core/orderExecution/order_router.py`
- **._lookup_price_map()** (5 connections) — `core/orderExecution/order_router.py`
- **.place_gtt_fallback_order()** (5 connections) — `core/orderExecution/order_router.py`
- **._reprice_resolved_list()** (5 connections) — `core/orderExecution/order_router.py`
- **.order_is_open()** (4 connections) — `core/broker/internal/dhan/broker.py`
- **._broker_failure_log_fields()** (4 connections) — `core/orderExecution/order_router.py`
- **._coerce_positive_exec_price()** (4 connections) — `core/orderExecution/order_router.py`
- **._failure_is_no_open_position()** (4 connections) — `core/orderExecution/order_router.py`
- **._hedge_fill_retry_enabled()** (4 connections) — `core/orderExecution/order_router.py`
- **._log_bundle_margin_check()** (4 connections) — `core/orderExecution/order_router.py`
- **._mark_hedge_intent_cancelled()** (4 connections) — `core/orderExecution/order_router.py`
- **._reject_bundle_legs()** (4 connections) — `core/orderExecution/order_router.py`
- *... and 21 more nodes in this community*

## Relationships

- [OrderRouter](OrderRouter.md) (37 shared connections)
- [._set_order_state](_set_order_state.md) (18 shared connections)
- [.sync_trades_from_broker](sync_trades_from_broker.md) (9 shared connections)
- [Order Execution](Order_Execution.md) (8 shared connections)
- [._broker_position_row_for_intent](_broker_position_row_for_intent.md) (6 shared connections)
- [DhanBroker](DhanBroker.md) (2 shared connections)
- [dhan/broker.py](dhan-broker.py.md) (2 shared connections)
- [Component Details](Component_Details.md) (2 shared connections)
- [ExecutionValidator](ExecutionValidator.md) (2 shared connections)
- [RunMode](RunMode.md) (1 shared connections)
- [GttFallbackWatch](GttFallbackWatch.md) (1 shared connections)
- [DeltaBroker](DeltaBroker.md) (1 shared connections)

## Source Files

- `core/broker/internal/dhan/broker.py`
- `core/orderExecution/order_router.py`
- `docs/ORDER_LOGGING_PIPELINE.md`
- `docs/oms_flow.md`

## Audit Trail

- EXTRACTED: 173 (94%)
- INFERRED: 11 (6%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*