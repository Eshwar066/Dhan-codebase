# EventType

> 31 nodes

## Key Concepts

- **EventType** (53 connections) — `core/events/types.py`
- **EventBus** (26 connections) — `core/events/bus.py`
- **bus.py** (14 connections) — `core/events/bus.py`
- **quotes.py** (13 connections) — `core/events/handlers/quotes.py`
- **StrategyQuoteHandler** (8 connections) — `core/events/handlers/quotes.py`
- **events/__init__.py** (8 connections) — `core/events/__init__.py`
- **register_strategy_quote_handler()** (6 connections) — `core/events/handlers/quotes.py`
- **test_handler_exception_does_not_block_others()** (6 connections) — `tests/test_event_bus.py`
- **test_publish_priority_order()** (6 connections) — `tests/test_event_bus.py`
- **.subscribe()** (5 connections) — `core/events/bus.py`
- **.__call__()** (4 connections) — `core/events/handlers/quotes.py`
- **test_filter_skips_handler()** (4 connections) — `tests/test_event_bus.py`
- **Subscription** (3 connections) — `core/events/bus.py`
- **.publish()** (3 connections) — `core/events/bus.py`
- **.publish_many()** (3 connections) — `core/events/bus.py`
- **.__init__()** (2 connections) — `core/events/handlers/quotes.py`
- **Enum** (2 connections)
- **.clear()** (1 connections) — `core/events/bus.py`
- **.__init__()** (1 connections) — `core/events/bus.py`
- **bad()** (1 connections) — `tests/test_event_bus.py`
- **good()** (1 connections) — `tests/test_event_bus.py`
- **handler_a()** (1 connections) — `tests/test_event_bus.py`
- **handler_b()** (1 connections) — `tests/test_event_bus.py`
- **str** (1 connections)
- **FilterFn** (1 connections)
- *... and 6 more nodes in this community*

## Relationships

- [Event](Event.md) (26 shared connections)
- [test_event_bus.py](test_event_bus.py.md) (16 shared connections)
- [make_event](make_event.md) (9 shared connections)
- [reentry_at_cost.py](reentry_at_cost.py.md) (8 shared connections)
- [test_gtt_quote_handler_push_calls_on_quote](test_gtt_quote_handler_push_calls_on_quote.md) (7 shared connections)
- [RunMode](RunMode.md) (7 shared connections)
- [FeedSupervisorService](FeedSupervisorService.md) (3 shared connections)
- [logging.py](logging.py.md) (3 shared connections)
- [services/__init__.py](services-__init__.py.md) (3 shared connections)
- [typing](typing.md) (3 shared connections)
- [factory.py](factory.py.md) (2 shared connections)
- [ExecutionService](ExecutionService.md) (2 shared connections)

## Source Files

- `core/events/__init__.py`
- `core/events/bus.py`
- `core/events/handlers/quotes.py`
- `core/events/types.py`
- `tests/test_event_bus.py`

## Audit Trail

- EXTRACTED: 98 (72%)
- INFERRED: 39 (28%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*