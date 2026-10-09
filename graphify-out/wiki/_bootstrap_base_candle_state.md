# ._bootstrap_base_candle_state

> 12 nodes

## Key Concepts

- **._bootstrap_base_candle_state()** (12 connections) — `core/engine/indicator_manager.py`
- **._load_candles_from_rsi_history()** (8 connections) — `core/engine/indicator_manager.py`
- **._drop_future_bars()** (6 connections) — `core/engine/indicator_manager.py`
- **._strip_same_day_bars()** (5 connections) — `core/engine/indicator_manager.py`
- **._timeframe_to_seconds()** (5 connections) — `core/engine/indicator_manager.py`
- **._validate_log_candles()** (4 connections) — `core/engine/indicator_manager.py`
- **._key_symbol_tf()** (2 connections) — `core/engine/indicator_manager.py`
- **.test_timeframe_to_seconds_handles_4h_and_1d()** (2 connections) — `core/engine/tests/test_extra_timeframe_live_append.py`
- **_to_business_day()** (1 connections) — `core/engine/indicator_manager.py`
- **Remove today's rows from API bootstrap; today's OHLC comes from closed-candle…** (1 connections) — `core/engine/indicator_manager.py`
- **Bootstrap OHLC frame from deduped RSI history closes when candle logs are short.** (1 connections) — `core/engine/indicator_manager.py`
- **Remove bars whose open is ahead of wall clock (bad IST seed rows).** (1 connections) — `core/engine/indicator_manager.py`

## Relationships

- [Any](Any.md) (7 shared connections)
- [IndicatorManager](IndicatorManager.md) (7 shared connections)
- [._collect_candle_closed_rows_from_logs](_collect_candle_closed_rows_from_logs.md) (3 shared connections)
- [._sanitize_delta_ohlc_df](_sanitize_delta_ohlc_df.md) (1 shared connections)
- [._load_rsi_history_rows](_load_rsi_history_rows.md) (1 shared connections)
- [TestExtraTimeframeLiveAppend](TestExtraTimeframeLiveAppend.md) (1 shared connections)

## Source Files

- `core/engine/indicator_manager.py`
- `core/engine/tests/test_extra_timeframe_live_append.py`

## Audit Trail

- EXTRACTED: 34 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*