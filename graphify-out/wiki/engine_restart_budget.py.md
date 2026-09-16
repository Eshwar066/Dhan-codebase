# engine_restart_budget.py

> 13 nodes

## Key Concepts

- **engine_restart_budget.py** (12 connections) — `core/utils/engine_restart_budget.py`
- **on_startup_failure()** (7 connections) — `core/utils/engine_restart_budget.py`
- **ExitBudgetExceeded** (6 connections) — `core/utils/engine_restart_budget.py`
- **reset_startup_success()** (5 connections) — `core/utils/engine_restart_budget.py`
- **_save_state()** (5 connections) — `core/utils/engine_restart_budget.py`
- **_load_state()** (4 connections) — `core/utils/engine_restart_budget.py`
- **_state_path()** (3 connections) — `core/utils/engine_restart_budget.py`
- **Any** (2 connections)
- **Exception** (1 connections)
- **Track consecutive startup failures per engine_id and cap automated restarts.…** (1 connections) — `core/utils/engine_restart_budget.py`
- **Raised when startup failure budget is exhausted (caller should exit 0).** (1 connections) — `core/utils/engine_restart_budget.py`
- **Clear failure counter after a successful startup (e.g. reconciliation passed).** (1 connections) — `core/utils/engine_restart_budget.py`
- **Record a startup failure. If budget exceeded, send Telegram once and raise…** (1 connections) — `core/utils/engine_restart_budget.py`

## Relationships

- [factory.py](factory.py.md) (4 shared connections)
- [logging.py](logging.py.md) (3 shared connections)
- [.start](start.md) (2 shared connections)
- [LiveEngine](LiveEngine.md) (1 shared connections)
- [typing](typing.md) (1 shared connections)

## Source Files

- `core/utils/engine_restart_budget.py`

## Audit Trail

- EXTRACTED: 29 (97%)
- INFERRED: 1 (3%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*