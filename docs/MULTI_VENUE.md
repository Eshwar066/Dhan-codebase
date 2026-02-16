# Multi-Venue Architecture

Two fully isolated engines: **Engine_Dhan** (India markets) and **Engine_Delta** (Crypto). No shared OMS state.

---

## 1. Folder Structure

```
run/
  config.py              # RUN_MODE, STRATEGY_JOBS (each job has "venue": "DHAN" | "DELTA")
  engine_config.py       # EngineConfig dataclass, example_dhan_* / example_delta_* configs
  main.py                # Entry point; --venue filter; uses EngineFactory

core/
  engine/
    base_engine.py       # Unchanged: strategy, data, instrument_store, position_manager, build_context()
    backtest_engine.py   # Unchanged: single-venue backtest loop
    live_engine.py       # Unchanged: single-venue live loop
    factory.py           # EngineFactory.create_engine(config) → BacktestEngine | LiveEngine
    supervisor.py        # Optional: Supervisor holds multiple engines, start_all/stop_all, health_check
    __init__.py

  data/
    sources/             # DhanSource, DeltaSource
    datalayer/           # DhanDataProvider, DeltaDataProvider
    feeds/               # DeltaWebSocketFeed (DhanWebSocketFeed when added)

  broker/                # DhanBroker, DeltaBroker, SimulatedBroker
  orderExecution/       # OrderRouter, RiskManager, PositionManager, IntentStore (no shared instances)
  ...
```

---

## 2. EngineFactory

**Location:** `core/engine/factory.py`

**Usage:**

```python
from run.engine_config import EngineConfig
from run.config import RunMode
from core.engine.factory import EngineFactory

# Dhan live engine
config = EngineConfig(
    broker_name="DHAN",
    run_mode=RunMode.LIVE,
    strategy_name="LEAPS_RSI",
    symbols=["NIFTY"],
    live={"exchange": "INDEX", "sector": "YES", "rsi": "YES"},
    backtest={...},
)
engine = EngineFactory.create_engine(config)
engine.start(exchange="INDEX", sector="YES", rsi="YES")

# Delta backtest engine
config = EngineConfig(
    broker_name="DELTA",
    run_mode=RunMode.BACKTEST,
    strategy_name="FuturesEMAHighLow",
    symbols=["BTCUSD"],
    delta_testnet=True,
    delta_india=False,
    backtest={"start_date": "2024-03-20", "end_date": "2025-03-30", "timeframe": "60", ...},
)
engine = EngineFactory.create_engine(config)
engine.run(symbols=config.symbols, **config.backtest)
```

**What Factory builds per venue:**

| Component           | Dhan stack                    | Delta stack                     |
|--------------------|-------------------------------|---------------------------------|
| Data provider       | DhanDataProvider(DhanSource)  | DeltaDataProvider(DeltaSource)  |
| Instrument store   | InstrumentStore(Dependencies/all_instrument*.csv) | InstrumentStore(DELTA, delta_instrument_*.csv) |
| PositionManager    | New instance                  | New instance                    |
| RiskManager        | New instance                  | New instance                    |
| IntentStore        | New instance                  | New instance                    |
| Broker             | DhanBroker(DhanBrokerApi)     | DeltaBroker(DeltaBrokerApi)     |
| OrderRouter        | Wired to Dhan broker          | Wired to Delta broker           |
| CandleService      | CandleService(data_provider)  | CandleService(data_provider)    |
| Realtime feed      | None (Dhan WS when added)     | DeltaWebSocketFeed              |

---

## 3. Example Configs (Dhan and Delta)

**Location:** `run/engine_config.py`

- `example_dhan_live_config()` – Dhan, LIVE, LEAPS_RSI, NIFTY  
- `example_dhan_backtest_config()` – Dhan, BACKTEST, INSIDE_BAR  
- `example_delta_live_config()` – Delta, LIVE, FuturesEMAHighLow, BTCUSD  
- `example_delta_backtest_config()` – Delta, BACKTEST, FuturesEMAHighLow  

Use as:

```python
from run.engine_config import example_delta_live_config
config = example_delta_live_config()
engine = EngineFactory.create_engine(config)
# then engine.start(...) with config.live
```

---

## 4. Running Two Engines in Parallel (Two Processes)

**One process = one venue.** Run two processes for Dhan + Delta in parallel.

**Terminal 1 – Dhan (India):**
```bash
python -m run.main --venue DHAN
```

**Terminal 2 – Delta (Crypto):**
```bash
python -m run.main --venue DELTA
```

- Each process loads only its venue’s jobs from `STRATEGY_JOBS` (filtered by `venue`).
- Each process gets its own engine(s) from `EngineFactory` with an isolated OMS (PositionManager, RiskManager, OrderRouter, Broker).
- No shared state between processes.

**Single process, all jobs (no filter):**
```bash
python -m run.main
```
Runs every job in sequence; each job gets its own engine. For LIVE, the first job’s `engine.start()` blocks, so multiple live jobs only make sense with the Supervisor (threads).

---

## 5. Dependency Injection

- **EngineFactory** is the only place that constructs the full stack (data, instruments, OMS, broker, feed). No global singletons.
- **EngineConfig** carries venue, strategy, symbols, and mode; Factory reads it and injects the right implementations.
- **BaseEngine** is unchanged: it receives `strategy`, `data`, `instrument_store`, `position_manager` and builds `DataRouter` and `OptionChainService` from `data`. No venue logic inside BaseEngine.
- **BacktestEngine / LiveEngine** receive their dependencies in the constructor; no broker or venue routing inside the engine.

---

## 6. No Merged Broker Router

- There is no single “multi-venue” OrderRouter or Broker.
- Each engine has exactly one OrderRouter wired to one Broker (Dhan or Delta).
- One engine = one broker = one risk universe.

---

## 7. Optional: Supervisor (Single Process, Multiple Venues)

To run both Dhan and Delta in **one process** (each engine in its own thread):

```python
from run.engine_config import example_dhan_live_config, example_delta_live_config
from core.engine import Supervisor

sv = Supervisor()
sv.register_from_config(example_dhan_live_config())
sv.register_from_config(example_delta_live_config())
sv.start_all()  # each engine runs in its own thread

# Optional: health
print(sv.health_check())
```

Supervisor does **not** execute trades; it only starts/stops engines and exposes a health/metrics scaffold.
