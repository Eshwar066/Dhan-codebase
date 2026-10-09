# TestExtraTimeframeLiveAppend

> 15 nodes

## Key Concepts

- **TestExtraTimeframeLiveAppend** (11 connections) — `core/engine/tests/test_extra_timeframe_live_append.py`
- **._resolve_enrich_timeframe()** (6 connections) — `core/engine/indicator_manager.py`
- **._strategy_owns_timeframe()** (6 connections) — `core/engine/indicator_manager.py`
- **.test_restore_strategies_after_reconcile_all_strategies()** (3 connections) — `core/engine/tests/test_extra_timeframe_live_append.py`
- **.test_enrich_passes_extra_tf_into_append_path()** (2 connections) — `core/engine/tests/test_extra_timeframe_live_append.py`
- **.test_enrich_skips_unowned_explicit_timeframe()** (2 connections) — `core/engine/tests/test_extra_timeframe_live_append.py`
- **.test_evaluate_parallel_includes_extra_timeframe_owner()** (2 connections) — `core/engine/tests/test_extra_timeframe_live_append.py`
- **.test_resolve_enrich_timeframe_prefers_owned_bar_tf()** (2 connections) — `core/engine/tests/test_extra_timeframe_live_append.py`
- **.test_strategy_owns_primary_and_extra()** (2 connections) — `core/engine/tests/test_extra_timeframe_live_append.py`
- **.test_candle_strategy_for_matches_extra_timeframes()** (1 connections) — `core/engine/tests/test_extra_timeframe_live_append.py`
- **dos_restore()** (1 connections) — `core/engine/tests/test_extra_timeframe_live_append.py`
- **True when ``timeframe`` is the strategy primary TF or an ``extra_timeframes``…** (1 connections) — `core/engine/indicator_manager.py`
- **Prefer the closed-bar TF when the strategy owns it (primary or…** (1 connections) — `core/engine/indicator_manager.py`
- **Non-primary strategies (e.g. DOS) must receive restore + ctx.** (1 connections) — `core/engine/tests/test_extra_timeframe_live_append.py`
- **4h BarClosed must evaluate DOS (extra_timeframes), not only primary TF==4h.** (1 connections) — `core/engine/tests/test_extra_timeframe_live_append.py`

## Relationships

- [IndicatorManager](IndicatorManager.md) (5 shared connections)
- [Any](Any.md) (4 shared connections)
- [RunMode](RunMode.md) (1 shared connections)
- [._bootstrap_base_candle_state](_bootstrap_base_candle_state.md) (1 shared connections)
- [LiveEngine](LiveEngine.md) (1 shared connections)

## Source Files

- `core/engine/indicator_manager.py`
- `core/engine/tests/test_extra_timeframe_live_append.py`

## Audit Trail

- EXTRACTED: 24 (89%)
- INFERRED: 3 (11%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*