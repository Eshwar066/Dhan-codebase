# make_event

> 14 nodes

## Key Concepts

- **make_event()** (38 connections) — `core/events/types.py`
- **test_reentry_at_cost.py** (20 connections) — `core/events/handlers/tests/test_reentry_at_cost.py`
- **ReentryAtCostFillHandler** (12 connections) — `core/events/handlers/reentry_at_cost.py`
- **TestFillHandler** (6 connections) — `core/events/handlers/tests/test_reentry_at_cost.py`
- **.test_main_entry_stops()** (3 connections) — `core/events/handlers/tests/test_reentry_at_cost.py`
- **.test_main_sl_arms()** (3 connections) — `core/events/handlers/tests/test_reentry_at_cost.py`
- **.test_main_sl_skips_partial_fill()** (3 connections) — `core/events/handlers/tests/test_reentry_at_cost.py`
- **TestStopHelper** (2 connections) — `core/events/handlers/tests/test_reentry_at_cost.py`
- **.__init__()** (2 connections) — `core/events/handlers/reentry_at_cost.py`
- **.test_stop_on_main_opened()** (2 connections) — `core/events/handlers/tests/test_reentry_at_cost.py`
- **.to_log_dict()** (2 connections) — `core/events/types.py`
- **Any** (2 connections)
- **IntentFilled → arm / stop reentry-at-cost watches.** (1 connections) — `core/events/handlers/reentry_at_cost.py`
- **Unit tests for reentry-at-cost event adapters (GTT-style).** (1 connections) — `core/events/handlers/tests/test_reentry_at_cost.py`

## Relationships

- [reentry_at_cost.py](reentry_at_cost.py.md) (12 shared connections)
- [Event](Event.md) (10 shared connections)
- [EventType](EventType.md) (9 shared connections)
- [RunMode](RunMode.md) (5 shared connections)
- [test_event_bus.py](test_event_bus.py.md) (4 shared connections)
- [test_gtt_quote_handler_push_calls_on_quote](test_gtt_quote_handler_push_calls_on_quote.md) (4 shared connections)
- [.start](start.md) (3 shared connections)
- [services/__init__.py](services-__init__.py.md) (3 shared connections)
- [factory.py](factory.py.md) (2 shared connections)
- [LiveEngineHelpersMixin](LiveEngineHelpersMixin.md) (1 shared connections)
- [._check_feed_stall_fail_safe](_check_feed_stall_fail_safe.md) (1 shared connections)
- [._maybe_tick_reentry_at_cost](_maybe_tick_reentry_at_cost.md) (1 shared connections)

## Source Files

- `core/events/handlers/reentry_at_cost.py`
- `core/events/handlers/tests/test_reentry_at_cost.py`
- `core/events/types.py`

## Audit Trail

- EXTRACTED: 73 (95%)
- INFERRED: 4 (5%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*