# Project Structure (Current)

Compact map of the current repository layout and runtime ownership.

## Top-Level Tree

```text
Algo/
├── README.md
├── PROJECT_STRUCTURE.md
├── PROJECT_FLOW_CHART.md
├── run/
│   ├── main.py
│   ├── config.py
│   └── engine_config.py
├── core/
│   ├── engine/
│   ├── strategies/
│   ├── data/
│   ├── orderExecution/
│   ├── broker/
│   ├── models/
│   ├── utils/
│   ├── universe/
│   ├── analytics/
│   └── library/
├── logger/
├── logs/
├── reports/
├── Dependencies/
├── docs/
└── graphify-out/
```

## Ownership by Layer

- `run/`  
  Process entry and config translation (`STRATEGY_JOBS` -> `EngineConfig`).

- `core/engine/`  
  Engine orchestration:
  - `base_engine.py`: shared context/wiring
  - `backtest_engine.py`: historical replay engine
  - `live_engine.py`: live loop, strategy workers, intent/OMS pipeline
  - `factory.py`: builds isolated engine stacks
  - `supervisor.py`: optional multi-engine process supervisor

- `core/strategies/`  
  Strategy implementations and registry (`registry.py`, `base.py`, strategy packages).

- `core/data/`  
  Market data and feed stack:
  - `sources/`: broker/API fetchers
  - `datalayer/`: provider abstraction for engines
  - `feeds/`: websocket/feed adapters
  - `candle_aggregator.py`: tick -> closed-candle aggregation
  - `option_chain_service.py`, `data_router.py`

- `core/orderExecution/`  
  OMS and execution controls:
  - `intent_store.py`
  - `risk_manager.py`
  - `position_manager.py`
  - `order_router.py`
  - `account_router.py`

- `core/broker/internal/`  
  Broker adapters:
  - `dhan/`
  - `delta/`
  - `simulated/` (paper/backtest execution)

- `logger/`  
  Runtime logging helpers (`engine_logger`, `trade_logger`, `open_positions_logger`).

- `logs/`, `reports/`  
  Runtime output:
  - structured logs
  - open positions snapshots
  - EOD and shutdown reports
  - intent pipeline journal

## Runtime Data Flow (Current)

```text
run/main.py
  -> EngineFactory.create_engine(config)
  -> LiveEngine / BacktestEngine

LiveEngine (feed-driven):
WebSocket Feed -> Tick Queue -> CandleAggregator -> Strategy Worker(s)
  -> intent_queue -> AccountRouter
  -> queue per (account_id, symbol)
  -> OMS worker (retry + token bucket + breaker)
  -> OrderRouter -> Broker
  -> fills -> PositionManager (trade-led)
```

## Important Files to Start With

- Entry/config:
  - `run/main.py`
  - `run/config.py`
  - `run/engine_config.py`

- Engine/flow:
  - `core/engine/factory.py`
  - `core/engine/live_engine.py`
  - `core/engine/backtest_engine.py`

- OMS:
  - `core/orderExecution/order_router.py`
  - `core/orderExecution/intent_store.py`
  - `core/orderExecution/position_manager.py`
  - `core/orderExecution/account_router.py`

- Data/feed:
  - `core/data/candle_aggregator.py`
  - `core/data/feeds/dhan_feed.py`
  - `core/data/feeds/delta_feed.py`

## Notes

- Use `README.md` for the concise project overview.
- Use `PROJECT_FLOW_CHART.md` for HLD + LLD execution diagrams.
