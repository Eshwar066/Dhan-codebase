# .symbol_underlying_root

> 9 nodes

## Key Concepts

- **.symbol_underlying_root()** (6 connections) — `core/orderExecution/position_manager.py`
- **._claim_strategy_for_symbol()** (5 connections) — `core/orderExecution/position_manager.py`
- **.strategy_may_claim_symbol()** (5 connections) — `core/orderExecution/position_manager.py`
- **._ownership_row_compatible_with_folder()** (4 connections) — `core/orderExecution/position_manager.py`
- **.test_btst_may_not_claim_nifty()** (2 connections) — `core/orderExecution/test_ownership_claim_guard.py`
- **.test_symbol_underlying_root_banknifty_before_nifty()** (2 connections) — `core/orderExecution/test_ownership_claim_guard.py`
- **Resolve ownership stamp for a broker-adopted / empty-strategy leg. ``strategy``…** (1 connections) — `core/orderExecution/position_manager.py`
- **Best-effort underlying root (BANKNIFTY before NIFTY).** (1 connections) — `core/orderExecution/position_manager.py`
- **Drop poisoned rows (e.g. NIFTY PE parked under BankNiftyBTST CSV).** (1 connections) — `core/orderExecution/position_manager.py`

## Relationships

- [PositionManager](PositionManager.md) (4 shared connections)
- [.reconcile_with_broker](reconcile_with_broker.md) (3 shared connections)
- [_pm](_pm.md) (2 shared connections)

## Source Files

- `core/orderExecution/position_manager.py`
- `core/orderExecution/test_ownership_claim_guard.py`

## Audit Trail

- EXTRACTED: 18 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*