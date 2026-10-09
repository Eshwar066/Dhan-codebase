# .get_intraday

> 13 nodes

## Key Concepts

- **.get_intraday()** (10 connections) — `core/data/sources/delta_source.py`
- **._intraday_tail_is_stale()** (7 connections) — `core/data/sources/delta_source.py`
- **._cache_latest_timestamp()** (5 connections) — `core/data/sources/delta_source.py`
- **._fetch_intraday_range()** (5 connections) — `core/data/sources/delta_source.py`
- **._to_date()** (4 connections) — `core/data/sources/delta_source.py`
- **DataFrame** (4 connections)
- **date** (3 connections)
- **._timeframe_seconds()** (2 connections) — `core/data/sources/delta_source.py`
- **Timestamp** (1 connections)
- **True when cache tail is behind wall clock (same-day bars missing).** (1 connections) — `core/data/sources/delta_source.py`
- **Fetch intraday candles for a date range from Delta API. Returns normalized…** (1 connections) — `core/data/sources/delta_source.py`
- **Long-term historical intraday. Cache key = symbol+timeframe. Returns requested…** (1 connections) — `core/data/sources/delta_source.py`
- **Normalize to date for range comparison.** (1 connections) — `core/data/sources/delta_source.py`

## Relationships

- [DeltaSource](DeltaSource.md) (6 shared connections)
- [historical_cache.py](historical_cache.py.md) (3 shared connections)

## Source Files

- `core/data/sources/delta_source.py`

## Audit Trail

- EXTRACTED: 27 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*