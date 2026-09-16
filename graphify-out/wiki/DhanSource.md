# DhanSource

> 34 nodes

## Key Concepts

- **DhanSource** (55 connections) — `core/data/sources/dhan_source.py`
- **Data feeding (engines)** (9 connections) — `core/library/README.md`
- **.get_latest_candles()** (3 connections) — `core/data/sources/dhan_source.py`
- **.get_live_expiry()** (3 connections) — `core/data/sources/dhan_source.py`
- **.get_ltp_data()** (3 connections) — `core/data/sources/dhan_source.py`
- **.cancel_forever_order()** (2 connections) — `core/data/sources/dhan_source.py`
- **.cancel_order()** (2 connections) — `core/data/sources/dhan_source.py`
- **.get_atm_options()** (2 connections) — `core/data/sources/dhan_source.py`
- **.get_forever_orders()** (2 connections) — `core/data/sources/dhan_source.py`
- **.get_itm_options()** (2 connections) — `core/data/sources/dhan_source.py`
- **.get_ltp_v2()** (2 connections) — `core/data/sources/dhan_source.py`
- **.get_ohlc_v2()** (2 connections) — `core/data/sources/dhan_source.py`
- **.get_order_by_id()** (2 connections) — `core/data/sources/dhan_source.py`
- **.get_otm_options()** (2 connections) — `core/data/sources/dhan_source.py`
- **.get_quote_data()** (2 connections) — `core/data/sources/dhan_source.py`
- **.get_quote_v2()** (2 connections) — `core/data/sources/dhan_source.py`
- **.get_balance()** (1 connections) — `core/data/sources/dhan_source.py`
- **.get_holdings()** (1 connections) — `core/data/sources/dhan_source.py`
- **.get_live_pnl()** (1 connections) — `core/data/sources/dhan_source.py`
- **.get_nse_expiries()** (1 connections) — `core/data/sources/dhan_source.py`
- **.get_nse_optionchain_historical()** (1 connections) — `core/data/sources/dhan_source.py`
- **.get_order_detail()** (1 connections) — `core/data/sources/dhan_source.py`
- **Fetch a single order by broker order id (no tradehull status-poll sleep).** (1 connections) — `core/data/sources/dhan_source.py`
- **Latest OHLC/LTP per symbol. Returns dict { symbol: { open, high, low, close,…** (1 connections) — `core/data/sources/dhan_source.py`
- **Cancel a single order.** (1 connections) — `core/data/sources/dhan_source.py`
- *... and 9 more nodes in this community*

## Relationships

- [Core Library – Dhan Tradehull](Core_Library_–_Dhan_Tradehull.md) (5 shared connections)
- [historical_cache.py](historical_cache.py.md) (4 shared connections)
- [.create_live_engine](create_live_engine.md) (3 shared connections)
- [._fetch_futures_intraday](_fetch_futures_intraday.md) (3 shared connections)
- [load_expired_option_chain_from_files](load_expired_option_chain_from_files.md) (3 shared connections)
- [DhanMarketFeedClient](DhanMarketFeedClient.md) (3 shared connections)
- [option_buildup_scheduler.py](option_buildup_scheduler.py.md) (2 shared connections)
- [typing](typing.md) (2 shared connections)
- [dhan/broker.py](dhan-broker.py.md) (2 shared connections)
- [.as_calendar_date](as_calendar_date.md) (2 shared connections)
- [IDataProvider](IDataProvider.md) (2 shared connections)
- [factory.py](factory.py.md) (1 shared connections)

## Source Files

- `core/data/sources/dhan_source.py`
- `core/library/README.md`

## Audit Trail

- EXTRACTED: 58 (77%)
- INFERRED: 17 (23%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*