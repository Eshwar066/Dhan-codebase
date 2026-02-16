# Algo – Multi-Venue Trading System

A production-grade, modular trading system that supports **India markets (Dhan)** and **crypto (Delta Exchange)** with fully isolated engines, config-driven setup, and file-based logging. One engine = one broker = one OMS; no shared state across venues.

---

## Table of contents

1. [What this project does](#what-this-project-does)
2. [Architecture at a glance](#architecture-at-a-glance)
3. [Concurrency model](#concurrency-model)
4. [Candle aggregation model](#candle-aggregation-model)
5. [Determinism guarantee](#determinism-guarantee)
6. [Engine safety model](#engine-safety-model)
7. [Directory structure](#directory-structure)
8. [Key concepts](#key-concepts)
9. [Configuration](#configuration)
10. [How to run](#how-to-run)
11. [Production features](#production-features)
12. [Steps to take (checklist)](#steps-to-take-checklist)
13. [Environment and dependencies](#environment-and-dependencies)
14. [Further reading](#further-reading)

---

## What this project does

- **Backtest** strategies on historical candles (single venue per run).
- **Live / paper trade** with real-time data: **Delta** uses WebSocket; **Dhan** is currently **REST/candle service only** (**DhanWebSocketFeed** planned when Dhan exposes a WebSocket API).
- **Two venues in parallel**: run Dhan (India) and Delta (crypto) in separate processes or in one process via a Supervisor.
- **Per-engine OMS**: each engine has its own PositionManager, RiskManager, OrderRouter, and Broker—no shared orders or positions across venues.
- **Production safeguards**: broker reconciliation on startup, risk kill switch, closed-candle validation, feed health checks, structured JSON logs, EOD CSV export, capital and risk limits per engine.

---

## Architecture at a glance

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           run/main.py                                    │
│  --venue DHAN | DELTA  →  job_to_engine_config()  →  EngineFactory       │
└─────────────────────────────────────────────────────────────────────────┘
                                          │
                    ┌─────────────────────┴─────────────────────┐
                    ▼                                           ▼
         ┌──────────────────────┐                  ┌──────────────────────┐
         │  Engine_Dhan         │                  │  Engine_Delta        │
         │  DhanDataProvider    │                  │  DeltaDataProvider  │
         │  DhanBroker          │                  │  DeltaBroker        │
         │  PositionManager #1  │                  │  PositionManager #2 │
         │  RiskManager #1      │                  │  RiskManager #2     │
         │  OrderRouter → Dhan  │                  │  OrderRouter → Delta │
         │  (Dhan WS planned)   │                  │  DeltaWebSocketFeed  │
         └──────────────────────┘                  └──────────────────────┘
                    │                                           │
                    └─────────────────────┬─────────────────────┘
                                          ▼
                              ┌───────────────────────┐
                              │  BaseEngine           │
                              │  strategy, data,      │
                              │  instrument_store,    │
                              │  position_manager     │
                              │  build_context()      │
                              └───────────────────────┘
                                          │
                    ┌─────────────────────┴─────────────────────┐
                    ▼                                           ▼
         ┌──────────────────────┐                  ┌──────────────────────┐
         │  BacktestEngine      │                  │  LiveEngine          │
         │  Historical candles │                  │  Realtime feed /      │
         │  SimulatedBroker     │                  │  candle_service      │
         │  .run(symbols, ...)  │                  │  .start(exchange,…)   │
         └──────────────────────┘                  └──────────────────────┘
```

- **BaseEngine**: shared foundation; builds `DataRouter`, `OptionChainService`, and `StrategyContext`; calls `strategy.on_candle(candle, ctx)` → intent.
- **BacktestEngine**: replays history per symbol; runs exits/rollover then entry; uses `SimulatedBroker`.
- **LiveEngine**: infinite loop; optional WebSocket feed or candle_service; reconciles positions on start; checks kill switch; validates closed candles; logs to `logs/{engine_id}.log`; exports EOD to `reports/{engine_id}_{date}.csv`.
- **EngineFactory**: from `EngineConfig` builds the full stack (data, instruments, OMS, broker, feed) for one venue. No shared instances.

---

## Concurrency model

- **LiveEngine** uses a **single-threaded event loop** per engine; there is no multi-threading or async event loop within one engine.
- **WebSocket feeds** (e.g. Delta) push events into an **engine-owned queue** (or equivalent); the main loop consumes from that queue. The feed may run on a separate thread, but the strategy and OMS run on the engine thread.
- **No shared mutable state across engines**: each process/engine has its own PositionManager, RiskManager, OrderRouter, and Broker. Running Dhan and Delta in two processes gives full fault isolation; the optional Supervisor runs multiple engines in one process (e.g. one thread per engine) with no shared OMS state.

---

## Candle aggregation model

- The engine **consumes only closed candles**: `LiveEngine._is_closed_candle()` ensures the candle timestamp is aligned to the timeframe boundary and not in the future, so forming (incomplete) candles are skipped. **No repainting**—strategy logic sees only completed bars.
- If a prop-style **CandleAggregator** is added (tick → 1m → higher timeframes), the same rule applies: the engine receives only closed, aggregated candles.

---

## Determinism guarantee

- **Deterministic event ordering** within each engine: candles and orders are processed in a well-defined order (e.g. symbol loop, then strategy → intent → router). No race conditions on OMS state within a single engine.

---

## Engine safety model

Production safeguards (implemented and planned) that make the system institutional-grade:

| Layer | Feature | Status |
|--------|--------|--------|
| **Risk** | Kill switch hierarchy (`RiskManager.trigger_kill_switch`) | Implemented |
| **Broker** | Broker circuit breaker (fail-fast on repeated broker errors) | Planned |
| **Startup** | Reconciliation on start (sync PositionManager to broker) | Implemented |
| **Signals** | Duplicate signal protection (avoid re-entry on same bar/signal) | Planned |
| **Orders** | Order state consistency verification (PM vs broker) | Planned |
| **Resource** | Memory guard (cap queue size / history) | Planned |
| **Strategy** | Strategy timeout guard (max time per `on_candle`) | Planned |
| **Feed** | Symbol-level pause (pause entries per symbol when feed stale) | Implemented (feed health) |
| **Latency** | Latency guard (log strategy_time_ms, broker_latency_ms; optional alert on breach) | Implemented |
| **Feed** | Feed health (warn when no data for `feed_stale_seconds`; pause entries) | Implemented |

Latency logging is done **only on the order path** (when an order is placed), not in the tick ingestion path, so it does not degrade performance at high tick rates (e.g. 1000+ ticks/sec).

---

## Directory structure

```
Algo/
├── README.md                 # This file
├── requirements.txt
├── .env                      # DHAN_*, DELTA_* (create from .env.example if present)
│
├── run/
│   ├── main.py               # Entry: python -m run.main [--venue DHAN|DELTA]
│   ├── config.py            # RUN_MODE, DEFAULT_VENUE, STRATEGY_JOBS
│   └── engine_config.py      # EngineConfig, example_dhan_* / example_delta_*
│
├── core/
│   ├── engine/
│   │   ├── base_engine.py    # Shared: strategy, data, build_context()
│   │   ├── backtest_engine.py
│   │   ├── live_engine.py    # Reconciliation, kill switch, validation, EOD, logging
│   │   ├── factory.py       # EngineFactory.create_engine(config)
│   │   └── supervisor.py    # Optional: run multiple engines in one process
│   │
│   ├── strategies/
│   │   ├── registry.py      # STRATEGY_MAP: name → strategy class, allowed_modes
│   │   ├── base.py          # BaseStrategy
│   │   ├── Futures/Futures_EMA/
│   │   ├── Leaps/
│   │   └── Inside_bar_candle/
│   │
│   ├── data/
│   │   ├── sources/         # DhanSource, DeltaSource
│   │   ├── datalayer/       # DhanDataProvider, DeltaDataProvider
│   │   ├── feeds/           # DeltaWebSocketFeed, RealtimeFeed base
│   │   ├── candle_service.py
│   │   └── data_router.py
│   │
│   ├── broker/
│   │   ├── base.py          # BaseBroker, IBrokerApi
│   │   └── internal/        # dhan/, delta/, simulated/
│   │
│   ├── orderExecution/
│   │   ├── order_router.py
│   │   ├── risk_manager.py  # Limits, kill switch, capital bucket
│   │   ├── position_manager.py
│   │   └── intent_store.py
│   │
│   ├── utils/instruments/   # InstrumentStore, Dhan/Delta instrument loaders
│   ├── models/              # StrategyContext, OrderIntent
│   └── library/             # delta_rest_client, delta_websocket, dhan_tradehull
│
├── logs/
│   ├── engine_logger.py     # Structured JSON per engine: logs/{engine_id}.log
│   └── logger/              # TradeLogger (CSV trade log)
│
├── reports/                 # EOD CSV: {engine_id}_{YYYYMMDD}.csv
├── Dependencies/            # Instrument CSVs (Dhan/Delta), dated
├── data_cache/              # Cached option/expiry data (optional)
└── docs/
    ├── MULTI_VENUE.md       # Multi-venue design, factory, two-process run
    └── PRODUCTION_UPGRADES.md  # Reconciliation, kill switch, logging, EOD, etc.
```

---

## Key concepts

| Concept | Meaning |
|--------|--------|
| **Venue** | Broker/market: `DHAN` (India) or `DELTA` (crypto). Each job in config has a `venue`. |
| **Engine** | One BacktestEngine or LiveEngine instance. Built by EngineFactory from an EngineConfig. |
| **OMS** | Order management: PositionManager, RiskManager, IntentStore, OrderRouter, Broker. One OMS per engine. |
| **Strategy** | Class registered in `STRATEGY_MAP`; implements `on_candle`, `should_evaluate`, `should_exit`, etc. |
| **EngineConfig** | Dataclass: broker_name, run_mode, strategy_name, symbols, capital, risk_per_trade_percent, backtest/live params, engine_id. |
| **Run mode** | `BACKTEST` \| `PAPER` \| `LIVE`. Set in `run/config.py` as `RUN_MODE`. |

---

## Configuration

### 1. Run mode and default venue (`run/config.py`)

- **RUN_MODE**: `RunMode.BACKTEST` \| `RunMode.PAPER` \| `RunMode.LIVE` — applies to all jobs when using `main.py`.
- **DEFAULT_VENUE**: used when a job does not set `"venue"` (e.g. `"DELTA"` or `"DHAN"`).
- **STRATEGY_JOBS**: list of job dicts. Each job has:
  - **name**: strategy key in `STRATEGY_MAP` (e.g. `"FuturesEMAHighLow"`, `"LEAPS_RSI"`).
  - **venue**: `"DHAN"` or `"DELTA"`.
  - **enabled**: if `False`, job is skipped.
  - **symbols**: list of symbols (e.g. `["BTCUSD"]`, `["NIFTY"]`).
  - **capital**, **risk_per_trade_percent** (optional; for live risk limits).
  - **backtest**: `start_date`, `end_date`, `timeframe`, `exchange`, `sector`.
  - **live**: `exchange`, `sector`, `rsi` (and any strategy-specific params).

### 2. Engine config (`run/engine_config.py`)

- **EngineConfig**: full config for one engine (used by EngineFactory).
- Helpers: `example_dhan_live_config()`, `example_delta_live_config()`, etc., with `engine_id`, `capital`, `risk_per_trade_percent` where relevant.
- **engine_id** defaults to `{broker_name}_{strategy_name}` if not set; used for log file and EOD report filename.

### 3. Environment variables

- **Dhan**: `DHAN_CLIENT_CODE`, `DHAN_ACCESS_TOKEN` (and any required by Dhan Tradehull).
- **Delta**: `DELTA_API_KEY`, `DELTA_API_SECRET`, optional `DELTA_BASE_URL`.
- Loaded via `dotenv` in live path and in sources; keep `.env` out of version control.

---

## How to run

### Prerequisites

- Python 3.x; install deps: `pip install -r requirements.txt`.
- `.env` with credentials for the venue(s) you run.
- **Dependencies/** with instrument file for the venue/date (e.g. `all_instrument{YYYY-MM-DD}.csv` for Dhan, `delta_instrument_{YYYY-MM-DD}.csv` for Delta). Some flows create or fetch these automatically.

### Backtest (single venue)

1. Set `RUN_MODE = RunMode.BACKTEST` in `run/config.py`.
2. Ensure the job you want has `backtest` with `start_date`, `end_date`, `timeframe`, `exchange`, `sector`.
3. Run all jobs, or only one venue:
   ```bash
   python -m run.main
   # or only Delta jobs
   python -m run.main --venue DELTA
   ```
4. Each job gets its own BacktestEngine and SimulatedBroker; results and trade log go to `logs/` (e.g. strategy trade CSV).

### Live / paper (single venue)

1. Set `RUN_MODE = RunMode.LIVE` (or `PAPER`) in `run/config.py`.
2. Set the job’s `venue` to the broker you use; add `live` (e.g. `exchange`, `sector`, `rsi`).
3. Run that venue only (recommended: one process per venue):
   ```bash
   python -m run.main --venue DELTA
   # or
   python -m run.main --venue DHAN
   ```
4. Live engine will:
   - Reconcile broker positions with PositionManager on startup.
   - Use Delta WebSocket feed for Delta if credentials are set; otherwise candle_service / REST.
   - Check risk kill switch and limits each loop; block entries when blocked.
   - Validate closed candles only; log to `logs/{engine_id}.log` and write EOD to `reports/{engine_id}_{date}.csv`.

### Two processes (Dhan + Delta in parallel)

- **Process 1 (India):**  
  `python -m run.main --venue DHAN`
- **Process 2 (Crypto):**  
  `python -m run.main --venue DELTA`

Each process runs only jobs for that venue; each engine has its own OMS and log file.

### Optional: one process, multiple engines (Supervisor)

See `docs/MULTI_VENUE.md`: create a Supervisor, `register_from_config()` for each EngineConfig, then `start_all()` so each live engine runs in its own thread.

---

## Production features

| Feature | Where | What it does |
|--------|--------|----------------|
| **Broker reconciliation** | LiveEngine | On start, fetches broker positions, syncs PositionManager, logs mismatches to engine log. |
| **Kill switch** | RiskManager | `trigger_kill_switch(reason)` blocks all new entries; exits still allowed; logged. |
| **Risk limits** | RiskManager | daily_max_loss, max_open_positions, max_symbol_exposure, max_portfolio_exposure; capital × risk_per_trade_percent → max_risk_amount per trade. |
| **Closed-candle validation** | LiveEngine | Only evaluates candles that are closed and aligned to timeframe; skips forming candles. |
| **Structured logging** | EngineLogger | One JSON line per event in `logs/{engine_id}.log` (order_placed, risk_block, reconciliation, kill_switch, latency, etc.). |
| **Feed health** | LiveEngine | Tracks last tick/candle per symbol; warns and can pause entries if no data for `feed_stale_seconds`. |
| **EOD export** | LiveEngine | Writes `reports/{engine_id}_{YYYYMMDD}.csv` (open positions, realized pnl). |
| **Latency** | LiveEngine | Logs strategy_time_ms, broker_latency_ms, total_latency_ms for orders (order path only; not in tick ingestion, so no impact at high tick rate). |

Details: `docs/PRODUCTION_UPGRADES.md`.

---

## Steps to take (checklist)

Use this as a reference for setup and next steps.

### Initial setup

1. **Clone and install**
   - `pip install -r requirements.txt`
   - Create `.env` with Dhan and/or Delta credentials (see Environment and dependencies below).

2. **Configure run mode and jobs**
   - Open `run/config.py`; set `RUN_MODE` (BACKTEST / PAPER / LIVE).
   - Set `DEFAULT_VENUE` if you rely on default venue for jobs.
   - In `STRATEGY_JOBS`, set `enabled: True` for the strategy you want; set `venue`, `symbols`, `backtest`, `live`, and optionally `capital`, `risk_per_trade_percent`.

3. **Instrument files**
   - For Dhan: ensure `Dependencies/all_instrument{date}.csv` exists (or let the flow that creates it run).
   - For Delta: same for `delta_instrument_{date}.csv` (or use Delta’s instrument fetch if implemented).

### Backtest

4. Set `RUN_MODE = RunMode.BACKTEST` in `run/config.py`.
5. Run: `python -m run.main` or `python -m run.main --venue DELTA` (or DHAN).
6. Check `logs/` for strategy trade CSVs and any engine logs.

### Live / paper

7. Set `RUN_MODE = RunMode.LIVE` (or PAPER) in `run/config.py`.
8. Ensure the job has `live` with `exchange`, `sector`, and optionally `rsi`.
9. Run one venue per process: `python -m run.main --venue DELTA` or `--venue DHAN`.
10. Monitor `logs/{engine_id}.log` (JSON lines) and `reports/{engine_id}_{date}.csv` for EOD.

### Add or change a strategy

11. Implement a strategy (subclass BaseStrategy, implement `on_candle`, etc.) and register it in `core/strategies/registry.py` under `STRATEGY_MAP` with `allowed_modes`.
12. Add a new job in `STRATEGY_JOBS` in `run/config.py` with `name`, `venue`, `symbols`, `backtest`, `live`, and optionally `capital`, `risk_per_trade_percent`.
13. Run as above; the new job will get its own engine when its venue is selected.

### Production hardening

14. Set **capital** and **risk_per_trade_percent** (and optionally **daily_max_loss**) per job so RiskManager enforces per-trade and daily limits.
15. Optionally call **RiskManager.trigger_kill_switch(reason)** from a monitoring script or manually when you need to stop entries.
16. Use **reports/** and **logs/** for audits and debugging; no print() in engine path when EngineLogger is set.
17. Run Dhan and Delta in **separate processes** (two terminals or two services) for fault isolation.

### Optional next steps

18. Add **DhanWebSocketFeed** (in `core/data/feeds/`) when Dhan exposes a WebSocket API; wire it in EngineFactory for `broker_name == "DHAN"`.
19. Use **Supervisor** (see `docs/MULTI_VENUE.md`) if you want both venues in one process (e.g. for dev).
20. Hook **RiskManager.record_realized_pnl(amount)** when a position is closed (e.g. from PositionManager or broker callback) so daily_max_loss is accurate.

---

## Environment and dependencies

### Python

- 3.8+ recommended. Key deps: `requests`, `pandas`, `numpy`, `websocket-client`, `python-dateutil`, `pytz`, `dhanhq`, `Dhan-Tradehull`. See `requirements.txt`.

### Environment variables

- **Dhan**: `DHAN_CLIENT_CODE`, `DHAN_ACCESS_TOKEN`.
- **Delta**: `DELTA_API_KEY`, `DELTA_API_SECRET`; optional `DELTA_BASE_URL` (defaults depend on testnet/india in config).
- Loaded in live path and in data sources; use a `.env` file at project root (do not commit it).

### Project layout (summary)

- **run/**: entry point and config (RUN_MODE, STRATEGY_JOBS, EngineConfig).
- **core/engine/**: BaseEngine, BacktestEngine, LiveEngine, EngineFactory, Supervisor.
- **core/strategies/**: registry and strategy implementations.
- **core/data/**: sources, datalayer, feeds, candle_service.
- **core/broker/**: base + internal (dhan, delta, simulated).
- **core/orderExecution/**: order_router, risk_manager, position_manager, intent_store.
- **logs/**: engine_logger (JSON), logger (trade CSV).
- **reports/**: EOD CSV per engine per day.
- **Dependencies/**: instrument CSVs.

---

## Further reading

- **docs/MULTI_VENUE.md** – Multi-venue design, EngineFactory usage, two-process run, Supervisor.
- **docs/PRODUCTION_UPGRADES.md** – Reconciliation, kill switch, logging, EOD, capital bucket, latency.
- **core/engine/factory.py** – How each stack is built from EngineConfig.
- **run/engine_config.py** – EngineConfig fields and example configs.

---

**Quick reference commands**

```bash
# Backtest all jobs (RUN_MODE = BACKTEST in config)
python -m run.main

# Backtest only Delta jobs
python -m run.main --venue DELTA

# Live only Dhan jobs (RUN_MODE = LIVE)
python -m run.main --venue DHAN

# Live only Delta jobs
python -m run.main --venue DELTA
```

Logs: `logs/{engine_id}.log` (JSON). EOD: `reports/{engine_id}_{YYYYMMDD}.csv`.

<!-- this is when engine should work -->
Time (IST)      | 09:00  | 12:00  | 15:30  | 19:00  | 22:00  | 03:00  | 09:00
----------------|--------|--------|--------|--------|--------|--------|--------
Office Hours    |  🏢     |  🏢     |  🏢     |        |        |        |        
Home Hours      |        |        |        |  🏠     |  🏠     |  🏠     |  🏠     
Dhan Engine     |  🔵    |  🔵    |  🔵    |  ⬜     |  ⬜     |  ⬜     |  ⬜     
Delta Engine    |  ⬜    |  ⬜    |  ⬜    |  🔴    |  🔴    |  🔴    |  🔴   

🏢 – Office hours (light monitoring only)

🏠 – Home hours (can fully monitor/control engines)

🔵 – Dhan engine active (intraday + positional trades)

🔴 – Delta engine active (evening/night crypto strategies)

⬜ – Engine OFF
