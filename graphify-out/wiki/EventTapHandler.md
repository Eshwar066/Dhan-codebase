# EventTapHandler

> 10 nodes

## Key Concepts

- **EventTapHandler** (6 connections) — `core/events/handlers/logging.py`
- **register_event_tap()** (6 connections) — `core/events/handlers/logging.py`
- **sanitize_event_payload_for_log()** (6 connections) — `core/events/handlers/logging.py`
- **_summarize_intent()** (5 connections) — `core/events/handlers/logging.py`
- **.__call__()** (4 connections) — `core/events/handlers/logging.py`
- **.__init__()** (3 connections) — `core/events/handlers/logging.py`
- **_summarize_candle()** (3 connections) — `core/events/handlers/logging.py`
- **Any** (3 connections)
- **Path** (1 connections)
- **Shrink event payloads for disk tap (never stringify full ctx/strategy).** (1 connections) — `core/events/handlers/logging.py`

## Relationships

- [logging.py](logging.py.md) (5 shared connections)
- [Event](Event.md) (5 shared connections)
- [test_event_bus.py](test_event_bus.py.md) (2 shared connections)
- [factory.py](factory.py.md) (1 shared connections)
- [EventType](EventType.md) (1 shared connections)

## Source Files

- `core/events/handlers/logging.py`

## Audit Trail

- EXTRACTED: 22 (85%)
- INFERRED: 4 (15%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*