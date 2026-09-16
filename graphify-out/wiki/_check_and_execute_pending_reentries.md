# ._check_and_execute_pending_reentries

> 19 nodes

## Key Concepts

- **._check_and_execute_pending_reentries()** (8 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`
- **._check_tp_sl_on_5min()** (8 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`
- **._strategy_open_positions()** (8 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`
- **._structure_still_open_at_broker()** (7 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`
- **NiftyDOS — Graph Context (for graphify / Cursor)** (7 connections) — `core/strategies/IBBM/NiftyDOS/NIFTYDOS_GRAPH_CONTEXT.md`
- **Exit / reentry pipeline** (6 connections) — `core/strategies/IBBM/NiftyDOS/NIFTYDOS_GRAPH_CONTEXT.md`
- **Strategy-scoped broker flat checks** (6 connections) — `core/strategies/IBBM/NiftyDOS/NIFTYDOS_GRAPH_CONTEXT.md`
- **._finalize_pending_exits()** (5 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`
- **._is_structure_flat_at_broker()** (4 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`
- **._underlying_symbol()** (2 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`
- **IST timestamps** (2 connections) — `core/strategies/IBBM/NiftyDOS/NIFTYDOS_GRAPH_CONTEXT.md`
- **Signal gating (`should_evaluate` + `eval_signal_log_message`)** (2 connections) — `core/strategies/IBBM/NiftyDOS/NIFTYDOS_GRAPH_CONTEXT.md`
- **NIFTYDOS_GRAPH_CONTEXT.md** (1 connections) — `core/strategies/IBBM/NiftyDOS/NIFTYDOS_GRAPH_CONTEXT.md`
- **Regenerate graph** (1 connections) — `core/strategies/IBBM/NiftyDOS/NIFTYDOS_GRAPH_CONTEXT.md`
- **Tests** (1 connections) — `core/strategies/IBBM/NiftyDOS/NIFTYDOS_GRAPH_CONTEXT.md`
- **Drop TP/SL tracking once broker is flat; keep SL reentry flags for 30m eval.** (1 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`
- **Check TP/SL and EOD exit on 5-min candle and return exit intents if hit.** (1 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`
- **Check if positions with pending reentry have been closed at broker. If closed,…** (1 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`
- **Open broker legs for this strategy only (ignore other strategies on same…** (1 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`

## Relationships

- [._attempt_sl_reentry](_attempt_sl_reentry.md) (10 shared connections)
- [NiftyDOS](NiftyDOS.md) (9 shared connections)
- [._check_eod_exit](_check_eod_exit.md) (3 shared connections)
- [._candle_ts_ist](_candle_ts_ist.md) (1 shared connections)
- [.sync_tracking_from_broker](sync_tracking_from_broker.md) (1 shared connections)

## Source Files

- `core/strategies/IBBM/NiftyDOS/NIFTYDOS_GRAPH_CONTEXT.md`
- `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`

## Audit Trail

- EXTRACTED: 36 (75%)
- INFERRED: 12 (25%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*