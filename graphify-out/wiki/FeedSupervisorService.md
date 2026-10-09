# FeedSupervisorService

> 13 nodes

## Key Concepts

- **FeedSupervisorService** (14 connections) — `core/events/services/feed_supervisor.py`
- **feed.py** (10 connections) — `core/events/handlers/feed.py`
- **FeedSupervisorHandler** (8 connections) — `core/events/handlers/feed.py`
- **register_feed_handlers()** (6 connections) — `core/events/handlers/feed.py`
- **test_feed_supervisor_service_flags()** (4 connections) — `tests/test_event_bus.py`
- **.on_disconnected()** (3 connections) — `core/events/handlers/feed.py`
- **.on_recovered()** (3 connections) — `core/events/handlers/feed.py`
- **.__init__()** (2 connections) — `core/events/handlers/feed.py`
- **.__init__()** (2 connections) — `core/events/services/feed_supervisor.py`
- **.on_disconnected()** (2 connections) — `core/events/services/feed_supervisor.py`
- **.on_recovered()** (2 connections) — `core/events/services/feed_supervisor.py`
- **Any** (1 connections)
- **FeedDisconnected / FeedRecovered → FeedSupervisorService.** (1 connections) — `core/events/handlers/feed.py`

## Relationships

- [Event](Event.md) (12 shared connections)
- [test_event_bus.py](test_event_bus.py.md) (6 shared connections)
- [EventType](EventType.md) (3 shared connections)
- [services/__init__.py](services-__init__.py.md) (1 shared connections)
- [logging.py](logging.py.md) (1 shared connections)
- [ExitRolloverService](ExitRolloverService.md) (1 shared connections)
- [make_event](make_event.md) (1 shared connections)
- [RunMode](RunMode.md) (1 shared connections)

## Source Files

- `core/events/handlers/feed.py`
- `core/events/services/feed_supervisor.py`
- `tests/test_event_bus.py`

## Audit Trail

- EXTRACTED: 34 (81%)
- INFERRED: 8 (19%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*