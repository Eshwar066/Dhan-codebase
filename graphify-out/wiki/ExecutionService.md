# ExecutionService

> 14 nodes

## Key Concepts

- **ExecutionService** (14 connections) — `core/events/services/execution.py`
- **handlers/execution.py** (10 connections) — `core/events/handlers/execution.py`
- **IntentCreatedHandler** (7 connections) — `core/events/handlers/execution.py`
- **register_intent_created_handler()** (6 connections) — `core/events/handlers/execution.py`
- **.__call__()** (3 connections) — `core/events/handlers/execution.py`
- **.enqueue_intent()** (3 connections) — `core/events/services/execution.py`
- **.handle_intent_created()** (3 connections) — `core/events/services/execution.py`
- **test_execution_service_enqueues()** (3 connections) — `tests/test_event_bus.py`
- **.__init__()** (2 connections) — `core/events/handlers/execution.py`
- **.__init__()** (2 connections) — `core/events/services/execution.py`
- **Any** (2 connections)
- **_enqueue_entry_intents_grouped()** (1 connections) — `tests/test_event_bus.py`
- **IntentCreated → ExecutionService.** (1 connections) — `core/events/handlers/execution.py`
- **Enqueues entry intents into the OMS pipeline.** (1 connections) — `core/events/services/execution.py`

## Relationships

- [Event](Event.md) (10 shared connections)
- [test_event_bus.py](test_event_bus.py.md) (6 shared connections)
- [services/__init__.py](services-__init__.py.md) (2 shared connections)
- [EventType](EventType.md) (2 shared connections)
- [ExitRolloverService](ExitRolloverService.md) (1 shared connections)
- [RunMode](RunMode.md) (1 shared connections)

## Source Files

- `core/events/handlers/execution.py`
- `core/events/services/execution.py`
- `tests/test_event_bus.py`

## Audit Trail

- EXTRACTED: 33 (82%)
- INFERRED: 7 (18%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*