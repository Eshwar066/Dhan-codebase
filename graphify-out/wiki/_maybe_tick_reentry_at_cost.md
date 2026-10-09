# ._maybe_tick_reentry_at_cost

> 13 nodes

## Key Concepts

- **._maybe_tick_reentry_at_cost()** (10 connections) — `core/engine/live_engine.py`
- **Event bus (live engine)** (9 connections) — `docs/EVENT_BUS.md`
- **.needs_tick_queue()** (7 connections) — `core/engine/live_engine.py`
- **QuoteUpdated (push, not poll)** (4 connections) — `docs/EVENT_BUS.md`
- **Wiring (manifest-driven)** (4 connections) — `docs/EVENT_BUS.md`
- **Events** (3 connections) — `docs/EVENT_BUS.md`
- **EVENT_BUS.md** (1 connections) — `docs/EVENT_BUS.md`
- **Adding a strategy subscriber** (1 connections) — `docs/EVENT_BUS.md`
- **Audit log** (1 connections) — `docs/EVENT_BUS.md`
- **Package** (1 connections) — `docs/EVENT_BUS.md`
- **Tests** (1 connections) — `docs/EVENT_BUS.md`
- **True when candle aggregation or GTT QuoteUpdated push needs the tick queue.** (1 connections) — `core/engine/live_engine.py`
- **OMS poll: place same-contract re-entries when premium returns to cost. When the…** (1 connections) — `core/engine/live_engine.py`

## Relationships

- [.start](start.md) (4 shared connections)
- [reentry_at_cost.py](reentry_at_cost.py.md) (3 shared connections)
- [LiveEngine](LiveEngine.md) (2 shared connections)
- [Any](Any.md) (2 shared connections)
- [test_event_bus.py](test_event_bus.py.md) (2 shared connections)
- [make_event](make_event.md) (1 shared connections)
- [ReentryAtCostBook](ReentryAtCostBook.md) (1 shared connections)
- [.create_live_engine](create_live_engine.md) (1 shared connections)
- [ExitRolloverService](ExitRolloverService.md) (1 shared connections)
- [._set_order_state](_set_order_state.md) (1 shared connections)

## Source Files

- `core/engine/live_engine.py`
- `docs/EVENT_BUS.md`

## Audit Trail

- EXTRACTED: 22 (71%)
- INFERRED: 9 (29%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*