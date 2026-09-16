# normalize_dhan_tick_size

> 4 nodes

## Key Concepts

- **normalize_dhan_tick_size()** (7 connections) — `core/utils/price_tick.py`
- **.get_tick_size()** (3 connections) — `core/utils/instruments/dhan.py`
- **Return tick size for symbol from instrument data (SEM_TICK_SIZE); None if not…** (1 connections) — `core/utils/instruments/dhan.py`
- **Dhan ``SEM_TICK_SIZE`` may be stored as rupees (0.05) or paise (5 → ₹0.05).** (1 connections) — `core/utils/price_tick.py`

## Relationships

- [DhanInstrumentStore](DhanInstrumentStore.md) (2 shared connections)
- [roll_leaps_hedge.py](roll_leaps_hedge.py.md) (2 shared connections)
- [BankNiftyBTST](BankNiftyBTST.md) (1 shared connections)
- [RunMode](RunMode.md) (1 shared connections)

## Source Files

- `core/utils/instruments/dhan.py`
- `core/utils/price_tick.py`

## Audit Trail

- EXTRACTED: 9 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*