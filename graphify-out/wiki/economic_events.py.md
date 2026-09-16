# economic_events.py

> 22 nodes

## Key Concepts

- **economic_events.py** (33 connections) — `core/utils/calendar/economic_events.py`
- **active_events()** (8 connections) — `core/utils/calendar/economic_events.py`
- **normalize_now()** (8 connections) — `core/utils/calendar/economic_events.py`
- **short_dte_block_reason()** (8 connections) — `core/utils/calendar/economic_events.py`
- **intent_dte()** (7 connections) — `core/utils/calendar/economic_events.py`
- **pending_session_events()** (7 connections) — `core/utils/calendar/economic_events.py`
- **parse_event_time()** (6 connections) — `core/utils/calendar/economic_events.py`
- **event_blackout_end()** (5 connections) — `core/utils/calendar/economic_events.py`
- **parse_expiry_date()** (5 connections) — `core/utils/calendar/economic_events.py`
- **datetime** (5 connections)
- **_as_utc()** (4 connections) — `core/utils/calendar/economic_events.py`
- **_event_identity()** (4 connections) — `core/utils/calendar/economic_events.py`
- **is_high_usd_event()** (4 connections) — `core/utils/calendar/economic_events.py`
- **date** (1 connections)
- **Economic event calendar for Delta entry blackout. Trade path uses only in-…** (1 connections) — `core/utils/calendar/economic_events.py`
- **Dedupe key: normalized name + exact UTC second.** (1 connections) — `core/utils/calendar/economic_events.py`
- **Return events whose blackout window contains ``now``.** (1 connections) — `core/utils/calendar/economic_events.py`
- **Parse Delta/Dhan-style expiry (DDMMYY, ISO, date/datetime).** (1 connections) — `core/utils/calendar/economic_events.py`
- **Calendar DTE in IST: expiry_date - today_ist. Prefers instrument.expiry; falls…** (1 connections) — `core/utils/calendar/economic_events.py`
- **HIGH USD events not yet completed that belong to today's IST session (including…** (1 connections) — `core/utils/calendar/economic_events.py`
- **Extra ENTRY block for short-dated options around same-session HIGH events. -…** (1 connections) — `core/utils/calendar/economic_events.py`
- **Parse ISO-8601 (Z or offset) into timezone-aware UTC datetime.** (1 connections) — `core/utils/calendar/economic_events.py`

## Relationships

- [EventCalendarService](EventCalendarService.md) (11 shared connections)
- [EconomicEvent](EconomicEvent.md) (9 shared connections)
- [EventBlackoutGuard](EventBlackoutGuard.md) (8 shared connections)
- [test_economic_events.py](test_economic_events.py.md) (6 shared connections)
- [logging.py](logging.py.md) (2 shared connections)
- [typing](typing.md) (2 shared connections)
- [RunMode](RunMode.md) (2 shared connections)
- [factory.py](factory.py.md) (1 shared connections)

## Source Files

- `core/utils/calendar/economic_events.py`

## Audit Trail

- EXTRACTED: 77 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*