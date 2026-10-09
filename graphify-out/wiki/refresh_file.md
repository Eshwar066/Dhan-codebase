# refresh_file

> 17 nodes

## Key Concepts

- **refresh_file()** (11 connections) — `utils/delta/refresh_crypto_indicator_history.py`
- **main()** (6 connections) — `utils/delta/refresh_crypto_indicator_history.py`
- **_rows_from_df()** (6 connections) — `utils/delta/refresh_crypto_indicator_history.py`
- **Any** (6 connections)
- **_build_schema_row()** (5 connections) — `utils/delta/refresh_crypto_indicator_history.py`
- **_fetch_delta_ohlc()** (5 connections) — `utils/delta/refresh_crypto_indicator_history.py`
- **_strategy_for_tf()** (5 connections) — `utils/delta/refresh_crypto_indicator_history.py`
- **_trim_forming_tail()** (5 connections) — `utils/delta/refresh_crypto_indicator_history.py`
- **_float_or_none()** (4 connections) — `utils/delta/refresh_crypto_indicator_history.py`
- **_merge_history()** (4 connections) — `utils/delta/refresh_crypto_indicator_history.py`
- **_last_supertrend_snapshot()** (3 connections) — `utils/delta/refresh_crypto_indicator_history.py`
- **_load_history()** (3 connections) — `utils/delta/refresh_crypto_indicator_history.py`
- **DataFrame** (3 connections)
- **_parse_only()** (2 connections) — `utils/delta/refresh_crypto_indicator_history.py`
- **Timestamp** (1 connections)
- **Merge disk history with a fresh Delta REST SuperTrend series. ``delta_refresh``…** (1 connections) — `utils/delta/refresh_crypto_indicator_history.py`
- **Drop the current open (forming) bar so refresh ends at last closed candle.** (1 connections) — `utils/delta/refresh_crypto_indicator_history.py`

## Relationships

- [factory.py](factory.py.md) (14 shared connections)
- [DeltaSource](DeltaSource.md) (3 shared connections)
- [indicator_history.py](indicator_history.py.md) (2 shared connections)
- [indicator_history_path](indicator_history_path.md) (1 shared connections)
- [refresh_nifty_indicator_history.py](refresh_nifty_indicator_history.py.md) (1 shared connections)
- [DirectionalOptionSelling](DirectionalOptionSelling.md) (1 shared connections)
- [RSIBreadAndButter](RSIBreadAndButter.md) (1 shared connections)

## Source Files

- `utils/delta/refresh_crypto_indicator_history.py`

## Audit Trail

- EXTRACTED: 45 (96%)
- INFERRED: 2 (4%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*