# PositionManager

> 25 nodes

## Key Concepts

- **PositionManager** (63 connections) — `core/orderExecution/position_manager.py`
- **.has_open_main_leg()** (6 connections) — `core/orderExecution/position_manager.py`
- **.get_open_positions()** (4 connections) — `core/orderExecution/position_manager.py`
- **.get_qty()** (4 connections) — `core/orderExecution/position_manager.py`
- **.has_open_structure()** (4 connections) — `core/orderExecution/position_manager.py`
- **.get_structure_slice()** (3 connections) — `core/orderExecution/position_manager.py`
- **.get_hedge_for()** (2 connections) — `core/orderExecution/position_manager.py`
- **.has_structure_slice_open()** (2 connections) — `core/orderExecution/position_manager.py`
- **.is_flat()** (2 connections) — `core/orderExecution/position_manager.py`
- **.is_long()** (2 connections) — `core/orderExecution/position_manager.py`
- **.is_short()** (2 connections) — `core/orderExecution/position_manager.py`
- **.note_trade_led_fill()** (2 connections) — `core/orderExecution/position_manager.py`
- **.rebuild_position_metadata_from_intent_store()** (2 connections) — `core/orderExecution/position_manager.py`
- **.rebuild_structure_slices_from_intent_store()** (2 connections) — `core/orderExecution/position_manager.py`
- **.should_emit_forced_exit()** (2 connections) — `core/orderExecution/position_manager.py`
- **.realized_pnl()** (1 connections) — `core/orderExecution/position_manager.py`
- **.snapshot()** (1 connections) — `core/orderExecution/position_manager.py`
- **.total_exposure()** (1 connections) — `core/orderExecution/position_manager.py`
- **.unrealized_pnl()** (1 connections) — `core/orderExecution/position_manager.py`
- **True if an open MAIN already blocks a new entry for this LEAPS leg family.…** (1 connections) — `core/orderExecution/position_manager.py`
- **Find hedge position linked to a main position. Matching is done via: - same…** (1 connections) — `core/orderExecution/position_manager.py`
- **Mark symbol as recently updated from fills API; reconcile_with_broker skips…** (1 connections) — `core/orderExecution/position_manager.py`
- **Debounce on_forced_exit for partial external/liquidation bursts; always emit on…** (1 connections) — `core/orderExecution/position_manager.py`
- **Best-effort: ENTRY rows in store (FILLED or pending GTT) → position_metadata by…** (1 connections) — `core/orderExecution/position_manager.py`
- **Rebuild MAIN ENTRY slices from FILLED intents (intent-centric duplicate + risk…** (1 connections) — `core/orderExecution/position_manager.py`

## Relationships

- [.reconcile_with_broker](reconcile_with_broker.md) (10 shared connections)
- [RunMode](RunMode.md) (8 shared connections)
- [.create_live_engine](create_live_engine.md) (4 shared connections)
- [.symbol_underlying_root](symbol_underlying_root.md) (4 shared connections)
- [normalize_fill_side](normalize_fill_side.md) (3 shared connections)
- [factory.py](factory.py.md) (2 shared connections)
- [typing](typing.md) (2 shared connections)
- [TradeLogger](TradeLogger.md) (2 shared connections)
- [_pm](_pm.md) (2 shared connections)
- [Position](Position.md) (2 shared connections)
- [ReentryAtCostBook](ReentryAtCostBook.md) (2 shared connections)
- [LeapsQuarterly](LeapsQuarterly.md) (2 shared connections)

## Source Files

- `core/orderExecution/position_manager.py`

## Audit Trail

- EXTRACTED: 62 (77%)
- INFERRED: 19 (23%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*