# StrategyContext

> 28 nodes

## Key Concepts

- **StrategyContext** (42 connections) — `core/models/strategy_context.py`
- **BaseAdapter** (12 connections) — `core/data/adapters/base.py`
- **KotakAdapter** (11 connections) — `core/data/adapters/kotak_adapter.py`
- **DhanAdapter** (10 connections) — `core/data/adapters/dhan_adapter.py`
- **data_router.py** (10 connections) — `core/data/data_router.py`
- **NSEAdapter** (9 connections) — `core/data/adapters/nse_adapter.py`
- **kotak_adapter.py** (9 connections) — `core/data/adapters/kotak_adapter.py`
- **adapters/base.py** (8 connections) — `core/data/adapters/base.py`
- **dhan_adapter.py** (8 connections) — `core/data/adapters/dhan_adapter.py`
- **nse_adapter.py** (7 connections) — `core/data/adapters/nse_adapter.py`
- **.get_option_chain()** (4 connections) — `core/data/adapters/dhan_adapter.py`
- **.__init__()** (4 connections) — `core/data/data_router.py`
- **.build_context_only()** (3 connections) — `core/engine/base_engine.py`
- **.get_expiries()** (2 connections) — `core/data/adapters/dhan_adapter.py`
- **.get_expiries()** (2 connections) — `core/data/adapters/kotak_adapter.py`
- **.get_historical_option_chain()** (2 connections) — `core/data/adapters/kotak_adapter.py`
- **.get_expiries()** (2 connections) — `core/data/adapters/nse_adapter.py`
- **.get_historical_option_chain()** (2 connections) — `core/data/adapters/nse_adapter.py`
- **.get_option_chain()** (2 connections) — `core/data/adapters/nse_adapter.py`
- **ABC** (2 connections)
- **.get_expiries()** (1 connections) — `core/data/adapters/base.py`
- **.get_historical_option_chain()** (1 connections) — `core/data/adapters/base.py`
- **.get_option_chain()** (1 connections) — `core/data/adapters/base.py`
- **.__init__()** (1 connections) — `core/data/adapters/base.py`
- **Kotak Neo adapter for live option chains (DHAN-shaped DataFrame contract).** (1 connections) — `core/data/adapters/kotak_adapter.py`
- *... and 3 more nodes in this community*

## Relationships

- [typing](typing.md) (22 shared connections)
- [option_buildup_scheduler.py](option_buildup_scheduler.py.md) (10 shared connections)
- [.as_calendar_date](as_calendar_date.md) (6 shared connections)
- [factory.py](factory.py.md) (4 shared connections)
- [Any](Any.md) (3 shared connections)
- [OptionBuildup](OptionBuildup.md) (2 shared connections)
- [lag_diag.py](lag_diag.py.md) (1 shared connections)
- [RunMode](RunMode.md) (1 shared connections)
- [Order Execution](Order_Execution.md) (1 shared connections)
- [kotak_data_provider.py](kotak_data_provider.py.md) (1 shared connections)

## Source Files

- `core/data/adapters/base.py`
- `core/data/adapters/dhan_adapter.py`
- `core/data/adapters/kotak_adapter.py`
- `core/data/adapters/nse_adapter.py`
- `core/data/data_router.py`
- `core/engine/base_engine.py`
- `core/models/strategy_context.py`

## Audit Trail

- EXTRACTED: 92 (88%)
- INFERRED: 13 (12%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*