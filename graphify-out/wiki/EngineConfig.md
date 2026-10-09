# EngineConfig

> 23 nodes

## Key Concepts

- **EngineConfig** (32 connections) — `run/engine_config.py`
- **job_to_engine_config()** (15 connections) — `run/main.py`
- **Project Structure (Current)** (6 connections) — `utils/PROJECT_STRUCTURE.md`
- **example_delta_backtest_config()** (4 connections) — `run/engine_config.py`
- **example_delta_live_config()** (4 connections) — `run/engine_config.py`
- **example_dhan_backtest_config()** (4 connections) — `run/engine_config.py`
- **example_dhan_live_config()** (4 connections) — `run/engine_config.py`
- **Operational boundaries** (4 connections) — `docs/runtime_flow.md`
- **.dependencies_dir()** (2 connections) — `run/engine_config.py`
- **Ownership by Layer** (2 connections) — `utils/PROJECT_STRUCTURE.md`
- **.__post_init__()** (1 connections) — `run/engine_config.py`
- **Path** (1 connections)
- **PROJECT_STRUCTURE.md** (1 connections) — `utils/PROJECT_STRUCTURE.md`
- **Important Files to Start With** (1 connections) — `utils/PROJECT_STRUCTURE.md`
- **Notes** (1 connections) — `utils/PROJECT_STRUCTURE.md`
- **Runtime Data Flow (Current)** (1 connections) — `utils/PROJECT_STRUCTURE.md`
- **Top-Level Tree** (1 connections) — `utils/PROJECT_STRUCTURE.md`
- **Example: Dhan live engine for India markets (NIFTY, equities) with capital.** (1 connections) — `run/engine_config.py`
- **Example: Dhan backtest only.** (1 connections) — `run/engine_config.py`
- **Example: Delta live engine for crypto (BTCUSD, etc.) with capital bucket.** (1 connections) — `run/engine_config.py`
- **Example: Delta backtest only.** (1 connections) — `run/engine_config.py`
- **Config for a single-venue engine. All OMS components will be built from this…** (1 connections) — `run/engine_config.py`
- **Build EngineConfig from a resolved engine job dict.** (1 connections) — `run/main.py`

## Relationships

- [RunMode](RunMode.md) (12 shared connections)
- [.create_live_engine](create_live_engine.md) (9 shared connections)
- [main.py](main.py.md) (5 shared connections)
- [Supervisor](Supervisor.md) (4 shared connections)
- [factory.py](factory.py.md) (2 shared connections)
- [force_leaps_cycle.py](force_leaps_cycle.py.md) (2 shared connections)
- [roll_leaps_hedge.py](roll_leaps_hedge.py.md) (2 shared connections)
- [dummy_live.py](dummy_live.py.md) (2 shared connections)
- [option_buildup_scheduler.py](option_buildup_scheduler.py.md) (1 shared connections)
- [AccountRouter](AccountRouter.md) (1 shared connections)
- [CandleAggregator](CandleAggregator.md) (1 shared connections)
- [Phased plan](Phased_plan.md) (1 shared connections)

## Source Files

- `docs/runtime_flow.md`
- `run/engine_config.py`
- `run/main.py`
- `utils/PROJECT_STRUCTURE.md`

## Audit Trail

- EXTRACTED: 50 (75%)
- INFERRED: 17 (25%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*