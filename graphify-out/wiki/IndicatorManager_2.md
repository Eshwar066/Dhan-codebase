# IndicatorManager

> God node · 69 connections · `core/engine/indicator_manager.py`

**Community:** [IndicatorManager](IndicatorManager.md)

## Connections by Relation

### calls
- .__init__() `EXTRACTED`
- .test_enrich_passes_extra_tf_into_append_path() `EXTRACTED`
- .test_enrich_skips_unowned_explicit_timeframe() `EXTRACTED`

### contains
- indicator_manager.py `EXTRACTED`

### imports
- live_engine.py `EXTRACTED`
- test_extra_timeframe_live_append.py `EXTRACTED`

### method
- .enrich_candle_for_strategy() `EXTRACTED`
- ._bootstrap_base_candle_state() `EXTRACTED`
- ._append_rsi_history_log() `EXTRACTED`
- ._sanitize_delta_ohlc_df() `EXTRACTED`
- ._load_candles_from_rsi_history() `EXTRACTED`
- ._collect_candle_closed_rows_from_logs() `EXTRACTED`
- ._merge_today_live_candles() `EXTRACTED`
- ._load_candles_from_logs() `EXTRACTED`
- ._structure_confirm_delay_bars() `EXTRACTED`
- ._structure_confirm_tail_rows() `EXTRACTED`
- ._strategy_owns_timeframe() `EXTRACTED`
- ._resolve_enrich_timeframe() `EXTRACTED`
- ._load_rsi_history_rows() `EXTRACTED`
- ._merge_rsi_history_into_base_df() `EXTRACTED`
- ._candle_rows_to_sorted_df() `EXTRACTED`
- ._drop_future_bars() `EXTRACTED`
- ._load_today_live_candles() `EXTRACTED`
- ._load_today_from_indicator_history() `EXTRACTED`
- ._finalize_delta_base_df() `EXTRACTED`
- ._strip_same_day_bars() `EXTRACTED`
- *…and 36 more `method` connection(s) not listed (lowest-degree first to go)*

### rationale_for
- Shared indicator layer for live engine. Maintains per-(symbol,timeframe) base… `EXTRACTED`

### references
- [Runtime notes](Runtime_notes.md) `INFERRED`
- How it works: `INFERRED`
- Indicator bootstrap `INFERRED`
- Yahoo NIFTY indicator history (optional) `INFERRED`

### uses
- [LiveEngine](LiveEngine.md) `INFERRED`
- [TestExtraTimeframeLiveAppend](TestExtraTimeframeLiveAppend.md) `INFERRED`

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*