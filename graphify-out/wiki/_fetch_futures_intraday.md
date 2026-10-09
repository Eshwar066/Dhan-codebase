# ._fetch_futures_intraday

> 7 nodes

## Key Concepts

- **._fetch_futures_intraday()** (4 connections) — `core/data/sources/dhan_source.py`
- **._normalize_intraday_df()** (4 connections) — `core/data/sources/dhan_source.py`
- **._resample_ohlc_minutes()** (4 connections) — `core/data/sources/dhan_source.py`
- **DataFrame** (3 connections)
- **Normalize raw API df: timestamp column, sort, time column. Returns None if…** (1 connections) — `core/data/sources/dhan_source.py`
- **Resample OHLC to ``target_minutes`` bars with NSE session origin 09:15 IST.** (1 connections) — `core/data/sources/dhan_source.py`
- **Call Dhan charts/intraday API and return normalized DataFrame.** (1 connections) — `core/data/sources/dhan_source.py`

## Relationships

- [historical_cache.py](historical_cache.py.md) (3 shared connections)
- [DhanSource](DhanSource.md) (3 shared connections)

## Source Files

- `core/data/sources/dhan_source.py`

## Audit Trail

- EXTRACTED: 12 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*