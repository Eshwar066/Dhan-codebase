# Component Details

> 14 nodes

## Key Concepts

- **Component Details** (7 connections) — `docs/ORDER_LOGGING_PIPELINE.md`
- **LiveEngine (`core/engine/live_engine.py`)** (7 connections) — `docs/ORDER_LOGGING_PIPELINE.md`
- **.evaluate_sim_broker_stops()** (4 connections) — `core/engine/base_engine.py`
- **BacktestEngine (`core/engine/backtest_engine.py`)** (4 connections) — `docs/ORDER_LOGGING_PIPELINE.md`
- **2. Engine Layer** (3 connections) — `docs/ORDER_LOGGING_PIPELINE.md`
- **4. Broker Layer** (3 connections) — `docs/ORDER_LOGGING_PIPELINE.md`
- **6. Trade Logger (`utils/logger/trade_logger.py`)** (3 connections) — `docs/ORDER_LOGGING_PIPELINE.md`
- **Any** (1 connections)
- **5. Position Manager (`core/orderExecution/position_manager.py`)** (1 connections) — `docs/ORDER_LOGGING_PIPELINE.md`
- **Live Brokers (DhanBroker, DeltaBroker, KotakBroker)** (1 connections) — `docs/ORDER_LOGGING_PIPELINE.md`
- **SimulatedBroker (`core/broker/internal/simulated/broker.py`)** (1 connections) — `docs/ORDER_LOGGING_PIPELINE.md`
- **TRADE_LOG_COLUMNS (completed round-trips)** (1 connections) — `docs/ORDER_LOGGING_PIPELINE.md`
- **TRADES_COLUMNS (per-fill events)** (1 connections) — `docs/ORDER_LOGGING_PIPELINE.md`
- **SimulatedBroker: fire resting MAIN_SL when option LTP crosses trigger…** (1 connections) — `core/engine/base_engine.py`

## Relationships

- [SimulatedBroker](SimulatedBroker.md) (2 shared connections)
- [BacktestEngine](BacktestEngine.md) (2 shared connections)
- [Any](Any.md) (2 shared connections)
- [factory.py](factory.py.md) (1 shared connections)
- [IndiaMktMixins](IndiaMktMixins.md) (1 shared connections)
- [Order Logging Pipeline](Order_Logging_Pipeline.md) (1 shared connections)
- [DeltaBroker](DeltaBroker.md) (1 shared connections)
- [DhanBroker](DhanBroker.md) (1 shared connections)
- [KotakBroker](KotakBroker.md) (1 shared connections)

## Source Files

- `core/engine/base_engine.py`
- `docs/ORDER_LOGGING_PIPELINE.md`

## Audit Trail

- EXTRACTED: 16 (64%)
- INFERRED: 9 (36%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*