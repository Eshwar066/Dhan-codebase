# DhanInstrumentProvider

> 11 nodes

## Key Concepts

- **DhanInstrumentProvider** (8 connections) — `core/utils/instruments/dhan.py`
- **get_provider_for_path()** (5 connections) — `core/utils/instruments/providers.py`
- **._fetch_master_csv()** (3 connections) — `core/utils/instruments/dhan.py`
- **.load()** (3 connections) — `core/utils/instruments/dhan.py`
- **.__init__()** (3 connections) — `core/utils/instruments/dhan.py`
- **.__init__()** (2 connections) — `core/utils/instruments/dhan.py`
- **Path** (2 connections)
- **Path** (1 connections)
- **Load Dhan instrument master from CSV (e.g. all_instrument{date}.csv).** (1 connections) — `core/utils/instruments/dhan.py`
- **Download public Dhan scrip master (same source as Tradehull) if file is missing.** (1 connections) — `core/utils/instruments/dhan.py`
- **Return provider based on broker; path is used for Dhan CSV or optional Delta…** (1 connections) — `core/utils/instruments/providers.py`

## Relationships

- [RunMode](RunMode.md) (3 shared connections)
- [DhanInstrumentStore](DhanInstrumentStore.md) (2 shared connections)
- [DeltaInstrumentProvider](DeltaInstrumentProvider.md) (1 shared connections)

## Source Files

- `core/utils/instruments/dhan.py`
- `core/utils/instruments/providers.py`

## Audit Trail

- EXTRACTED: 18 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*