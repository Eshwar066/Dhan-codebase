# RiskManager

> 21 nodes

## Key Concepts

- **RiskManager** (21 connections) — `core/orderExecution/risk_manager.py`
- **.allow_intent()** (11 connections) — `core/orderExecution/risk_manager.py`
- **._is_short_option()** (3 connections) — `core/orderExecution/risk_manager.py`
- **._open_positions_count()** (3 connections) — `core/orderExecution/risk_manager.py`
- **.record_execution_source()** (3 connections) — `core/orderExecution/risk_manager.py`
- **._cooldown_ok()** (2 connections) — `core/orderExecution/risk_manager.py`
- **._direction_ok()** (2 connections) — `core/orderExecution/risk_manager.py`
- **._get_event_time()** (2 connections) — `core/orderExecution/risk_manager.py`
- **.__init__()** (2 connections) — `core/orderExecution/risk_manager.py`
- **._log_block()** (2 connections) — `core/orderExecution/risk_manager.py`
- **.record_realized_pnl()** (2 connections) — `core/orderExecution/risk_manager.py`
- **.reset_daily()** (2 connections) — `core/orderExecution/risk_manager.py`
- **.trigger_kill_switch()** (2 connections) — `core/orderExecution/risk_manager.py`
- **Any** (2 connections)
- **Call when a position is closed and PnL is realized (e.g. from PositionManager).** (1 connections) — `core/orderExecution/risk_manager.py`
- **Aggregate exits by source for risk analytics (liquidation rate, forced vs…** (1 connections) — `core/orderExecution/risk_manager.py`
- **Reset daily PnL (call at start of new trading day).** (1 connections) — `core/orderExecution/risk_manager.py`
- **intent: OrderIntent object Exit/force exit always allowed. Entry blocked if…** (1 connections) — `core/orderExecution/risk_manager.py`
- **True if intent is ENTRY + SELL on an option (short option).** (1 connections) — `core/orderExecution/risk_manager.py`
- **Count open positions relevant for `max_open_positions`. We intentionally count…** (1 connections) — `core/orderExecution/risk_manager.py`
- **Block all new entry intents. Log critical event. Exits remain allowed.** (1 connections) — `core/orderExecution/risk_manager.py`

## Relationships

- [.create_live_engine](create_live_engine.md) (3 shared connections)
- [test_economic_events.py](test_economic_events.py.md) (3 shared connections)
- [factory.py](factory.py.md) (3 shared connections)
- [EventBlackoutGuard](EventBlackoutGuard.md) (2 shared connections)
- [Live Engine](Live_Engine.md) (1 shared connections)
- [Order Execution](Order_Execution.md) (1 shared connections)
- [.sync_trades_from_broker](sync_trades_from_broker.md) (1 shared connections)

## Source Files

- `core/orderExecution/risk_manager.py`

## Audit Trail

- EXTRACTED: 34 (85%)
- INFERRED: 6 (15%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*