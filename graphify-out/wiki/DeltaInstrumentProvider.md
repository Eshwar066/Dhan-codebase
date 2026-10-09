# DeltaInstrumentProvider

> 11 nodes

## Key Concepts

- **DeltaInstrumentProvider** (8 connections) — `core/utils/instruments/delta.py`
- **fetch_delta_products()** (7 connections) — `core/utils/instruments/delta.py`
- **.fetch_products()** (4 connections) — `core/utils/instruments/delta.py`
- **refresh()** (4 connections) — `utils/delta/refresh_delta_instruments.py`
- **.load()** (3 connections) — `core/utils/instruments/delta.py`
- **DataFrame** (3 connections)
- **main()** (2 connections) — `utils/delta/refresh_delta_instruments.py`
- **.__init__()** (1 connections) — `core/utils/instruments/delta.py`
- **Path** (1 connections)
- **Fetch product list from Delta /v2/products. Returns raw result as DataFrame.** (1 connections) — `core/utils/instruments/delta.py`
- **Load Delta Exchange product list from API or from cache CSV in Dependencies.** (1 connections) — `core/utils/instruments/delta.py`

## Relationships

- [RunMode](RunMode.md) (7 shared connections)
- [DeltaInstrumentStore](DeltaInstrumentStore.md) (1 shared connections)
- [DhanInstrumentProvider](DhanInstrumentProvider.md) (1 shared connections)

## Source Files

- `core/utils/instruments/delta.py`
- `utils/delta/refresh_delta_instruments.py`

## Audit Trail

- EXTRACTED: 22 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*