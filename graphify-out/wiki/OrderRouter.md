# OrderRouter

> 38 nodes

## Key Concepts

- **OrderRouter** (138 connections) — `core/orderExecution/order_router.py`
- **.verify_open_orders_with_broker()** (17 connections) — `core/orderExecution/order_router.py`
- **._normalize_broker_order_for_recon()** (8 connections) — `core/orderExecution/order_router.py`
- **._persist_order_state()** (8 connections) — `core/orderExecution/order_router.py`
- **._try_resolve_cancelled_bracket_sibling()** (7 connections) — `core/orderExecution/order_router.py`
- **.__init__()** (6 connections) — `core/orderExecution/order_router.py`
- **._rebuild_order_state_cache()** (6 connections) — `core/orderExecution/order_router.py`
- **._reconcile_stale_bracket_order_states_on_startup()** (6 connections) — `core/orderExecution/order_router.py`
- **._load_order_state()** (5 connections) — `core/orderExecution/order_router.py`
- **._merge_forever_orders_for_recon()** (5 connections) — `core/orderExecution/order_router.py`
- **._order_state_file_for_strategy()** (5 connections) — `core/orderExecution/order_router.py`
- **._read_order_state_file()** (5 connections) — `core/orderExecution/order_router.py`
- **._resolve_intent_id_from_broker_order()** (5 connections) — `core/orderExecution/order_router.py`
- **._intent_strategy_id()** (4 connections) — `core/orderExecution/order_router.py`
- **._mark_intent_cancelled()** (4 connections) — `core/orderExecution/order_router.py`
- **._order_state_files_to_load()** (4 connections) — `core/orderExecution/order_router.py`
- **._broker_tag_matches_intent()** (3 connections) — `core/orderExecution/order_router.py`
- **._intent_matched_on_broker_open()** (3 connections) — `core/orderExecution/order_router.py`
- **._persisted_sent_has_filled_bracket_sibling()** (3 connections) — `core/orderExecution/order_router.py`
- **.prune_terminal_order_states()** (3 connections) — `core/orderExecution/order_router.py`
- **Path** (3 connections)
- **._intent_is_terminal_filled()** (2 connections) — `core/orderExecution/order_router.py`
- **._prepare_intent_reorder()** (2 connections) — `core/orderExecution/order_router.py`
- **.reset_oms_session_boundary()** (2 connections) — `core/orderExecution/order_router.py`
- **.resolve_intent_id_by_broker_order_id()** (2 connections) — `core/orderExecution/order_router.py`
- *... and 13 more nodes in this community*

## Relationships

- [Any](Any.md) (37 shared connections)
- [._set_order_state](_set_order_state.md) (21 shared connections)
- [.sync_trades_from_broker](sync_trades_from_broker.md) (14 shared connections)
- [RunMode](RunMode.md) (11 shared connections)
- [Order Execution](Order_Execution.md) (11 shared connections)
- [ExecutionValidator](ExecutionValidator.md) (7 shared connections)
- [._broker_position_row_for_intent](_broker_position_row_for_intent.md) (7 shared connections)
- [.create_live_engine](create_live_engine.md) (3 shared connections)
- [._refresh_stale_limit_orders](_refresh_stale_limit_orders.md) (3 shared connections)
- [ReentryAtCostBook](ReentryAtCostBook.md) (3 shared connections)
- [factory.py](factory.py.md) (2 shared connections)
- [test_order_repricing.py](test_order_repricing.py.md) (2 shared connections)

## Source Files

- `core/orderExecution/order_router.py`

## Audit Trail

- EXTRACTED: 179 (87%)
- INFERRED: 27 (13%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*