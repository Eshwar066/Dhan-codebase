# Project structure

High-level layout and flow. See **README.md** for architecture and **core/README.txt** for directory details.

## Directory tree

```
Dhan codebase/
├── core/
│   ├── data/
│   │   ├── datalayer/         IDataProvider, DhanDataProvider
│   │   ├── sources/           DhanSource, NSEClient
│   │   ├── adapters/          NSEAdapter, DhanAdapter (option chain; use StrategyContext)
│   │   ├── data_router.py
│   │   ├── option_chain_service.py
│   │   └── candle_service.py
│   ├── engine/
│   │   ├── base_engine.py     build_context() → StrategyContext
│   │   ├── backtest_engine.py
│   │   └── live_engine.py
│   ├── library/
│   │   └── dhan_tradehull.py  In-project Dhan API (OHLC, option chain, orders)
│   ├── models/
│   │   ├── order_intent.py    OrderIntent
│   │   └── strategy_context.py  StrategyContext (typed ctx)
│   ├── broker/                Order placement (Dhan, Delta stub, Simulated)
│   ├── orderExecution/        OrderRouter, RiskManager, IntentStore, PositionManager
│   ├── strategies/            base, IndiaMktMixins, Leaps, Inside_bar_candle, registry
│   └── utils/                 expiry_resolver, instruments, session
├── run/
│   ├── config.py              RUN_MODE, STRATEGY_JOBS
│   └── main.py                Wire and run jobs
├── logs/
├── Dependencies/              Instrument file (all_instrument{date}.csv)
├── requirements.txt
└── README.md
```

## Flow (ASCII)

```
Data layer (IDataProvider) → Engine → Strategy.on_candle(candle, ctx: StrategyContext)
                                       → OrderIntent(s)
                                       → OrderRouter → RiskManager → Broker
                                                                     → PositionManager
```

## Key files

| Area        | Files |
|------------|--------|
| Entry      | run/main.py, run/config.py |
| Data feed  | core/data/datalayer/, core/data/sources/dhan_source.py, core/data/option_chain_service.py |
| Context    | core/models/strategy_context.py |
| Engine     | core/engine/base_engine.py, backtest_engine.py, live_engine.py |
| Strategy   | core/strategies/base.py, IndiaMktMixins.py, Leaps/LeapsQuatery_RSI_52_32.py |
| Orders     | core/orderExecution/order_router.py, risk_manager.py, intent_store.py, position_manager.py |
| Broker     | core/broker/dhanbroker.py, dhan_broker_api.py, simulated_broker.py, delta_broker.py |
| Dhan API   | core/library/dhan_tradehull.py |

## README index

- **README.md** (root) – overview, flow, StrategyContext, data vs broker, improvements, live roadmap
- **PROJECT_STRUCTURE.md** – this file; directory tree and README index
- **core/README.txt** – core directory layout
- **core/models/README.md** – OrderIntent, StrategyContext
- **core/broker/README.md** – broker layer, files, Dhan/Delta/Simulated
- **core/data/datalayer/README.md** – data layer, IDataProvider, files
- **core/library/README.md** – Dhan Tradehull usage and data/order APIs
- **core/orderExecution/README.md** – intent flow, risk, position manager, files
- **core/utils/instruments/README.md** – InstrumentStore, CSV columns
- **run/README.txt** – main.py, config, Dependencies, credentials
- **core/strategies/Leaps/readme.txt** – LEAPS RSI strategy spec and implementation refs
- **core/strategies/Inside_bar_candle/readme.txt** – Inside bar strategy and engine flow
