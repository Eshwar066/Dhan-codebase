# historical_cache.py

> 38 nodes

## Key Concepts

- **historical_cache.py** (13 connections) — `core/data/sources/historical_cache.py`
- **.get_intraday()** (12 connections) — `core/data/sources/dhan_source.py`
- **delta_historical_cache.py** (12 connections) — `core/data/sources/delta_historical_cache.py`
- **dhan_historical_cache.py** (11 connections) — `core/data/sources/dhan_historical_cache.py`
- **save_df()** (9 connections) — `core/data/sources/historical_cache.py`
- **load_df()** (8 connections) — `core/data/sources/historical_cache.py`
- **.get_Futures_historical_intraday_data()** (7 connections) — `core/data/sources/dhan_source.py`
- **_safe_key()** (7 connections) — `core/data/sources/historical_cache.py`
- **save_df()** (6 connections) — `core/data/sources/delta_historical_cache.py`
- **load_df()** (6 connections) — `core/data/sources/dhan_historical_cache.py`
- **save_df()** (6 connections) — `core/data/sources/dhan_historical_cache.py`
- **cache_key_delta_intraday()** (5 connections) — `core/data/sources/delta_historical_cache.py`
- **load_df()** (5 connections) — `core/data/sources/delta_historical_cache.py`
- **cache_key_futures()** (5 connections) — `core/data/sources/dhan_historical_cache.py`
- **cache_key_intraday()** (5 connections) — `core/data/sources/dhan_historical_cache.py`
- **._to_date()** (5 connections) — `core/data/sources/dhan_source.py`
- **re** (5 connections)
- **_drop_flat_candles()** (4 connections) — `core/data/sources/delta_historical_cache.py`
- **_path()** (3 connections) — `core/data/sources/historical_cache.py`
- **DataFrame** (2 connections)
- **DataFrame** (1 connections)
- **File cache for Delta Exchange historical intraday data. Uses…** (1 connections) — `core/data/sources/delta_historical_cache.py`
- **Drop rows where open, high, low, close are all equal (no-trade bars).** (1 connections) — `core/data/sources/delta_historical_cache.py`
- **Load a DataFrame from Delta cache. Returns None if missing or invalid.** (1 connections) — `core/data/sources/delta_historical_cache.py`
- **Save a DataFrame to Delta cache. Flat candles (o==h==l==c) are not stored.** (1 connections) — `core/data/sources/delta_historical_cache.py`
- *... and 13 more nodes in this community*

## Relationships

- [factory.py](factory.py.md) (7 shared connections)
- [logging.py](logging.py.md) (7 shared connections)
- [DhanSource](DhanSource.md) (4 shared connections)
- [RunMode](RunMode.md) (4 shared connections)
- [.get_intraday](get_intraday.md) (3 shared connections)
- [._fetch_futures_intraday](_fetch_futures_intraday.md) (3 shared connections)
- [typing](typing.md) (3 shared connections)
- [load_expired_option_chain_from_files](load_expired_option_chain_from_files.md) (2 shared connections)
- [EconomicEvent](EconomicEvent.md) (1 shared connections)

## Source Files

- `core/data/sources/delta_historical_cache.py`
- `core/data/sources/dhan_historical_cache.py`
- `core/data/sources/dhan_source.py`
- `core/data/sources/historical_cache.py`

## Audit Trail

- EXTRACTED: 93 (99%)
- INFERRED: 1 (1%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*