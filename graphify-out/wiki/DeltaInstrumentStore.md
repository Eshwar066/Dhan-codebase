# DeltaInstrumentStore

> 18 nodes

## Key Concepts

- **DeltaInstrumentStore** (16 connections) — `core/utils/instruments/delta.py`
- **._row_for_contract_key()** (7 connections) — `core/utils/instruments/delta.py`
- **.refresh_products()** (6 connections) — `core/utils/instruments/delta.py`
- **.futures_intent_creation_details()** (5 connections) — `core/utils/instruments/delta.py`
- **.intent_creation_details()** (5 connections) — `core/utils/instruments/delta.py`
- **._row_to_instrument()** (5 connections) — `core/utils/instruments/delta.py`
- **.__init__()** (4 connections) — `core/utils/instruments/delta.py`
- **._rebuild_symbol_lookup()** (4 connections) — `core/utils/instruments/delta.py`
- **.get_lot_size()** (3 connections) — `core/utils/instruments/delta.py`
- **.get_tick_size()** (3 connections) — `core/utils/instruments/delta.py`
- **Series** (2 connections)
- **Path** (1 connections)
- **Redownload products, atomically replace cache, and rebuild lookup.** (1 connections) — `core/utils/instruments/delta.py`
- **Resolve CSV row by contract symbol or numeric product id (string).** (1 connections) — `core/utils/instruments/delta.py`
- **Return tick size for symbol from product data; None if not found.** (1 connections) — `core/utils/instruments/delta.py`
- **Return lot size for symbol from product data; None if not found. Delta often…** (1 connections) — `core/utils/instruments/delta.py`
- **Instrument store for Delta: product id/symbol lookup, Delta-specific backtest…** (1 connections) — `core/utils/instruments/delta.py`
- **Rebuild symbol/product-id lookups after loading or refreshing products.** (1 connections) — `core/utils/instruments/delta.py`

## Relationships

- [Instrument](Instrument.md) (5 shared connections)
- [RunMode](RunMode.md) (3 shared connections)
- [InstrumentStore](InstrumentStore.md) (1 shared connections)
- [DeltaInstrumentProvider](DeltaInstrumentProvider.md) (1 shared connections)
- [Any](Any.md) (1 shared connections)

## Source Files

- `core/utils/instruments/delta.py`

## Audit Trail

- EXTRACTED: 36 (92%)
- INFERRED: 3 (8%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*