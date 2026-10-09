# IndicatorManager

> 22 nodes

## Key Concepts

- **IndicatorManager** (69 connections) — `core/engine/indicator_manager.py`
- **._append_rsi_history_log()** (12 connections) — `core/engine/indicator_manager.py`
- **._structure_confirm_delay_bars()** (6 connections) — `core/engine/indicator_manager.py`
- **._structure_confirm_tail_rows()** (6 connections) — `core/engine/indicator_manager.py`
- **._apply_lag_divergence_to_candle()** (5 connections) — `core/engine/indicator_manager.py`
- **._hydrate_rsi_session_state_from_disk()** (5 connections) — `core/engine/indicator_manager.py`
- **._list_candles_log_paths()** (4 connections) — `core/engine/indicator_manager.py`
- **._is_candles_log_filename()** (3 connections) — `core/engine/indicator_manager.py`
- **._ist_bar_key_from_row()** (3 connections) — `core/engine/indicator_manager.py`
- **._live_row_fingerprint()** (3 connections) — `core/engine/indicator_manager.py`
- **._prune_rsi_logged_keys()** (3 connections) — `core/engine/indicator_manager.py`
- **._prune_live_persist_fingerprints()** (2 connections) — `core/engine/indicator_manager.py`
- **._safe_strategy_dir()** (2 connections) — `core/engine/indicator_manager.py`
- **._rsi_history_path()** (1 connections) — `core/engine/indicator_manager.py`
- **.set_runtime_context()** (1 connections) — `core/engine/indicator_manager.py`
- **Bars after close before writing ``live_append`` history. Only strategies that…** (1 connections) — `core/engine/indicator_manager.py`
- **Lag window for confirmed structure flags on the eval candle.** (1 connections) — `core/engine/indicator_manager.py`
- **Shared indicator layer for live engine. Maintains per-(symbol,timeframe) base…** (1 connections) — `core/engine/indicator_manager.py`
- **Copy confirmed swing/divergence flags from lagged pivot rows onto the eval…** (1 connections) — `core/engine/indicator_manager.py`
- **Single append-only ``{strategy_id}_candles.log`` (excludes old ``*.log.YYYY-MM-…** (1 connections) — `core/engine/indicator_manager.py`
- **Mark indicator history streams on disk so restarts only append new bars.** (1 connections) — `core/engine/indicator_manager.py`
- **Append indicator snapshot row(s) to shared history (symbol + timeframe).** (1 connections) — `core/engine/indicator_manager.py`

## Relationships

- [Any](Any.md) (31 shared connections)
- [._collect_candle_closed_rows_from_logs](_collect_candle_closed_rows_from_logs.md) (8 shared connections)
- [._bootstrap_base_candle_state](_bootstrap_base_candle_state.md) (7 shared connections)
- [TestExtraTimeframeLiveAppend](TestExtraTimeframeLiveAppend.md) (5 shared connections)
- [._sanitize_delta_ohlc_df](_sanitize_delta_ohlc_df.md) (4 shared connections)
- [factory.py](factory.py.md) (3 shared connections)
- [._load_rsi_history_rows](_load_rsi_history_rows.md) (3 shared connections)
- [RSIBreadAndButter](RSIBreadAndButter.md) (2 shared connections)
- [RunMode](RunMode.md) (1 shared connections)
- [RSI Bread & Butter (Delta crypto futures)](RSI_Bread_&_Butter_Delta_crypto_futures.md) (1 shared connections)
- [Runtime notes](Runtime_notes.md) (1 shared connections)
- [Algo - Multi-Venue Trading System](Algo_-_Multi-Venue_Trading_System.md) (1 shared connections)

## Source Files

- `core/engine/indicator_manager.py`

## Audit Trail

- EXTRACTED: 91 (91%)
- INFERRED: 9 (9%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*