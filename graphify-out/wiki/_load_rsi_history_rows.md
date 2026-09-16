# ._load_rsi_history_rows

> 6 nodes

## Key Concepts

- **._load_rsi_history_rows()** (6 connections) — `core/engine/indicator_manager.py`
- **._merge_rsi_history_into_base_df()** (6 connections) — `core/engine/indicator_manager.py`
- **._dedupe_rows_by_timestamp()** (4 connections) — `core/engine/indicator_manager.py`
- **Keep the last row per ``timestamp`` (handles duplicate log lines on restart).** (1 connections) — `core/engine/indicator_manager.py`
- **Load recent bars from shared indicator history (+ legacy RSI log).** (1 connections) — `core/engine/indicator_manager.py`
- **Prepend close-only bars from RSI history so the first live bar of the day gets…** (1 connections) — `core/engine/indicator_manager.py`

## Relationships

- [Any](Any.md) (4 shared connections)
- [IndicatorManager](IndicatorManager.md) (3 shared connections)
- [._bootstrap_base_candle_state](_bootstrap_base_candle_state.md) (1 shared connections)
- [._sanitize_delta_ohlc_df](_sanitize_delta_ohlc_df.md) (1 shared connections)

## Source Files

- `core/engine/indicator_manager.py`

## Audit Trail

- EXTRACTED: 14 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*