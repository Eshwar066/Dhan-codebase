# normalize_fill_side

> 17 nodes

## Key Concepts

- **normalize_fill_side()** (8 connections) — `core/orderExecution/position_manager.py`
- **.on_fill()** (8 connections) — `core/orderExecution/position_manager.py`
- **_fill_clock_for_trade_log()** (7 connections) — `core/orderExecution/position_manager.py`
- **resolve_fill_candle_ts()** (7 connections) — `core/orderExecution/position_manager.py`
- **Any** (7 connections)
- **datetime** (4 connections)
- **Debugging Tips** (4 connections) — `docs/ORDER_LOGGING_PIPELINE.md`
- **.update_fill()** (3 connections) — `core/orderExecution/position_manager.py`
- **.clear_ownership_metadata()** (3 connections) — `core/orderExecution/position_manager.py`
- **wall_clock_ist()** (3 connections) — `core/orderExecution/position_manager.py`
- **.ownership_snapshot()** (2 connections) — `core/orderExecution/position_manager.py`
- **.test_normalize_fill_side()** (2 connections) — `core/orderExecution/test_ownership_claim_guard.py`
- **Instrument** (1 connections)
- **Drop ownership metadata for ``trading_symbol``; return the prior bucket.** (1 connections) — `core/orderExecution/position_manager.py`
- **Return fill/bar time for OMS hooks; IST wall clock for Indian index strategies…** (1 connections) — `core/orderExecution/position_manager.py`
- **Map broker/intent side aliases to BUY/SELL. None if missing or unknown.…** (1 connections) — `core/orderExecution/position_manager.py`
- **Normalize bar/fill time to **IST naive** for trade_log CSV display. Naive…** (1 connections) — `core/orderExecution/position_manager.py`

## Relationships

- [RunMode](RunMode.md) (8 shared connections)
- [.reconcile_with_broker](reconcile_with_broker.md) (4 shared connections)
- [PositionManager](PositionManager.md) (3 shared connections)
- [Position](Position.md) (2 shared connections)
- [_pm](_pm.md) (1 shared connections)
- [Order Logging Pipeline](Order_Logging_Pipeline.md) (1 shared connections)
- [Any](Any.md) (1 shared connections)
- [SimulatedBroker](SimulatedBroker.md) (1 shared connections)

## Source Files

- `core/orderExecution/position_manager.py`
- `core/orderExecution/test_ownership_claim_guard.py`
- `docs/ORDER_LOGGING_PIPELINE.md`

## Audit Trail

- EXTRACTED: 39 (93%)
- INFERRED: 3 (7%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*