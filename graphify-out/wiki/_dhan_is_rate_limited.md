# _dhan_is_rate_limited

> 6 nodes

## Key Concepts

- **_dhan_is_rate_limited()** (5 connections) — `core/library/dhan_tradehull.py`
- **.get_ohlc_data()** (4 connections) — `core/library/dhan_tradehull.py`
- **._ohlc_cache_store()** (3 connections) — `core/library/dhan_tradehull.py`
- **._ohlc_cache_subset()** (3 connections) — `core/library/dhan_tradehull.py`
- **Any** (3 connections)
- **True when Dhan returns HTTP 805 / too-many-requests style errors.** (1 connections) — `core/library/dhan_tradehull.py`

## Relationships

- [Tradehull](Tradehull.md) (3 shared connections)
- [.get_ltp_data](get_ltp_data.md) (1 shared connections)
- [logging.py](logging.py.md) (1 shared connections)

## Source Files

- `core/library/dhan_tradehull.py`

## Audit Trail

- EXTRACTED: 12 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*