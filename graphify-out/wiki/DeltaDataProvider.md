# DeltaDataProvider

> 21 nodes

## Key Concepts

- **DeltaDataProvider** (18 connections) — `core/data/datalayer/delta_data_provider.py`
- **Registry registration snippet** (6 connections) — `docs/templates/REGISTRY_SNIPPET.md`
- **Any** (3 connections)
- **3. `core/strategies/runtime_spec.py`** (3 connections) — `docs/templates/REGISTRY_SNIPPET.md`
- **.get_expired_optionchain()** (2 connections) — `core/data/datalayer/delta_data_provider.py`
- **.get_intraday()** (2 connections) — `core/data/datalayer/delta_data_provider.py`
- **.get_live_expiry()** (2 connections) — `core/data/datalayer/delta_data_provider.py`
- **.get_nse_optionchain_historical()** (2 connections) — `core/data/datalayer/delta_data_provider.py`
- **.__init__()** (2 connections) — `core/data/datalayer/delta_data_provider.py`
- **.get_latest_candles()** (1 connections) — `core/data/datalayer/delta_data_provider.py`
- **.get_live_option_chain()** (1 connections) — `core/data/datalayer/delta_data_provider.py`
- **.get_products()** (1 connections) — `core/data/datalayer/delta_data_provider.py`
- **.product_id_for_symbol()** (1 connections) — `core/data/datalayer/delta_data_provider.py`
- **DataFrame** (1 connections)
- **REGISTRY_SNIPPET.md** (1 connections) — `docs/templates/REGISTRY_SNIPPET.md`
- **1. `core/strategies/registry.py`** (1 connections) — `docs/templates/REGISTRY_SNIPPET.md`
- **2. `run/strategy_profiles.py`** (1 connections) — `docs/templates/REGISTRY_SNIPPET.md`
- **4. `run/config.py` (optional engine)** (1 connections) — `docs/templates/REGISTRY_SNIPPET.md`
- **5. Index entry** (1 connections) — `docs/templates/REGISTRY_SNIPPET.md`
- **Data layer for Delta Exchange: ticker/LTP, products, expiries. No orders.** (1 connections) — `core/data/datalayer/delta_data_provider.py`
- **Args: delta_source: DeltaSource instance (or any object exposing get_* data…** (1 connections) — `core/data/datalayer/delta_data_provider.py`

## Relationships

- [IDataProvider](IDataProvider.md) (3 shared connections)
- [.create_live_engine](create_live_engine.md) (2 shared connections)
- [factory.py](factory.py.md) (1 shared connections)
- [BaseBroker](BaseBroker.md) (1 shared connections)
- [NiftySMA9Weekly](NiftySMA9Weekly.md) (1 shared connections)

## Source Files

- `core/data/datalayer/delta_data_provider.py`
- `docs/templates/REGISTRY_SNIPPET.md`

## Audit Trail

- EXTRACTED: 27 (90%)
- INFERRED: 3 (10%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*