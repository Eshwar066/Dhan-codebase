# Event

> 46 nodes

## Key Concepts

- **Event** (56 connections) — `core/events/types.py`
- **EngineEventContext** (52 connections) — `core/events/context.py`
- **context.py** (17 connections) — `core/events/context.py`
- **ScheduledEvalService** (12 connections) — `core/events/services/scheduled_eval.py`
- **gtt.py** (12 connections) — `core/events/handlers/gtt.py`
- **market.py** (11 connections) — `core/events/handlers/market.py`
- **GttQuoteHandler** (10 connections) — `core/events/handlers/gtt.py`
- **fills.py** (10 connections) — `core/events/handlers/fills.py`
- **scheduled.py** (10 connections) — `core/events/handlers/scheduled.py`
- **BarClosedEntryHandler** (8 connections) — `core/events/handlers/market.py`
- **FillAuditHandler** (7 connections) — `core/events/handlers/fills.py`
- **BarClosedExitHandler** (7 connections) — `core/events/handlers/market.py`
- **ReentryAtCostQuoteHandler** (7 connections) — `core/events/handlers/reentry_at_cost.py`
- **ScheduledSlotHandler** (7 connections) — `core/events/handlers/scheduled.py`
- **register_bar_closed_handlers()** (7 connections) — `core/events/handlers/market.py`
- **register_fill_handlers()** (6 connections) — `core/events/handlers/fills.py`
- **register_gtt_quote_handler()** (6 connections) — `core/events/handlers/gtt.py`
- **register_scheduled_slot_handler()** (6 connections) — `core/events/handlers/scheduled.py`
- **.__call__()** (4 connections) — `core/events/handlers/gtt.py`
- **_quote_from_payload()** (4 connections) — `core/events/handlers/gtt.py`
- **.__call__()** (3 connections) — `core/events/handlers/market.py`
- **.__call__()** (3 connections) — `core/events/handlers/reentry_at_cost.py`
- **.__call__()** (3 connections) — `core/events/handlers/scheduled.py`
- **.handle_scheduled_slot()** (3 connections) — `core/events/services/scheduled_eval.py`
- **.__init__()** (2 connections) — `core/events/handlers/fills.py`
- *... and 21 more nodes in this community*

## Relationships

- [EventType](EventType.md) (26 shared connections)
- [test_event_bus.py](test_event_bus.py.md) (18 shared connections)
- [FeedSupervisorService](FeedSupervisorService.md) (12 shared connections)
- [ExecutionService](ExecutionService.md) (10 shared connections)
- [make_event](make_event.md) (10 shared connections)
- [reentry_at_cost.py](reentry_at_cost.py.md) (8 shared connections)
- [test_gtt_quote_handler_push_calls_on_quote](test_gtt_quote_handler_push_calls_on_quote.md) (8 shared connections)
- [services/__init__.py](services-__init__.py.md) (7 shared connections)
- [logging.py](logging.py.md) (6 shared connections)
- [EventTapHandler](EventTapHandler.md) (5 shared connections)
- [RunMode](RunMode.md) (5 shared connections)
- [typing](typing.md) (3 shared connections)

## Source Files

- `core/events/context.py`
- `core/events/handlers/fills.py`
- `core/events/handlers/gtt.py`
- `core/events/handlers/market.py`
- `core/events/handlers/reentry_at_cost.py`
- `core/events/handlers/scheduled.py`
- `core/events/services/scheduled_eval.py`
- `core/events/types.py`

## Audit Trail

- EXTRACTED: 162 (76%)
- INFERRED: 51 (24%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*