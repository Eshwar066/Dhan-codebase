# KotakDataProvider

> 12 nodes

## Key Concepts

- **KotakDataProvider** (18 connections) — `core/data/datalayer/kotak_data_provider.py`
- **._convert_live_api_to_sem()** (5 connections) — `core/data/datalayer/kotak_data_provider.py`
- **.get_live_expiry()** (4 connections) — `core/data/datalayer/kotak_data_provider.py`
- **._instruments_df()** (4 connections) — `core/data/datalayer/kotak_data_provider.py`
- **Any** (4 connections)
- **DataFrame** (3 connections)
- **.bind_instrument_store()** (2 connections) — `core/data/datalayer/kotak_data_provider.py`
- **.get_intraday()** (2 connections) — `core/data/datalayer/kotak_data_provider.py`
- **.__init__()** (2 connections) — `core/data/datalayer/kotak_data_provider.py`
- **.get_latest_candles()** (1 connections) — `core/data/datalayer/kotak_data_provider.py`
- **Data layer for Kotak Neo. Orders belong to the broker layer.** (1 connections) — `core/data/datalayer/kotak_data_provider.py`
- **Convert live API response to SEM_* format expected by build_dhan_shaped_chain.** (1 connections) — `core/data/datalayer/kotak_data_provider.py`

## Relationships

- [kotak_data_provider.py](kotak_data_provider.py.md) (6 shared connections)
- [factory.py](factory.py.md) (3 shared connections)
- [IDataProvider](IDataProvider.md) (2 shared connections)
- [.create_live_engine](create_live_engine.md) (1 shared connections)
- [typing](typing.md) (1 shared connections)

## Source Files

- `core/data/datalayer/kotak_data_provider.py`

## Audit Trail

- EXTRACTED: 28 (93%)
- INFERRED: 2 (7%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*