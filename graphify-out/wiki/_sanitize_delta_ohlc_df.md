# ._sanitize_delta_ohlc_df

> 7 nodes

## Key Concepts

- **._sanitize_delta_ohlc_df()** (8 connections) — `core/engine/indicator_manager.py`
- **._finalize_delta_base_df()** (5 connections) — `core/engine/indicator_manager.py`
- **._sanitize_delta_ohlc_row()** (5 connections) — `core/engine/indicator_manager.py`
- **._should_sanitize_delta_ohlc()** (4 connections) — `core/engine/indicator_manager.py`
- **Re-sanitize rolling OHLC (1m/5m only) and bump update_seq after bar append.** (1 connections) — `core/engine/indicator_manager.py`
- **Wick clamping is only for fine crypto bars (1m/5m tick noise). Applying it to…** (1 connections) — `core/engine/indicator_manager.py`
- **Clamp absurd tick wicks on 1m crypto bars (e.g. 58300 / 61437 on ~61100).** (1 connections) — `core/engine/indicator_manager.py`

## Relationships

- [Any](Any.md) (6 shared connections)
- [IndicatorManager](IndicatorManager.md) (4 shared connections)
- [._bootstrap_base_candle_state](_bootstrap_base_candle_state.md) (1 shared connections)
- [._load_rsi_history_rows](_load_rsi_history_rows.md) (1 shared connections)
- [._collect_candle_closed_rows_from_logs](_collect_candle_closed_rows_from_logs.md) (1 shared connections)

## Source Files

- `core/engine/indicator_manager.py`

## Audit Trail

- EXTRACTED: 19 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*