# test_event_bus.py

> 36 nodes

## Key Concepts

- **test_event_bus.py** (38 connections) — `tests/test_event_bus.py`
- **wiring.py** (37 connections) — `core/events/wiring.py`
- **wire_event_bus()** (29 connections) — `core/events/wiring.py`
- **resolve_strategy_subscriptions()** (14 connections) — `core/events/subscriptions.py`
- **strategy_opts_into_reentry()** (12 connections) — `core/events/handlers/reentry_at_cost.py`
- **attach_event_services()** (11 connections) — `core/events/services/__init__.py`
- **collect_enabled_events()** (11 connections) — `core/events/subscriptions.py`
- **events/subscriptions.py** (11 connections) — `core/events/subscriptions.py`
- **bar_closed_filter_for_strategies()** (10 connections) — `core/events/subscriptions.py`
- **resolve_engine_subscriptions()** (6 connections) — `core/events/wiring.py`
- **Any** (6 connections)
- **get_subscription_table()** (5 connections) — `core/events/subscriptions.py`
- **event_enabled()** (4 connections) — `core/events/subscriptions.py`
- **test_bar_closed_filter_timeframe()** (4 connections) — `tests/test_event_bus.py`
- **TestStrategyOptsIn** (3 connections) — `core/events/handlers/tests/test_reentry_at_cost.py`
- **_strategy_id()** (3 connections) — `core/events/subscriptions.py`
- **create_event_bus()** (3 connections) — `core/events/wiring.py`
- **_loaded_strategies()** (3 connections) — `core/events/wiring.py`
- **test_collect_enabled_events_union()** (3 connections) — `tests/test_event_bus.py`
- **test_resolve_strategy_subscriptions_from_table()** (3 connections) — `tests/test_event_bus.py`
- **.test_detects_class_policy()** (2 connections) — `core/events/handlers/tests/test_reentry_at_cost.py`
- **.test_disabled_or_missing()** (2 connections) — `core/events/handlers/tests/test_reentry_at_cost.py`
- **test_attach_event_services()** (2 connections) — `tests/test_event_bus.py`
- **_filter()** (1 connections) — `core/events/subscriptions.py`
- **__init__()** (1 connections) — `tests/test_event_bus.py`
- *... and 11 more nodes in this community*

## Relationships

- [Event](Event.md) (18 shared connections)
- [EventType](EventType.md) (16 shared connections)
- [reentry_at_cost.py](reentry_at_cost.py.md) (10 shared connections)
- [StrategyManifest](StrategyManifest.md) (7 shared connections)
- [ExecutionService](ExecutionService.md) (6 shared connections)
- [FeedSupervisorService](FeedSupervisorService.md) (6 shared connections)
- [make_event](make_event.md) (4 shared connections)
- [factory.py](factory.py.md) (4 shared connections)
- [test_gtt_quote_handler_push_calls_on_quote](test_gtt_quote_handler_push_calls_on_quote.md) (4 shared connections)
- [ExitRolloverService](ExitRolloverService.md) (3 shared connections)
- [RunMode](RunMode.md) (2 shared connections)
- [services/__init__.py](services-__init__.py.md) (2 shared connections)

## Source Files

- `core/events/handlers/reentry_at_cost.py`
- `core/events/handlers/tests/test_reentry_at_cost.py`
- `core/events/services/__init__.py`
- `core/events/subscriptions.py`
- `core/events/wiring.py`
- `tests/test_event_bus.py`

## Audit Trail

- EXTRACTED: 157 (95%)
- INFERRED: 8 (5%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*