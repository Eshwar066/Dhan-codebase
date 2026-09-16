# NSEClient

> 17 nodes

## Key Concepts

- **NSEClient** (16 connections) — `core/data/sources/NSEClient.py`
- **.get_options_history()** (7 connections) — `core/data/sources/NSEClient.py`
- **._save_cache()** (6 connections) — `core/data/sources/NSEClient.py`
- **._load_cache()** (5 connections) — `core/data/sources/NSEClient.py`
- **._ts_to_date()** (5 connections) — `core/data/sources/NSEClient.py`
- **._fetch_option_data()** (4 connections) — `core/data/sources/NSEClient.py`
- **.get_expiries()** (4 connections) — `core/data/sources/NSEClient.py`
- **.get_futures_history()** (4 connections) — `core/data/sources/NSEClient.py`
- **._cache_path()** (3 connections) — `core/data/sources/NSEClient.py`
- **._slice_data()** (3 connections) — `core/data/sources/NSEClient.py`
- **.to_dd_mmm_yyyy()** (3 connections) — `core/data/sources/NSEClient.py`
- **.to_dd_mm_yyyy()** (2 connections) — `core/data/sources/NSEClient.py`
- **.__init__()** (1 connections) — `core/data/sources/NSEClient.py`
- **date** (1 connections)
- **Supports: - '31-Mar-2022' - '2022-03-30T18:30:00.000+00:00'** (1 connections) — `core/data/sources/NSEClient.py`
- **instrument: OPTIDX → options FUTIDX → futures** (1 connections) — `core/data/sources/NSEClient.py`
- **Dates format: from/to → DD-MM-YYYY expiry_date → DD-MMM-YYYY (31-DEC-2020)** (1 connections) — `core/data/sources/NSEClient.py`

## Relationships

- [logging.py](logging.py.md) (2 shared connections)
- [DhanMarketFeedClient](DhanMarketFeedClient.md) (1 shared connections)
- [DhanSource](DhanSource.md) (1 shared connections)
- [factory.py](factory.py.md) (1 shared connections)

## Source Files

- `core/data/sources/NSEClient.py`

## Audit Trail

- EXTRACTED: 35 (97%)
- INFERRED: 1 (3%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*