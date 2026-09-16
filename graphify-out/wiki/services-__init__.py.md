# services/__init__.py

> 14 nodes

## Key Concepts

- **services/__init__.py** (12 connections) — `core/events/services/__init__.py`
- **StrategyEvalService** (10 connections) — `core/events/services/strategy_eval.py`
- **scheduled_eval.py** (8 connections) — `core/events/services/scheduled_eval.py`
- **strategy_eval.py** (8 connections) — `core/events/services/strategy_eval.py`
- **services/execution.py** (6 connections) — `core/events/services/execution.py`
- **.evaluate_and_publish_intents()** (4 connections) — `core/events/services/strategy_eval.py`
- **.handle_bar_closed()** (3 connections) — `core/events/services/strategy_eval.py`
- **.__init__()** (2 connections) — `core/events/services/strategy_eval.py`
- **Any** (2 connections)
- **IntentCreated → OMS enqueue (was LiveEngine._enqueue_entry_intents_grouped…** (1 connections) — `core/events/services/execution.py`
- **Event-path services — orchestration extracted from LiveEngine for testability.** (1 connections) — `core/events/services/__init__.py`
- **ScheduledSlot orchestration.** (1 connections) — `core/events/services/scheduled_eval.py`
- **Strategy evaluation → IntentCreated publish (was handler + LiveEngine eval loop…** (1 connections) — `core/events/services/strategy_eval.py`
- **Runs parallel strategy evaluation and publishes IntentCreated events.…** (1 connections) — `core/events/services/strategy_eval.py`

## Relationships

- [Event](Event.md) (7 shared connections)
- [ExitRolloverService](ExitRolloverService.md) (3 shared connections)
- [EventType](EventType.md) (3 shared connections)
- [make_event](make_event.md) (3 shared connections)
- [typing](typing.md) (3 shared connections)
- [RunMode](RunMode.md) (3 shared connections)
- [test_event_bus.py](test_event_bus.py.md) (2 shared connections)
- [ExecutionService](ExecutionService.md) (2 shared connections)
- [logging.py](logging.py.md) (1 shared connections)
- [FeedSupervisorService](FeedSupervisorService.md) (1 shared connections)

## Source Files

- `core/events/services/__init__.py`
- `core/events/services/execution.py`
- `core/events/services/scheduled_eval.py`
- `core/events/services/strategy_eval.py`

## Audit Trail

- EXTRACTED: 41 (93%)
- INFERRED: 3 (7%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*