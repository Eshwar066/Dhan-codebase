# ._enrich_df_bs_delta

> 14 nodes

## Key Concepts

- **._enrich_df_bs_delta()** (8 connections) — `core/library/dhan_tradehull.py`
- **_expiry_date_for_series()** (5 connections) — `core/library/dhan_tradehull.py`
- **.get_expired_option_data()** (5 connections) — `core/library/dhan_tradehull.py`
- **_last_thursday_month()** (4 connections) — `core/library/dhan_tradehull.py`
- **_years_to_expiry()** (4 connections) — `core/library/dhan_tradehull.py`
- **.convert_to_df()** (3 connections) — `core/library/dhan_tradehull.py`
- **date** (3 connections)
- **.get_market_depth_df()** (2 connections) — `core/library/dhan_tradehull.py`
- **DataFrame** (2 connections)
- **_df()** (1 connections) — `core/library/dhan_tradehull.py`
- **Rough year fraction from bar timestamp to expiry (calendar).** (1 connections) — `core/library/dhan_tradehull.py`
- **Add ``delta`` column via Black-Scholes using ``spot``, ``strike``, ``iv``, bar…** (1 connections) — `core/library/dhan_tradehull.py`
- **Last Thursday of (year, month) — NIFTY-style monthly expiry.** (1 connections) — `core/library/dhan_tradehull.py`
- **Map Dhan ``expiry_code`` (0 = front month, 1 = next) to an expiry calendar…** (1 connections) — `core/library/dhan_tradehull.py`

## Relationships

- [logging.py](logging.py.md) (4 shared connections)
- [Tradehull](Tradehull.md) (4 shared connections)
- [IndiaMktMixins](IndiaMktMixins.md) (1 shared connections)
- [DhanContext](DhanContext.md) (1 shared connections)
- [._get_dhan_http](_get_dhan_http.md) (1 shared connections)

## Source Files

- `core/library/dhan_tradehull.py`

## Audit Trail

- EXTRACTED: 26 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*