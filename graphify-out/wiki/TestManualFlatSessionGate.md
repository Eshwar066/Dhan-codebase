# TestManualFlatSessionGate

> 8 nodes

## Key Concepts

- **TestManualFlatSessionGate** (8 connections) — `core/orderExecution/test_manual_broker_flat_sync.py`
- **._engine()** (4 connections) — `core/orderExecution/test_manual_broker_flat_sync.py`
- **.test_market_hours_empty_book_clears_and_cancels()** (3 connections) — `core/orderExecution/test_manual_broker_flat_sync.py`
- **.test_nonempty_book_missing_leg_clears_even_outside_hours()** (3 connections) — `core/orderExecution/test_manual_broker_flat_sync.py`
- **.test_outside_hours_empty_book_keeps_metadata()** (3 connections) — `core/orderExecution/test_manual_broker_flat_sync.py`
- **Overnight empty/ambiguous book must NOT clear ownership.** (1 connections) — `core/orderExecution/test_manual_broker_flat_sync.py`
- **In-session empty book = confirmed flat → clear meta + cancel MAIN_SL.** (1 connections) — `core/orderExecution/test_manual_broker_flat_sync.py`
- **Specific leg absent from a real book → confirmed gone (not ambiguous).** (1 connections) — `core/orderExecution/test_manual_broker_flat_sync.py`

## Relationships

- [RunMode](RunMode.md) (2 shared connections)
- [LiveEngine](LiveEngine.md) (1 shared connections)
- [PositionManager](PositionManager.md) (1 shared connections)

## Source Files

- `core/orderExecution/test_manual_broker_flat_sync.py`

## Audit Trail

- EXTRACTED: 11 (79%)
- INFERRED: 3 (21%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*