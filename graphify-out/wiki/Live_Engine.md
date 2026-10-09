# Live Engine

> 9 nodes

## Key Concepts

- **Live Engine** (7 connections) — `core/engine/readme.md`
- **.is_engine_blocked()** (3 connections) — `core/orderExecution/risk_manager.py`
- **Live vs backtest** (3 connections) — `core/engine/readme.md`
- **Responsibilities** (3 connections) — `core/engine/readme.md`
- **Risk blocks (`risk_manager.is_engine_blocked()`)** (2 connections) — `core/engine/readme.md`
- **engine/readme.md** (1 connections) — `core/engine/readme.md`
- **Related docs** (1 connections) — `core/engine/readme.md`
- **Strategy eval modes (`strategy_eval_modes` / `runtime_spec`)** (1 connections) — `core/engine/readme.md`
- **True if kill switch is triggered. Block new entries; exits still allowed.** (1 connections) — `core/orderExecution/risk_manager.py`

## Relationships

- [RiskManager](RiskManager.md) (1 shared connections)
- [._rest_option_quote](_rest_option_quote.md) (1 shared connections)
- [ExitRolloverService](ExitRolloverService.md) (1 shared connections)
- [BacktestEngine](BacktestEngine.md) (1 shared connections)
- [CandleAggregator](CandleAggregator.md) (1 shared connections)
- [._run_watches](_run_watches.md) (1 shared connections)

## Source Files

- `core/engine/readme.md`
- `core/orderExecution/risk_manager.py`

## Audit Trail

- EXTRACTED: 9 (64%)
- INFERRED: 5 (36%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*