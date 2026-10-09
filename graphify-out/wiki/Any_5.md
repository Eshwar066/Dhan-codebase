# Any

> 33 nodes

## Key Concepts

- **Any** (45 connections)
- **.enrich_candle_for_strategy()** (29 connections) — `core/engine/indicator_manager.py`
- **._compute_adx_columns()** (5 connections) — `core/engine/indicator_manager.py`
- **._compute_sma_columns()** (5 connections) — `core/engine/indicator_manager.py`
- **._compute_supertrend_columns()** (5 connections) — `core/engine/indicator_manager.py`
- **._strategy_persisted_indicator_keys()** (5 connections) — `core/engine/indicator_manager.py`
- **._strategy_uses_indicator_history()** (5 connections) — `core/engine/indicator_manager.py`
- **._compute_rsi_columns()** (4 connections) — `core/engine/indicator_manager.py`
- **.get_recent_enriched_candles()** (4 connections) — `core/engine/indicator_manager.py`
- **._indicator_row_for_candle()** (4 connections) — `core/engine/indicator_manager.py`
- **._key_strategy_symbol_tf()** (4 connections) — `core/engine/indicator_manager.py`
- **._shared_indicator_signature()** (4 connections) — `core/engine/indicator_manager.py`
- **._strategy_adx_params()** (4 connections) — `core/engine/indicator_manager.py`
- **._strategy_requires_rsi()** (4 connections) — `core/engine/indicator_manager.py`
- **._strategy_sma_lengths()** (4 connections) — `core/engine/indicator_manager.py`
- **._strategy_supertrend_params()** (4 connections) — `core/engine/indicator_manager.py`
- **.indicator_window_size()** (3 connections) — `core/engine/indicator_manager.py`
- **.set_structure_session_exchange()** (3 connections) — `core/strategies/market_structure_mixin.py`
- **How it works:** (3 connections) — `NiftyDOS_Test_Scenarios.md`
- **.__init__()** (2 connections) — `core/engine/indicator_manager.py`
- **._row_has_confirmed_structure()** (2 connections) — `core/engine/indicator_manager.py`
- **._to_ist_iso()** (2 connections) — `core/engine/indicator_manager.py`
- **Return the indicator dataframe row matching the live candle bar open time.** (1 connections) — `core/engine/indicator_manager.py`
- **Last ``max_rows`` enriched bars for strategy eval (mirrors backtest candle…** (1 connections) — `core/engine/indicator_manager.py`
- **Compute full RSI/prev_RSI columns for strategies that explicitly require RSI.** (1 connections) — `core/engine/indicator_manager.py`
- *... and 8 more nodes in this community*

## Relationships

- [IndicatorManager](IndicatorManager.md) (30 shared connections)
- [._bootstrap_base_candle_state](_bootstrap_base_candle_state.md) (7 shared connections)
- [._collect_candle_closed_rows_from_logs](_collect_candle_closed_rows_from_logs.md) (7 shared connections)
- [._sanitize_delta_ohlc_df](_sanitize_delta_ohlc_df.md) (6 shared connections)
- [TestExtraTimeframeLiveAppend](TestExtraTimeframeLiveAppend.md) (4 shared connections)
- [._load_rsi_history_rows](_load_rsi_history_rows.md) (4 shared connections)
- [indicator_helpers.py](indicator_helpers.py.md) (2 shared connections)
- [test_structure.py](test_structure.py.md) (1 shared connections)
- [MarketStructureConfig](MarketStructureConfig.md) (1 shared connections)
- [NiftyDOS Strategy - Complete Scenarios & Test Cases](NiftyDOS_Strategy_-_Complete_Scenarios_&_Test_Cases.md) (1 shared connections)

## Source Files

- `NiftyDOS_Test_Scenarios.md`
- `core/engine/indicator_manager.py`
- `core/strategies/market_structure_mixin.py`

## Audit Trail

- EXTRACTED: 109 (97%)
- INFERRED: 3 (3%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*