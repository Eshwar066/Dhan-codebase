# Any

> 7 nodes

## Key Concepts

- **.get_expiry_list()** (3 connections) — `core/models/strategy_context.py`
- **.get_recent_candles()** (3 connections) — `core/models/strategy_context.py`
- **.get_selected_expiry()** (3 connections) — `core/models/strategy_context.py`
- **Any** (3 connections)
- **Safe access for expiry_list (may not be set yet).** (1 connections) — `core/models/strategy_context.py`
- **Safe access for selected_expiry.** (1 connections) — `core/models/strategy_context.py`
- **Last n candles for current symbol (including current). Empty if not provided by…** (1 connections) — `core/models/strategy_context.py`

## Relationships

- [StrategyContext](StrategyContext.md) (3 shared connections)

## Source Files

- `core/models/strategy_context.py`

## Audit Trail

- EXTRACTED: 9 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*