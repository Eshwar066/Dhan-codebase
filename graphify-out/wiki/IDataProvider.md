# IDataProvider

> 28 nodes

## Key Concepts

- **IDataProvider** (20 connections) — `core/data/datalayer/base.py`
- **datalayer/base.py** (9 connections) — `core/data/datalayer/base.py`
- **dhan_data_provider.py** (8 connections) — `core/data/datalayer/dhan_data_provider.py`
- **datalayer/__init__.py** (8 connections) — `core/data/datalayer/__init__.py`
- **delta_data_provider.py** (7 connections) — `core/data/datalayer/delta_data_provider.py`
- **Any** (4 connections)
- **Data Layer** (4 connections) — `core/data/datalayer/README.md`
- **Files** (4 connections) — `core/data/datalayer/README.md`
- **What goes here** (4 connections) — `core/data/datalayer/README.md`
- **.get_expired_optionchain()** (3 connections) — `core/data/datalayer/base.py`
- **.get_live_expiry()** (3 connections) — `core/data/datalayer/base.py`
- **.get_nse_expiries()** (3 connections) — `core/data/datalayer/base.py`
- **.get_nse_optionchain_historical()** (3 connections) — `core/data/datalayer/base.py`
- **.get_latest_candles()** (2 connections) — `core/data/datalayer/base.py`
- **.get_live_option_chain()** (2 connections) — `core/data/datalayer/base.py`
- **ABC** (2 connections)
- **datalayer/README.md** (1 connections) — `core/data/datalayer/README.md`
- **Usage** (1 connections) — `core/data/datalayer/README.md`
- **Data layer: abstract interface for all market data feeding the engines. Pro-…** (1 connections) — `core/data/datalayer/base.py`
- **Contract for market data used by engines and order management. Implementations:…** (1 connections) — `core/data/datalayer/base.py`
- **Latest OHLC/LTP per symbol (live/tick mode).** (1 connections) — `core/data/datalayer/base.py`
- **Live expiry list (broker-specific format, e.g. indices).** (1 connections) — `core/data/datalayer/base.py`
- **NSE expiry dates for a symbol/year. Optional for non-NSE providers.** (1 connections) — `core/data/datalayer/base.py`
- **Live option chain (e.g. Dhan format).** (1 connections) — `core/data/datalayer/base.py`
- **Expired option data for backtest (e.g. Dhan).** (1 connections) — `core/data/datalayer/base.py`
- *... and 3 more nodes in this community*

## Relationships

- [typing](typing.md) (6 shared connections)
- [DhanDataProvider](DhanDataProvider.md) (4 shared connections)
- [kotak_data_provider.py](kotak_data_provider.py.md) (3 shared connections)
- [DeltaDataProvider](DeltaDataProvider.md) (3 shared connections)
- [KotakDataProvider](KotakDataProvider.md) (2 shared connections)
- [option_buildup_scheduler.py](option_buildup_scheduler.py.md) (2 shared connections)
- [DhanSource](DhanSource.md) (2 shared connections)
- [Runtime notes](Runtime_notes.md) (1 shared connections)
- [BaseBroker](BaseBroker.md) (1 shared connections)

## Source Files

- `core/data/datalayer/README.md`
- `core/data/datalayer/__init__.py`
- `core/data/datalayer/base.py`
- `core/data/datalayer/delta_data_provider.py`
- `core/data/datalayer/dhan_data_provider.py`

## Audit Trail

- EXTRACTED: 54 (89%)
- INFERRED: 7 (11%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*