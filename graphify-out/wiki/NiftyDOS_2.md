# NiftyDOS

> God node · 104 connections · `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`

**Community:** [NiftyDOS](NiftyDOS.md)

## Connections by Relation

### calls
- .test_should_evaluate_false_when_supertrend_unchanged() `EXTRACTED`
- .test_should_evaluate_true_at_945_entry() `EXTRACTED`
- .test_should_evaluate_true_for_sl_reentry() `EXTRACTED`
- .test_should_evaluate_true_on_supertrend_flip() `EXTRACTED`
- .test_should_evaluate_5min_only_for_monitoring_or_reentry() `EXTRACTED`
- .setUp() `EXTRACTED`
- .test_has_open_main_ignores_other_strategies() `EXTRACTED`
- .test_structure_flat_ignores_other_strategy_positions() `EXTRACTED`
- .test_structure_still_open_only_for_same_strategy() `EXTRACTED`

### contains
- NiftyDOS.py `EXTRACTED`

### imports
- registry_entries.py `EXTRACTED`
- test_nifty_dos_critical_fixes.py `EXTRACTED`
- NiftyDOS/__init__.py `EXTRACTED`

### inherits
- [IndiaMktMixins](IndiaMktMixins.md) `EXTRACTED`
- BaseStrategy `EXTRACTED`

### method
- ._attempt_sl_reentry() `EXTRACTED`
- ._candle_open_ts_ist() `EXTRACTED`
- .on_candle() `EXTRACTED`
- ._build_entry_intents() `EXTRACTED`
- ._attempt_immediate_reentry() `EXTRACTED`
- ._candle_close_ts_ist() `EXTRACTED`
- .should_evaluate() `EXTRACTED`
- ._attempt_st_flip_reentry() `EXTRACTED`
- ._trade_date() `EXTRACTED`
- ._is_945am() `EXTRACTED`
- ._resolve_main_expiry() `EXTRACTED`
- ._get_supertrend_signal() `EXTRACTED`
- ._eval_signal_reason() `EXTRACTED`
- ._check_eod_exit() `EXTRACTED`
- ._check_tp_sl_on_5min() `EXTRACTED`
- ._check_and_execute_pending_reentries() `EXTRACTED`
- ._is_event_no_trade_day() `EXTRACTED`
- ._strategy_open_positions() `EXTRACTED`
- ._has_open_main_for_strategy() `EXTRACTED`
- ._structure_still_open_at_broker() `EXTRACTED`
- *…and 62 more `method` connection(s) not listed (lowest-degree first to go)*

### rationale_for
- NIFTY Supertrend + MA9 + ADX directional option selling with TP/SL management. `EXTRACTED`

### references
- [Strategy index](Strategy_index.md) `INFERRED`

### uses
- [ExpiryResolver](ExpiryResolver.md) `INFERRED`
- [RunMode](RunMode.md) `INFERRED`
- [Tradehull](Tradehull.md) `INFERRED`
- SessionManager `INFERRED`
- [NiftyDosCriticalFixTests](NiftyDosCriticalFixTests.md) `INFERRED`

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*