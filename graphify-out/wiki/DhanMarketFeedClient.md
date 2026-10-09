# DhanMarketFeedClient

> 18 nodes

## Key Concepts

- **DhanMarketFeedClient** (14 connections) — `core/library/dhan_marketfeed.py`
- **._post()** (8 connections) — `core/library/dhan_marketfeed.py`
- **Any** (8 connections)
- **.__init__()** (5 connections) — `core/data/sources/dhan_source.py`
- **.ltp()** (4 connections) — `core/library/dhan_marketfeed.py`
- **.ohlc()** (4 connections) — `core/library/dhan_marketfeed.py`
- **._payload()** (4 connections) — `core/library/dhan_marketfeed.py`
- **.quote()** (4 connections) — `core/library/dhan_marketfeed.py`
- **._ensure_deps_path()** (3 connections) — `core/data/sources/dhan_source.py`
- **._throttle()** (3 connections) — `core/library/dhan_marketfeed.py`
- **._headers()** (2 connections) — `core/library/dhan_marketfeed.py`
- **.__init__()** (1 connections) — `core/library/dhan_marketfeed.py`
- **Ensure Dependencies folder exists for Tradehull instrument file.** (1 connections) — `core/data/sources/dhan_source.py`
- **Client for Dhan v2 Market Quote API. Instruments: dict mapping exchange segment…** (1 connections) — `core/library/dhan_marketfeed.py`
- **Build request body: only non-empty segments, values as list of ints.** (1 connections) — `core/library/dhan_marketfeed.py`
- **Get LTP for instruments. Request: { "NSE_EQ": [11536], "NSE_FNO": [49081,…** (1 connections) — `core/library/dhan_marketfeed.py`
- **Get OHLC + LTP for instruments. Response: { "status": "success", "data": {…** (1 connections) — `core/library/dhan_marketfeed.py`
- **Get full quote: market depth, OHLC, OI, volume, etc. Response: { "status":…** (1 connections) — `core/library/dhan_marketfeed.py`

## Relationships

- [logging.py](logging.py.md) (5 shared connections)
- [DhanSource](DhanSource.md) (3 shared connections)
- [dhan/broker.py](dhan-broker.py.md) (1 shared connections)
- [Tradehull](Tradehull.md) (1 shared connections)
- [NSEClient](NSEClient.md) (1 shared connections)
- [DhanBroker](DhanBroker.md) (1 shared connections)

## Source Files

- `core/data/sources/dhan_source.py`
- `core/library/dhan_marketfeed.py`

## Audit Trail

- EXTRACTED: 37 (95%)
- INFERRED: 2 (5%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*