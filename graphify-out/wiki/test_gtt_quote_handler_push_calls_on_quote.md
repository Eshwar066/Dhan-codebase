# test_gtt_quote_handler_push_calls_on_quote

> 22 nodes

## Key Concepts

- **test_gtt_quote_handler_push_calls_on_quote()** (13 connections) — `tests/test_event_bus.py`
- **test_gtt_quote_handler_maintenance()** (12 connections) — `tests/test_event_bus.py`
- **test_gtt_maintenance_without_maintenance_tick_does_not_full_tick()** (11 connections) — `tests/test_event_bus.py`
- **.from_engine()** (8 connections) — `core/events/context.py`
- **TestRegister** (4 connections) — `core/events/handlers/tests/test_reentry_at_cost.py`
- **.test_register_subscribes()** (3 connections) — `core/events/handlers/tests/test_reentry_at_cost.py`
- **.test_tick_book_noop_without_pending()** (2 connections) — `core/events/handlers/tests/test_reentry_at_cost.py`
- **_current_ist_now()** (1 connections) — `tests/test_event_bus.py`
- **has_active_watches()** (1 connections) — `tests/test_event_bus.py`
- **tick()** (1 connections) — `tests/test_event_bus.py`
- **_current_ist_now()** (1 connections) — `tests/test_event_bus.py`
- **has_active_watches()** (1 connections) — `tests/test_event_bus.py`
- **maintenance_tick()** (1 connections) — `tests/test_event_bus.py`
- **on_quote()** (1 connections) — `tests/test_event_bus.py`
- **tick()** (1 connections) — `tests/test_event_bus.py`
- **_current_ist_now()** (1 connections) — `tests/test_event_bus.py`
- **has_active_watches()** (1 connections) — `tests/test_event_bus.py`
- **maintenance_tick()** (1 connections) — `tests/test_event_bus.py`
- **on_quote()** (1 connections) — `tests/test_event_bus.py`
- **tick()** (1 connections) — `tests/test_event_bus.py`
- **Any** (1 connections)
- **Regression: handler must not book.tick() on maintenance (LiveEngine owns quiet…** (1 connections) — `tests/test_event_bus.py`

## Relationships

- [Event](Event.md) (8 shared connections)
- [EventType](EventType.md) (7 shared connections)
- [make_event](make_event.md) (4 shared connections)
- [test_event_bus.py](test_event_bus.py.md) (4 shared connections)
- [reentry_at_cost.py](reentry_at_cost.py.md) (2 shared connections)
- [BidAskLtp](BidAskLtp.md) (1 shared connections)

## Source Files

- `core/events/context.py`
- `core/events/handlers/tests/test_reentry_at_cost.py`
- `tests/test_event_bus.py`

## Audit Trail

- EXTRACTED: 39 (83%)
- INFERRED: 8 (17%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*