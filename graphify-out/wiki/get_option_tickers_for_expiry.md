# .get_option_tickers_for_expiry

> 10 nodes

## Key Concepts

- **.get_option_tickers_for_expiry()** (5 connections) — `core/data/sources/delta_source.py`
- **.get_all_tickers_map()** (4 connections) — `core/data/sources/delta_source.py`
- **.get_tickers_list()** (4 connections) — `core/data/sources/delta_source.py`
- **.tickers_map_by_symbol()** (4 connections) — `core/data/sources/delta_source.py`
- **.expiry_ddmmyy_to_api_date()** (3 connections) — `core/data/sources/delta_source.py`
- **``DDMMYY`` (e.g. ``070326``) -> ``DD-MM-YYYY`` for Delta ``GET /v2/tickers``…** (1 connections) — `core/data/sources/delta_source.py`
- **One REST call: ``GET /v2/tickers`` with optional filters (option chain per…** (1 connections) — `core/data/sources/delta_source.py`
- **Index ticker rows by uppercase ``symbol``.** (1 connections) — `core/data/sources/delta_source.py`
- **Single batch call for all call or put option tickers for one underlying +…** (1 connections) — `core/data/sources/delta_source.py`
- **One ``GET /v2/tickers`` call with no filters (all products). Large payload;…** (1 connections) — `core/data/sources/delta_source.py`

## Relationships

- [DeltaSource](DeltaSource.md) (5 shared connections)

## Source Files

- `core/data/sources/delta_source.py`

## Audit Trail

- EXTRACTED: 15 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*