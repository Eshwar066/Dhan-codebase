# Supervisor

> 18 nodes

## Key Concepts

- **Supervisor** (14 connections) — `core/engine/supervisor.py`
- **EngineHandle** (7 connections) — `core/engine/supervisor.py`
- **.register_engine()** (5 connections) — `core/engine/supervisor.py`
- **.register_from_config()** (5 connections) — `core/engine/supervisor.py`
- **._run_live_engine()** (4 connections) — `core/engine/supervisor.py`
- **.health_check()** (3 connections) — `core/engine/supervisor.py`
- **Any** (3 connections)
- **.engines()** (2 connections) — `core/engine/supervisor.py`
- **.start_all()** (2 connections) — `core/engine/supervisor.py`
- **.stop_all()** (2 connections) — `core/engine/supervisor.py`
- **.__init__()** (1 connections) — `core/engine/supervisor.py`
- **Scaffold: return minimal health per venue. Override or extend for real metrics…** (1 connections) — `core/engine/supervisor.py`
- **One engine + its config and optional thread.** (1 connections) — `core/engine/supervisor.py`
- **Holds multiple engines. Can start/stop them (each in its own thread). Monitors…** (1 connections) — `core/engine/supervisor.py`
- **Create engine from config and register. Does not start.** (1 connections) — `core/engine/supervisor.py`
- **Register an already-created engine.** (1 connections) — `core/engine/supervisor.py`
- **Start all registered live engines in separate threads. BacktestEngine handles…** (1 connections) — `core/engine/supervisor.py`
- **Signal all engine threads to stop (if they support it).** (1 connections) — `core/engine/supervisor.py`

## Relationships

- [factory.py](factory.py.md) (4 shared connections)
- [EngineConfig](EngineConfig.md) (4 shared connections)
- [.create_live_engine](create_live_engine.md) (2 shared connections)
- [LiveEngine](LiveEngine.md) (2 shared connections)
- [Event](Event.md) (1 shared connections)

## Source Files

- `core/engine/supervisor.py`

## Audit Trail

- EXTRACTED: 30 (88%)
- INFERRED: 4 (12%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*