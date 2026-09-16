# ExitRolloverService

> 21 nodes

## Key Concepts

- **ExitRolloverService** (14 connections) — `core/events/services/exit_rollover.py`
- **Services (logic ownership)** (11 connections) — `docs/EVENT_BUS.md`
- **._run_exits_and_rollover()** (8 connections) — `core/engine/live_engine.py`
- **_position_matches_candle_symbol()** (7 connections) — `core/events/services/exit_rollover.py`
- **exit_rollover.py** (7 connections) — `core/events/services/exit_rollover.py`
- **.run_exits_and_rollover()** (6 connections) — `core/events/services/exit_rollover.py`
- **Any** (6 connections)
- **._run_exits_and_rollover_for_closed_bar()** (5 connections) — `core/engine/live_engine.py`
- **.run_for_closed_bar()** (4 connections) — `core/events/services/exit_rollover.py`
- **_position_allows_strategy_exit()** (4 connections) — `core/events/services/exit_rollover.py`
- **_structure_underlying()** (4 connections) — `core/events/services/exit_rollover.py`
- **.__init__()** (2 connections) — `core/events/services/exit_rollover.py`
- **Exits + monthly hedge rollover on every closed live-feed bar (backtest parity).** (1 connections) — `core/engine/live_engine.py`
- **Strategy exits and hedge rollover — always run before entry evaluation.** (1 connections) — `core/engine/live_engine.py`
- **Exit + hedge rollover orchestration (was LiveEngine._run_exits_*).** (1 connections) — `core/events/services/exit_rollover.py`
- **Strategy exits and hedge rollover — always run before entry evaluation.** (1 connections) — `core/events/services/exit_rollover.py`
- **Parse ``Strategy:BTCUSD:sleeve:...`` → BTCUSD when present.** (1 connections) — `core/events/services/exit_rollover.py`
- **True when ``position`` belongs to ``symbol`` (candle underlying). Used after…** (1 connections) — `core/events/services/exit_rollover.py`
- **Runs strategy ``should_exit`` / ``on_position_exit`` and hedge rollover.…** (1 connections) — `core/events/services/exit_rollover.py`
- **Exits + monthly hedge rollover on every closed live-feed bar.** (1 connections) — `core/events/services/exit_rollover.py`
- **MAIN book and post-partial trail legs (tag may become MAIN_TARGET after TARGET…** (1 connections) — `core/events/services/exit_rollover.py`

## Relationships

- [LiveEngine](LiveEngine.md) (4 shared connections)
- [test_event_bus.py](test_event_bus.py.md) (3 shared connections)
- [services/__init__.py](services-__init__.py.md) (3 shared connections)
- [Any](Any.md) (3 shared connections)
- [.start](start.md) (2 shared connections)
- [test_exit_rollover_service_filters_scheduled](test_exit_rollover_service_filters_scheduled.md) (1 shared connections)
- [factory.py](factory.py.md) (1 shared connections)
- [Live Engine](Live_Engine.md) (1 shared connections)
- [Runtime notes](Runtime_notes.md) (1 shared connections)
- [DirectionalOptionSellingTests](DirectionalOptionSellingTests.md) (1 shared connections)
- [RunMode](RunMode.md) (1 shared connections)
- [typing](typing.md) (1 shared connections)

## Source Files

- `core/engine/live_engine.py`
- `core/events/services/exit_rollover.py`
- `docs/EVENT_BUS.md`

## Audit Trail

- EXTRACTED: 44 (77%)
- INFERRED: 13 (23%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*