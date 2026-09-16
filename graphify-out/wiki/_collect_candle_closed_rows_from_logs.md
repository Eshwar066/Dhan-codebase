# ._collect_candle_closed_rows_from_logs

> 13 nodes

## Key Concepts

- **._collect_candle_closed_rows_from_logs()** (8 connections) — `core/engine/indicator_manager.py`
- **._load_candles_from_logs()** (7 connections) — `core/engine/indicator_manager.py`
- **._merge_today_live_candles()** (7 connections) — `core/engine/indicator_manager.py`
- **._candle_rows_to_sorted_df()** (6 connections) — `core/engine/indicator_manager.py`
- **._load_today_from_indicator_history()** (5 connections) — `core/engine/indicator_manager.py`
- **._load_today_live_candles()** (5 connections) — `core/engine/indicator_manager.py`
- **._parse_bar_timestamp_ist_to_aware()** (5 connections) — `core/engine/indicator_manager.py`
- **datetime** (2 connections)
- **date** (1 connections)
- **Today's OHLC from shared indicator history (delta_refresh wins over…** (1 connections) — `core/engine/indicator_manager.py`
- **Parse ``bar_timestamp_ist`` / ``candle_timestamp_ist`` from logs (ISO or…** (1 connections) — `core/engine/indicator_manager.py`
- **Scan strategy ``logs/{strategy_id}/{strategy_id}_candles.log`` (append-only).…** (1 connections) — `core/engine/indicator_manager.py`
- **Load the most recent ``tail_rows`` closed candles for symbol|timeframe from…** (1 connections) — `core/engine/indicator_manager.py`

## Relationships

- [IndicatorManager](IndicatorManager.md) (8 shared connections)
- [Any](Any.md) (7 shared connections)
- [._bootstrap_base_candle_state](_bootstrap_base_candle_state.md) (3 shared connections)
- [._sanitize_delta_ohlc_df](_sanitize_delta_ohlc_df.md) (1 shared connections)
- [factory.py](factory.py.md) (1 shared connections)

## Source Files

- `core/engine/indicator_manager.py`

## Audit Trail

- EXTRACTED: 35 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*