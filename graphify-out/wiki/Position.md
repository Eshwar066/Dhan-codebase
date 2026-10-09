# Position

> 13 nodes

## Key Concepts

- **Position** (16 connections) — `core/orderExecution/position_manager.py`
- **TestOvernightReconcileSymbolMap** (10 connections) — `core/orderExecution/test_overnight_reconcile_symbol_map.py`
- **TestManualBrokerFlatSync** (9 connections) — `core/orderExecution/test_manual_broker_flat_sync.py`
- **.test_sync_symbol_flat_clears_metadata_when_requested()** (3 connections) — `core/orderExecution/test_manual_broker_flat_sync.py`
- **.test_empty_broker_book_zeros_local_qty_keeps_metadata()** (3 connections) — `core/orderExecution/test_overnight_reconcile_symbol_map.py`
- **.test_space_broker_key_maps_onto_compact_local()** (3 connections) — `core/orderExecution/test_overnight_reconcile_symbol_map.py`
- **.test_adopt_matches_compact_intent_to_space_broker_via_identity()** (2 connections) — `core/orderExecution/test_overnight_reconcile_symbol_map.py`
- **.test_option_identity_matches_compact_and_space()** (2 connections) — `core/orderExecution/test_overnight_reconcile_symbol_map.py`
- **.__init__()** (1 connections) — `core/orderExecution/position_manager.py`
- **.__repr__()** (1 connections) — `core/orderExecution/position_manager.py`
- **.update_risk_metrics()** (1 connections) — `core/orderExecution/position_manager.py`
- **.test_router_cancels_resting_sl_on_manual_flat()** (1 connections) — `core/orderExecution/test_manual_broker_flat_sync.py`
- **_apply()** (1 connections) — `core/orderExecution/test_overnight_reconcile_symbol_map.py`

## Relationships

- [RunMode](RunMode.md) (8 shared connections)
- [Instrument](Instrument.md) (5 shared connections)
- [normalize_fill_side](normalize_fill_side.md) (2 shared connections)
- [.reconcile_with_broker](reconcile_with_broker.md) (2 shared connections)
- [PositionManager](PositionManager.md) (2 shared connections)
- [OrderRouter](OrderRouter.md) (2 shared connections)
- [typing](typing.md) (1 shared connections)
- [.option_identity_key](option_identity_key.md) (1 shared connections)

## Source Files

- `core/orderExecution/position_manager.py`
- `core/orderExecution/test_manual_broker_flat_sync.py`
- `core/orderExecution/test_overnight_reconcile_symbol_map.py`

## Audit Trail

- EXTRACTED: 26 (68%)
- INFERRED: 12 (32%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*