# ReentryAtCostBook

> 45 nodes

## Key Concepts

- **ReentryAtCostBook** (34 connections) — `core/orderExecution/reentry_at_cost_book.py`
- **ReentryAtCostWatch** (10 connections) — `core/orderExecution/reentry_at_cost_book.py`
- **._try_place()** (10 connections) — `core/orderExecution/reentry_at_cost_book.py`
- **TestBrokerNoOpenPositionSync** (9 connections) — `core/orderExecution/test_broker_no_open_position_sync.py`
- **._build_entry_intent()** (9 connections) — `core/orderExecution/reentry_at_cost_book.py`
- **.maybe_arm_from_main_sl()** (9 connections) — `core/orderExecution/reentry_at_cost_book.py`
- **._save()** (9 connections) — `core/orderExecution/reentry_at_cost_book.py`
- **Any** (8 connections)
- **._log()** (7 connections) — `core/orderExecution/reentry_at_cost_book.py`
- **._metadata_for_reentry()** (6 connections) — `core/orderExecution/reentry_at_cost_book.py`
- **.on_position_opened()** (6 connections) — `core/orderExecution/reentry_at_cost_book.py`
- **._prune_expired()** (6 connections) — `core/orderExecution/reentry_at_cost_book.py`
- **._contract_has_open_main()** (5 connections) — `core/orderExecution/reentry_at_cost_book.py`
- **.has_pending()** (5 connections) — `core/orderExecution/reentry_at_cost_book.py`
- **.tick()** (5 connections) — `core/orderExecution/reentry_at_cost_book.py`
- **_parse_expiry_code()** (4 connections) — `core/orderExecution/reentry_at_cost_book.py`
- **._load()** (4 connections) — `core/orderExecution/reentry_at_cost_book.py`
- **._resolve_instrument()** (4 connections) — `core/orderExecution/reentry_at_cost_book.py`
- **.stop_for_trading_symbol()** (4 connections) — `core/orderExecution/reentry_at_cost_book.py`
- **_FakePos** (3 connections) — `core/orderExecution/test_broker_no_open_position_sync.py`
- **.cancel_for_structure()** (3 connections) — `core/orderExecution/reentry_at_cost_book.py`
- **._current_premium()** (3 connections) — `core/orderExecution/reentry_at_cost_book.py`
- **.__init__()** (3 connections) — `core/orderExecution/reentry_at_cost_book.py`
- **._watch_from_dict()** (3 connections) — `core/orderExecution/reentry_at_cost_book.py`
- **._watch_to_dict()** (3 connections) — `core/orderExecution/reentry_at_cost_book.py`
- *... and 20 more nodes in this community*

## Relationships

- [RunMode](RunMode.md) (16 shared connections)
- [OrderRouter](OrderRouter.md) (3 shared connections)
- [unpack_strategy_meta](unpack_strategy_meta.md) (3 shared connections)
- [PositionManager](PositionManager.md) (2 shared connections)
- [LiveEngine](LiveEngine.md) (1 shared connections)
- [IntentStore](IntentStore.md) (1 shared connections)
- [NeoAPI](NeoAPI.md) (1 shared connections)
- [LiveEngineHelpersMixin](LiveEngineHelpersMixin.md) (1 shared connections)
- [._maybe_tick_reentry_at_cost](_maybe_tick_reentry_at_cost.md) (1 shared connections)
- [reentry_at_cost.py](reentry_at_cost.py.md) (1 shared connections)
- [Order Execution](Order_Execution.md) (1 shared connections)

## Source Files

- `core/orderExecution/reentry_at_cost_book.py`
- `core/orderExecution/test_broker_no_open_position_sync.py`
- `core/orderExecution/test_reentry_at_cost_book.py`

## Audit Trail

- EXTRACTED: 102 (87%)
- INFERRED: 15 (13%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*