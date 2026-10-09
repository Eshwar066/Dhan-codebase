# main.py

> 19 nodes

## Key Concepts

- **main.py** (22 connections) — `run/main.py`
- **configure_process_logging()** (14 connections) — `run/engine_config.py`
- **run_engine()** (8 connections) — `run/main.py`
- **main()** (6 connections) — `run/main.py`
- **ISTFormatter** (5 connections) — `run/engine_config.py`
- **acquire_engine_lock()** (5 connections) — `run/engine_lock.py`
- **_lock_path()** (3 connections) — `run/engine_lock.py`
- **.converter()** (2 connections) — `run/engine_config.py`
- **.formatTime()** (2 connections) — `run/engine_config.py`
- **resolve_log_level()** (2 connections) — `run/engine_config.py`
- **_select_jobs()** (2 connections) — `run/main.py`
- **LogRecord** (1 connections)
- **Path** (1 connections)
- **struct_time** (1 connections)
- **Attach a StreamHandler to the root logger and set levels so module loggers…** (1 connections) — `run/engine_config.py`
- **Logging formatter that outputs timestamps in IST (Asia/Kolkata).** (1 connections) — `run/engine_config.py`
- **Exit if another process already holds the lock for this engine_id.** (1 connections) — `run/engine_lock.py`
- **Multi-venue entry point. Uses EngineFactory to build isolated engines per…** (1 connections) — `run/main.py`
- **Create one engine from config and run it (backtest or live).** (1 connections) — `run/main.py`

## Relationships

- [RunMode](RunMode.md) (9 shared connections)
- [EngineConfig](EngineConfig.md) (5 shared connections)
- [.create_live_engine](create_live_engine.md) (4 shared connections)
- [factory.py](factory.py.md) (4 shared connections)
- [dummy_live.py](dummy_live.py.md) (4 shared connections)
- [force_leaps_cycle.py](force_leaps_cycle.py.md) (3 shared connections)
- [roll_leaps_hedge.py](roll_leaps_hedge.py.md) (3 shared connections)
- [logging.py](logging.py.md) (2 shared connections)
- [indicator_history_path](indicator_history_path.md) (1 shared connections)

## Source Files

- `run/engine_config.py`
- `run/engine_lock.py`
- `run/main.py`

## Audit Trail

- EXTRACTED: 54 (95%)
- INFERRED: 3 (5%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*