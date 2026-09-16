# EventBlackoutGuard

> 12 nodes

## Key Concepts

- **EventBlackoutGuard** (20 connections) — `core/utils/calendar/economic_events.py`
- **NowLike** (14 connections)
- **calendar/__init__.py** (9 connections) — `core/utils/calendar/__init__.py`
- **.should_block_entry()** (8 connections) — `core/utils/calendar/economic_events.py`
- **.describe_active()** (5 connections) — `core/utils/calendar/economic_events.py`
- **.is_blackout_active()** (5 connections) — `core/utils/calendar/economic_events.py`
- **.active_event()** (4 connections) — `core/utils/calendar/economic_events.py`
- **.is_blackout_active()** (4 connections) — `core/utils/calendar/economic_events.py`
- **._log_transition()** (3 connections) — `core/utils/calendar/economic_events.py`
- **OMS / engine guard: venue-scoped blackout check with start/end logging. No…** (1 connections) — `core/utils/calendar/economic_events.py`
- **Hard ENTRY gate: ±60m blackout OR short-DTE session rules. Returns (blocked,…** (1 connections) — `core/utils/calendar/economic_events.py`
- **Economic event calendar helpers (Delta entry blackout).** (1 connections) — `core/utils/calendar/__init__.py`

## Relationships

- [test_economic_events.py](test_economic_events.py.md) (10 shared connections)
- [economic_events.py](economic_events.py.md) (8 shared connections)
- [EventCalendarService](EventCalendarService.md) (8 shared connections)
- [EconomicEvent](EconomicEvent.md) (4 shared connections)
- [factory.py](factory.py.md) (2 shared connections)
- [RiskManager](RiskManager.md) (2 shared connections)
- [typing](typing.md) (2 shared connections)
- [.create_live_engine](create_live_engine.md) (1 shared connections)

## Source Files

- `core/utils/calendar/__init__.py`
- `core/utils/calendar/economic_events.py`

## Audit Trail

- EXTRACTED: 50 (89%)
- INFERRED: 6 (11%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*