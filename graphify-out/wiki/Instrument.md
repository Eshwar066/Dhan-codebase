# Instrument

> 17 nodes

## Key Concepts

- **Instrument** (29 connections) — `core/utils/instruments/base.py`
- **BaseInstrumentStore** (11 connections) — `core/utils/instruments/base.py`
- **.futures_intent_creation_details()** (3 connections) — `core/utils/instruments/base.py`
- **.intent_creation_details()** (3 connections) — `core/utils/instruments/base.py`
- **.get_lot_size()** (2 connections) — `core/utils/instruments/base.py`
- **.get_tick_size()** (2 connections) — `core/utils/instruments/base.py`
- **.contract_key()** (2 connections) — `core/utils/instruments/base.py`
- **ABC** (2 connections)
- **.__init__()** (1 connections) — `core/utils/instruments/base.py`
- **.__repr__()** (1 connections) — `core/utils/instruments/base.py`
- **Resolve futures contract to Instrument. Returns None if not found.** (1 connections) — `core/utils/instruments/base.py`
- **Return tick size for symbol when known; None otherwise. Override in broker…** (1 connections) — `core/utils/instruments/base.py`
- **Return lot size for symbol when known; None otherwise. Override in broker…** (1 connections) — `core/utils/instruments/base.py`
- **Single tradable contract (option/future/equity). Used by order intents and…** (1 connections) — `core/utils/instruments/base.py`
- **Uniquely identifies a tradable contract (netting, hedges, rollovers).** (1 connections) — `core/utils/instruments/base.py`
- **Broker-specific instrument store: load + lookup by symbol/expiry.** (1 connections) — `core/utils/instruments/base.py`
- **Resolve option contract to Instrument for order intent. Returns None if not…** (1 connections) — `core/utils/instruments/base.py`

## Relationships

- [RunMode](RunMode.md) (11 shared connections)
- [DhanInstrumentStore](DhanInstrumentStore.md) (6 shared connections)
- [DeltaInstrumentStore](DeltaInstrumentStore.md) (5 shared connections)
- [Position](Position.md) (5 shared connections)
- [_pm](_pm.md) (1 shared connections)
- [GttFallbackWatch](GttFallbackWatch.md) (1 shared connections)

## Source Files

- `core/utils/instruments/base.py`

## Audit Trail

- EXTRACTED: 42 (91%)
- INFERRED: 4 (9%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*