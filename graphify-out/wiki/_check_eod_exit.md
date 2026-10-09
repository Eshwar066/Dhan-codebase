# ._check_eod_exit

> 22 nodes

## Key Concepts

- **._check_eod_exit()** (8 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`
- **dhanhq()** (7 connections) — `core/library/dhanhq_tradehull_compat.py`
- **._check_tp_sl()** (7 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`
- **._get_structure_capital()** (7 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`
- **._calculate_structure_pnl()** (5 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`
- **._get_structure_positions()** (5 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`
- **._find_hedge_by_structure()** (4 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`
- **._get_current_premium()** (4 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`
- **._is_after_3pm()** (4 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`
- **.should_exit()** (4 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`
- **.calculate_margin_dhan()** (3 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`
- **4️⃣ EDGE CASES & BOUNDARY CONDITIONS** (2 connections) — `NiftyDOS_Test_Scenarios.md`
- **_DhanhqClient** (1 connections)
- **Get current premium for position.** (1 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`
- **Get both MAIN and HEDGE positions for a structure.** (1 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`
- **Find hedge position by matching structure characteristics. Hedge is a LONG…** (1 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`
- **Calculate total capital/margin deployed for the hedged structure. First tries…** (1 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`
- **Calculate combined P&L for the hedged structure (MAIN + HEDGE). MAIN: Short…** (1 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`
- **Check if TP or SL hit based on structure capital (margin deployed). Uses…** (1 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`
- **Check if after 3pm and |P&L| >= eod_exit_pct of capital deployed.** (1 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`
- **Calculate margin using Dhan's margin_calculator_multi API.** (1 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`
- **Check if candle CLOSE time is after 3:00 PM (for EOD exit).** (1 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`

## Relationships

- [NiftyDOS](NiftyDOS.md) (11 shared connections)
- [._check_and_execute_pending_reentries](_check_and_execute_pending_reentries.md) (3 shared connections)
- [DhanContext](DhanContext.md) (2 shared connections)
- [.get_login](get_login.md) (1 shared connections)
- [logging.py](logging.py.md) (1 shared connections)
- [main](main.md) (1 shared connections)
- [Tradehull](Tradehull.md) (1 shared connections)
- [._attempt_sl_reentry](_attempt_sl_reentry.md) (1 shared connections)
- [NiftyDOS Strategy - Complete Scenarios & Test Cases](NiftyDOS_Strategy_-_Complete_Scenarios_&_Test_Cases.md) (1 shared connections)

## Source Files

- `NiftyDOS_Test_Scenarios.md`
- `core/library/dhanhq_tradehull_compat.py`
- `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`

## Audit Trail

- EXTRACTED: 42 (91%)
- INFERRED: 4 (9%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*