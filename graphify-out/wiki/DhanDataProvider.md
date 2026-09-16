# DhanDataProvider

> 20 nodes

## Key Concepts

- **DhanDataProvider** (22 connections) — `core/data/datalayer/dhan_data_provider.py`
- **Any** (7 connections)
- **.get_intraday()** (3 connections) — `core/data/datalayer/dhan_data_provider.py`
- **.get_ltp_v2()** (3 connections) — `core/data/datalayer/dhan_data_provider.py`
- **.get_ohlc_v2()** (3 connections) — `core/data/datalayer/dhan_data_provider.py`
- **.get_quote_v2()** (3 connections) — `core/data/datalayer/dhan_data_provider.py`
- **.get_expired_optionchain()** (2 connections) — `core/data/datalayer/dhan_data_provider.py`
- **.get_Futures_historical_intraday_data()** (2 connections) — `core/data/datalayer/dhan_data_provider.py`
- **.get_live_expiry()** (2 connections) — `core/data/datalayer/dhan_data_provider.py`
- **.get_nse_expiries()** (2 connections) — `core/data/datalayer/dhan_data_provider.py`
- **.get_nse_optionchain_historical()** (2 connections) — `core/data/datalayer/dhan_data_provider.py`
- **.__init__()** (2 connections) — `core/data/datalayer/dhan_data_provider.py`
- **DataFrame** (2 connections)
- **.get_latest_candles()** (1 connections) — `core/data/datalayer/dhan_data_provider.py`
- **.get_live_option_chain()** (1 connections) — `core/data/datalayer/dhan_data_provider.py`
- **Data layer for Dhan: candles, option chain, expiries. No orders.** (1 connections) — `core/data/datalayer/dhan_data_provider.py`
- **LTP via v2 /marketfeed/ltp. instruments: { 'NSE_EQ': [id], 'NSE_FNO': [id], ...…** (1 connections) — `core/data/datalayer/dhan_data_provider.py`
- **OHLC + LTP via v2 /marketfeed/ohlc.** (1 connections) — `core/data/datalayer/dhan_data_provider.py`
- **Full quote via v2 /marketfeed/quote (depth, OI, volume).** (1 connections) — `core/data/datalayer/dhan_data_provider.py`
- **Args: dhan_source: DhanSource instance (or any object exposing get_* data…** (1 connections) — `core/data/datalayer/dhan_data_provider.py`

## Relationships

- [IDataProvider](IDataProvider.md) (4 shared connections)
- [.create_live_engine](create_live_engine.md) (2 shared connections)
- [option_buildup_scheduler.py](option_buildup_scheduler.py.md) (2 shared connections)
- [factory.py](factory.py.md) (1 shared connections)
- [DhanSource](DhanSource.md) (1 shared connections)

## Source Files

- `core/data/datalayer/dhan_data_provider.py`

## Audit Trail

- EXTRACTED: 34 (94%)
- INFERRED: 2 (6%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*