# Algo – Multi-Venue Trading System

A production-grade, modular trading system that supports **India markets (Dhan)** and **crypto (Delta Exchange)** with fully isolated engines, config-driven setup, and file-based logging. One engine = one broker = one OMS; no shared state across venues.

---

## Table of contents

1. [What this project does](#what-this-project-does)
2. [Dhan Market Quote API (implemented)](#dhan-market-quote-api-implemented)
3. [Architecture at a glance](#architecture-at-a-glance)
4. [Concurrency model](#concurrency-model)
5. [Candle aggregation model](#candle-aggregation-model)
6. [Determinism guarantee](#determinism-guarantee)
7. [Engine safety model](#engine-safety-model)
8. [Directory structure](#directory-structure)
9. [Key concepts](#key-concepts)
10. [Configuration](#configuration)
11. [How to run](#how-to-run)
12. [Production features](#production-features)
13. [Steps to take (checklist)](#steps-to-take-checklist)
14. [Environment and dependencies](#environment-and-dependencies)
15. [Further reading](#further-reading)

---

## What this project does

- **Backtest** strategies on historical candles (single venue per run).
- **Live / paper trade** with real-time data: **Delta** uses WebSocket; **Dhan** supports **DhanWebSocketFeed** (Live Market Feed WebSocket) when credentials and instrument file are set, otherwise REST/candle service.
- **Two venues in parallel**: run Dhan (India) and Delta (crypto) in separate processes or in one process via a Supervisor.
- **Per-engine OMS**: each engine has its own PositionManager, RiskManager, OrderRouter, and Broker—no shared orders or positions across venues.
- **Production safeguards**: broker reconciliation on startup, risk kill switch, closed-candle validation, feed health checks, structured JSON logs, EOD CSV export, capital and risk limits per engine.

---

## Dhan Market Quote API (implemented)

The **Dhan v2 Market Quote API** (LTP, OHLC, market depth) is integrated for the Dhan broker:

| Component | Location | What was implemented |
| --------- | -------- | --------------------- |
| **Client** | `core/library/dhan_marketfeed.py` | `DhanMarketFeedClient` with `ltp()`, `ohlc()`, `quote()` calling `POST /marketfeed/ltp`, `/marketfeed/ohlc`, `/marketfeed/quote`. Optional 1 req/s rate limit. |
| **Source** | `core/data/sources/dhan_source.py` | `get_ltp_v2(instruments)`, `get_ohlc_v2(instruments)`, `get_quote_v2(instruments)` using the v2 client. |
| **Data provider** | `core/data/datalayer/dhan_data_provider.py` | Same v2 methods exposed so engines can fetch LTP/OHLC/quote by segment + security IDs. |
| **Parsers** | `core/library/dhan_marketfeed.py` | `parse_ltp_response()`, `parse_ohlc_response()`, `parse_quote_response()` to flatten API responses. |

**Instruments format:** `{ "NSE_EQ": [11536], "NSE_FNO": [49081, 49082], ... }` — exchange segment → list of security IDs. Use when you have segment + IDs (e.g. from positions or instrument store). For symbol names, continue using `get_ltp_data(names)`, `get_latest_candles(symbols)`, `get_quote_data(names)` via Tradehull.

### Dhan Live Market Feed WebSocket (implemented)

Real-time tick-by-tick data over WebSocket is integrated for the Dhan broker:

| Component | Location | What was implemented |
| --------- | -------- | --------------------- |
| **WebSocket client** | `core/library/dhan_websocket.py` | Connect to `wss://api-feed.dhan.co` (version=2, token, clientId, authType=2). Subscribe via JSON (RequestCode 15, InstrumentList; max 100 per message). Parse binary Little Endian packets: Ticker (2), Quote (4), OI (5), Prev close (6), Full (8), Disconnect (50). Ping/pong keep-alive; disconnect RequestCode 12. |
| **Feed** | `core/data/feeds/dhan_feed.py` | `DhanWebSocketFeed(RealtimeFeed)`: takes access_token, client_id, instruments list. `get_last_ticker(symbol)`, `get_last_candle(symbol, resolution)`. Used by LiveEngine when broker is DHAN and `DHAN_ACCESS_TOKEN` / `DHAN_CLIENT_CODE` are set. |
| **Instrument resolution** | `core/utils/instruments/dhan.py` | `DhanInstrumentStore.get_feed_instruments(symbols)` returns list of `{ExchangeSegment, SecurityId, symbol}` for WebSocket subscribe. Maps NSE/BSE/MCX and segment to NSE_EQ, NSE_FNO, IDX_I, etc. |
| **Engine factory** | `core/engine/factory.py` | For live DHAN engine, if credentials and instrument store have `get_feed_instruments`, builds instruments from config.symbols and starts `DhanWebSocketFeed`. |

Up to 5 connections per user, 5000 instruments per connection. Server pings every 10s; no response for 40s closes the connection.

### Dhan Full Market Depth WebSocket (implemented)

Level 3 market depth (20 or 200 levels) for demand/supply zones and strategies beyond 5-level depth. NSE Equity and NSE Derivatives only. Request/response: JSON for subscribe, binary for depth packets.

| Component | Location | What was implemented |
| --------- | -------- | --------------------- |
| **WebSocket client** | `core/library/dhan_depth_websocket.py` | **20 level:** `wss://depth-api-feed.dhan.co/twentydepth` — up to 50 instruments per connection. **200 level:** `wss://full-depth-api.dhan.co/twohundreddepth` — 1 instrument per connection. Subscribe via JSON (RequestCode 23, InstrumentList for 20 level; single ExchangeSegment + SecurityId for 200 level). Parse binary: 12-byte header (msg_len, response_code 41=Bid/51=Ask, segment, security_id), then N×16-byte rows (float64 price, uint32 quantity, uint32 num_orders). Ping/pong keep-alive; disconnect RequestCode 12. |
| **Feed** | `core/data/feeds/dhan_depth_feed.py` | `DhanDepthFeed(RealtimeFeed)`: takes access_token, client_id, instruments list, level=20 or 200. `get_market_depth(symbol)` returns `{symbol, bids: [{price, quantity, num_orders}, ...], asks: [...]}`. Implements `get_last_ticker` from best bid/ask mid. Use when strategies need full depth; can run alongside `DhanWebSocketFeed` (separate connection). |
| **Instrument resolution** | `core/utils/instruments/dhan.py` | Same `get_feed_instruments(symbols)` as Live Market Feed; use NSE_EQ / NSE_FNO symbols for depth. |

**Usage:** Build instruments with `instrument_store.get_feed_instruments(symbols)`, then `DhanDepthFeed(access_token=..., client_id=..., instruments=instruments, level=20).start()`. Read depth via `feed.get_market_depth(symbol)`. Server pings every 10s; no response for 40s closes the connection. Max 5 WebSocket connections per user across all Dhan feeds.

### Equity Universe Service (Dhan)

Equity universe is **exchange-driven**: built from the official **NSE EQUITY_L** security master (`EQUITY_L.csv`), not from the Dhan instrument CSV. Listing date comes from NSE; IPO = any stock where `(today - listing_date).days <= days`. Broker (Dhan) is used only for order execution, LTP retrieval, and position reconciliation.

| Component | Location | What it does |
| --------- | -------- | ------------ |
| **NseMasterDownloader** | `core/universe/nse_master_downloader.py` | Downloads EQUITY_L.csv once per day from NSE; saves to `Dependencies/equity_universe/EQUITY_L_{YYYYMMDD}.csv` and `Dependencies/equity_universe/EQUITY_L_latest.csv`. User-Agent and Referer headers. Logs `nse_master_downloaded` / `nse_master_download_failed`. Runs at engine startup if file missing or outdated, or via `schedule_daily_refresh(hour=20)`. |
| **EquityUniverseService** | `core/universe/equity_universe_service.py` | Loads from `Dependencies/equity_universe/EQUITY_L_latest.csv`. Parses SERIES == "EQ"; extracts SYMBOL, DATE OF LISTING (DD-Mon-YY), ISIN NUMBER, MARKET LOT. `get_ipo_equities(days=365)` = symbols where `(today - listing_date).days <= days`. No Dhan CSV for universe. If file missing, attempts download; on failure logs `universe_load_error` and continues with empty universe. |
| **StockFilterEngine** | `core/universe/stock_filter_engine.py` | `filter(symbols, conditions, universe_service)`. Uses DhanDataProvider v2 for LTP/quote (security IDs from broker instrument store). No network inside strategy loop; no file I/O in `on_candle`. |
| **EquityMeta** | `core/universe/models.py` | Dataclass: `symbol`, `listing_date` (from NSE), `isin`, `market_lot`, `security_id` (optional, from broker for API). |

**Integration:** For **DHAN** engines with strategy `instrument == "EQUITY"`, EngineFactory instantiates EquityUniverseService (cache_dir, data_provider, instrument_store, engine_logger) and passes it as `ctx.universe_service`. Universe loads at startup; no file I/O inside `on_candle`.

**Strategy usage:** Universe = data; strategy = intelligence. Cache the IPO list once (e.g. in strategy init); do **not** call `get_ipo_equities()` inside `on_candle` (avoids O(N) rebuild per candle). Strategy owns selection logic (breakout, volume, NR7, VWAP, etc.).

```python
# Option A: cache IPO set at init, then fast lookup in on_candle
def __init__(self):
    self.ipo_symbols = set()  # filled once when ctx.universe_service is available

def on_candle(self, candle, ctx):
    if ctx.universe_service and not self.ipo_symbols:
        self.ipo_symbols = set(ctx.universe_service.get_ipo_equities(days=365))
    if candle["symbol"] not in self.ipo_symbols:
        return None
    # ... your breakout / filter logic

# Option B: lazy per-symbol with get_listing_days (research-flexible)
# No IO per call; listing dates cached in memory at universe load.
def on_candle(self, candle, ctx):
    symbol = candle["symbol"]
    as_of = candle.get("timestamp")  # pass in backtest for deterministic days
    days = ctx.universe_service.get_listing_days(symbol, as_of_date=as_of) if ctx.universe_service else None
    if days is None or not (30 <= days <= 90):  # e.g. 30–90 day window
        return None
    # ... test fresh IPO momentum, post-lockup, 6–12m base breakout, etc.
```

Refresh once per day via `schedule_daily_refresh(hour=20)` (no blocking in strategy loop).

**Daily universe refresh for IPOBreakout (symbols derived at startup):** For the IPO strategy, set `symbols: None` in the job. At engine startup the factory builds the universe, gets IPO equities (e.g. last 365 days), runs the filter (e.g. `price_above`, `volume_above`), caps the list (e.g. 50 symbols), and injects it into `config.symbols`. The engine loop and DhanWebSocketFeed then run only on these precomputed symbols—no heavy filtering per candle. Filtering happens before feed subscription so you subscribe only to the filtered set (you cannot subscribe to thousands of symbols). In `run/config.py` use `ipo_days`, `ipo_filter`, and `ipo_max_symbols` under `live` / `backtest` to control this. Run with `RUN_MODE = RunMode.LIVE` and `python -m run.main --venue DHAN`.

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
         │  DhanWebSocketFeed   │                  │  DeltaWebSocketFeed  │
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
- **LiveEngine**: infinite loop; optional WebSocket feed or candle*service; reconciles positions on start; checks kill switch; validates closed candles; logs to `logs/{engine_id}.log`; exports EOD to `reports/{engine_id}*{date}.csv`.
- **EngineFactory**: from `EngineConfig` builds the full stack (data, instruments, OMS, broker, feed) for one venue. No shared instances.

---

## Concurrency model

- **LiveEngine** uses a **single-threaded event loop** per engine; there is no multi-threading or async event loop within one engine.
- **WebSocket feeds** (Dhan, Delta) push ticks into an **engine-owned queue** when CandleAggregator is used; the main loop drains the queue and updates the aggregator (single state owner). The feed may run on a separate thread, but the strategy and OMS run on the engine thread.
- **No shared mutable state across engines**: each process/engine has its own PositionManager, RiskManager, OrderRouter, and Broker. Running Dhan and Delta in two processes gives full fault isolation; the optional Supervisor runs multiple engines in one process (e.g. one thread per engine) with no shared OMS state.

---

## Candle aggregation model

- The engine **consumes only closed candles**: `LiveEngine._is_closed_candle()` ensures the candle timestamp is aligned to the timeframe boundary and not in the future, so forming (incomplete) candles are skipped. **No repainting**—strategy logic sees only completed bars.

### CandleAggregator (implemented)

A **prop-grade candle engine** is implemented for both **Dhan** and **Delta** (broker-agnostic). The feed and aggregated candles feed multiple brokers by giving each engine its own aggregator instance and tick queue—no shared state across venues.

| Component | Location | What it does |
| --------- | -------- | ------------ |
| **CandleAggregator** | `core/data/candle_aggregator.py` | Ticks → 1m only; higher timeframes (5m, 15m, 30m, 1h, 2h, 4h, 1d) aggregate **only from closed 1m** candles. Integer bucket math; O(1) per tick. Closed candles immutable; `get_last_closed_candle(symbol, resolution)` returns last closed bar only—never forming, no repainting. |
| **Tick queue** | LiveEngine / EngineFactory | Engine-owned `queue.Queue`. WebSocket feeds push normalized ticks `{symbol, price, volume, timestamp}` (timestamp in Unix sec). Only the processor loop mutates candle state; no locks. |
| **Feed integration** | `core/data/feeds/delta_feed.py`, `dhan_feed.py` | `set_tick_queue(queue)`: when set (before `start()`), feed pushes ticks on each ticker/quote. Same tick format for both brokers. |
| **LiveEngine** | `core/engine/live_engine.py` | When `tick_queue` and `candle_aggregator` are set and strategy has `timeframe`: drain queue → `aggregator.on_tick()` → evaluate only on new closed candles (tracked per symbol). All existing safety layers (kill switch, duplicate signal, candle integrity, etc.) unchanged. |

**Flow (lock-free):** WebSocket (thread) → put tick on queue → Processor loop (engine thread) → `get_nowait` → `CandleAggregator.on_tick()` → on 1m boundary close 1m and propagate to higher TFs from closed 1m only → strategy sees only closed candles.

**Supported resolutions:** 1m, 5m, 15m, 30m, 1h, 2h, 4h, 1d (and aliases e.g. `"1"`, `"60"`). Per-symbol state: `current` (forming) + `closed` deque (maxlen=300). No pandas in live path; no heavy datetime in tick loop.

---

## Determinism guarantee

- **Deterministic event ordering** within each engine: candles and orders are processed in a well-defined order (e.g. symbol loop, then strategy → intent → router). No race conditions on OMS state within a single engine.

---

## Engine safety model

Production safeguards (implemented and planned) that make the system institutional-grade:

| Layer        | Feature                                                                          | Status      |
| ------------ | -------------------------------------------------------------------------------- | ----------- |
| **Risk**     | Kill switch hierarchy (`RiskManager.trigger_kill_switch`)                        | Implemented |
| **Broker**   | Broker circuit breaker (fail-fast on repeated broker errors)                     | Implemented |
| **Startup**  | Reconciliation on start (sync PositionManager to broker)                         | Implemented |
| **Signals**  | Duplicate signal protection (avoid re-entry on same bar/signal)                  | Implemented |
| **Orders**   | Order state consistency verification (PM vs broker)                              | Implemented |
| **Resource** | Memory guard (psutil; pause entries above threshold)                             | Implemented |
| **Strategy** | Strategy timeout guard (max time per `on_candle`)                                | Implemented |
| **Feed**     | Symbol-level pause (pause entries per symbol when feed stale or repeated errors) | Implemented |
| **Latency**  | Latency guard + critical pause after N cycles                                    | Implemented |
| **Feed**     | Feed health (warn when no data for `feed_stale_seconds`; pause entries)          | Implemented |
| **Shutdown** | Graceful shutdown (SIGINT/SIGTERM, snapshot, flush log)                          | Implemented |
| **Candle**   | Candle integrity validation (OHLC consistency)                                   | Implemented |
| **Slippage** | High-slippage warning on fill (no auto-adjust)                                   | Implemented |

Latency logging is done **only on the order path** (when an order is placed), not in the tick ingestion path, so it does not degrade performance at high tick rates (e.g. 1000+ ticks/sec).

---

## Trade-led OMS (Delta and Dhan)

For **Delta** and **Dhan**, the engine uses a **trade-led** OMS so that positions are driven by **trades** (fills), not by order state. This avoids fabricated fills and zero-price updates when orders disappear from the open list.

| Concept | Meaning |
| ------- | ------- |
| **Order** | Metadata only: order_id, intent_id, symbol, qty, side, state. Placing an order does **not** update position. |
| **Trade** | Source of truth. A trade is a fill from the exchange. Position changes **only** when a trade is applied. |
| **Flow** | Strategy → OrderRouter → Broker → place order. Separately: `sync_trades_from_broker()` pulls recent fills → for each new fill, `process_trade(trade)` → PositionManager updated, then order marked FILLED. |

**Behaviour:**

- **sync_trades_from_broker()**: Called at the start of order-state verification. Fetches recent fills from the broker (`get_recent_fills()`), then applies each new fill once via `process_trade()` (idempotent by trade id). Positions are updated only from these trades.
- **process_trade(trade)**: Updates PositionManager from the trade (price, size, side, intent_id); records realized PnL if position closed; marks the corresponding order/intent as FILLED. No position update is ever made from “order disappeared” or “assume filled.”
- **Missing order**: If an order is not on the broker open list (and not in history for Delta), the router tries to resolve a fill for that intent. If a fill is found, it is applied via `process_trade()` and the order is marked FILLED. If **no** fill is found, the order state is left unchanged and **no** position update is made (no fabricated fill, no zero price).

**Components:**

| Component | Location | Role |
| --------- | -------- | ---- |
| **OrderRouter** | `core/orderExecution/order_router.py` | `process_trade()`, `sync_trades_from_broker()`, `_processed_trade_ids` for idempotency. |
| **Delta broker** | `core/broker/internal/delta/broker.py` | `get_recent_fills()` (from `/v2/fills`), `get_fill_for_client_order_id()` for missing-order resolution. |
| **Dhan broker** | `core/broker/internal/dhan/broker.py` | `get_recent_fills()` (from order list: TRADED/filled orders), `get_fill_for_client_order_id()` for missing-order resolution. |
| **Dhan source** | `core/data/sources/dhan_source.py` | `get_fills()` derives fills from order list (status TRADED/filled/complete) for trade-led sync. |

Reconciliation remains position-based: broker positions are compared with local positions that were built from applied trades.

---

## Directory structure

```
Algo/
├── README.md                 # This file
├── requirements.txt
├── .env                      # DHAN_*, DELTA_*, DEMO_DELTA_* (copy from .env.example)
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
│   │   ├── Equity/IPOBreakout/   # IPO breakout (Dhan equity)
│   │   ├── Futures/Futures_EMA/
│   │   ├── Leaps/
│   │   └── PipelineTest/
│   │
│   ├── data/
│   │   ├── sources/         # DhanSource, DeltaSource
│   │   ├── datalayer/       # DhanDataProvider, DeltaDataProvider
│   │   ├── feeds/           # DeltaWebSocketFeed, DhanWebSocketFeed, DhanDepthFeed, RealtimeFeed base
│   │   ├── candle_service.py
│   │   ├── candle_aggregator.py   # Tick→1m; higher TFs from closed 1m; broker-agnostic
│   │   └── data_router.py
│   │
│   ├── universe/                  # Equity universe from NSE EQUITY_L (DHAN only)
│   │   ├── nse_master_downloader.py
│   │   ├── equity_universe_service.py
│   │   ├── stock_filter_engine.py
│   │   └── models.py
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
│   └── library/             # delta_rest_client, delta_websocket, dhan_websocket, dhan_depth_websocket, dhan_tradehull
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

| Concept          | Meaning                                                                                                                     |
| ---------------- | --------------------------------------------------------------------------------------------------------------------------- |
| **Venue**        | Broker/market: `DHAN` (India) or `DELTA` (crypto). Each job in config has a `venue`.                                        |
| **Engine**       | One BacktestEngine or LiveEngine instance. Built by EngineFactory from an EngineConfig.                                     |
| **OMS**          | Order management: PositionManager, RiskManager, IntentStore, OrderRouter, Broker. One OMS per engine.                       |
| **Strategy**     | Class registered in `STRATEGY_MAP`; implements `on_candle`, `should_evaluate`, `should_exit`, etc.                          |
| **EngineConfig** | Dataclass: broker_name, run_mode, strategy_name, symbols, capital, risk_per_trade_percent, backtest/live params, engine_id. |
| **Run mode**     | `BACKTEST` \| `PAPER` \| `LIVE`. Set in `run/config.py` as `RUN_MODE`.                                                      |

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
- **Production safeguards** (live only): `order_state_check_interval_min`, `circuit_breaker_threshold`, `allowed_trading_hours`, `slippage_threshold_pct`, `memory_threshold_percent`, `strategy_timeout_seconds`, `latency_critical_ms`, `latency_critical_cycles`, `symbol_error_threshold`, `feed_stale_seconds`, `max_open_positions`. All optional.

### 2.1 Pipeline test configs

Two jobs in `STRATEGY_JOBS` exercise the full pipeline (Signal → Risk → OMS → Router → Broker → PositionManager → reconciliation) for both venues:

- **Delta**: `name: "SignalFloodTest"`, `venue: "DELTA"`, `engine_id: "delta_test_pipeline"`, `symbols: ["BTCUSD"]`, timeframe `1m`, tight risk limits and aggressive safeguards so blocks (duplicate, max positions, feed stale, latency, etc.) can be observed. Disabled by default; set `enabled: True` for that job to run.
- **Dhan**: same strategy with `venue: "DHAN"`, `engine_id: "dhan_test_pipeline"`, `symbols: ["NIFTY"]`.

Use **PAPER** or **LIVE** run mode. The strategy (`SignalFloodTest`) generates entry/exit every 1m candle and optionally triggers oversize (risk rejection) and duplicate-signal blocks for verification.

### 3. Environment variables

- **Dhan**: `DHAN_CLIENT_CODE`, `DHAN_ACCESS_TOKEN` (and any required by Dhan Tradehull).
- **Delta**: `DELTA_API_KEY`, `DELTA_API_SECRET`, optional `DELTA_BASE_URL`. When using **testnet/demo** (`delta_testnet: True` in the job), the app uses **demo account** credentials if set: `DEMO_DELTA_API_KEY`, `DEMO_DELTA_API_SECRET`; otherwise it falls back to `DELTA_API_KEY` / `DELTA_API_SECRET`. **Delta India testnet** uses `https://cdn-ind.testnet.deltaex.org` (REST) and `wss://cdn-ind.testnet.deltaex.org` (WebSocket); use API keys from the same environment (India testnet).
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
4. **PAPER** (`RUN_MODE = RunMode.PAPER`): Uses **SimulatedBroker**—same LiveEngine stack and logs as LIVE (engine logger, order_placed, fills, reconciliation, EOD), but no real orders. Feed and candle aggregator still use live data when credentials are set.
5. **LIVE**: Live engine will:
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

| Feature                      | Where        | What it does                                                                                                                                    |
| ---------------------------- | ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| **Broker reconciliation**    | LiveEngine   | On start, fetches broker positions, syncs PositionManager, logs mismatches to engine log.                                                       |
| **Kill switch**              | RiskManager  | `trigger_kill_switch(reason)` blocks all new entries; exits still allowed; logged.                                                              |
| **Risk limits**              | RiskManager  | daily_max_loss, max_open_positions, max_symbol_exposure, max_portfolio_exposure; capital × risk_per_trade_percent → max_risk_amount per trade.  |
| **Closed-candle validation** | LiveEngine   | Only evaluates candles that are closed and aligned to timeframe; skips forming candles.                                                         |
| **Structured logging**       | EngineLogger | One JSON line per event in `logs/{engine_id}.log` (order_placed, risk_block, reconciliation, kill_switch, latency, etc.).                       |
| **Feed health**              | LiveEngine   | Tracks last tick/candle per symbol; warns and can pause entries if no data for `feed_stale_seconds`.                                            |
| **EOD export**               | LiveEngine   | Writes `reports/{engine_id}_{YYYYMMDD}.csv` (open positions, realized pnl).                                                                     |
| **Latency**                  | LiveEngine   | Logs strategy_time_ms, broker_latency_ms, total_latency_ms for orders (order path only; not in tick ingestion, so no impact at high tick rate). |

### Production safeguards (implemented)

The following are implemented and configurable via **EngineConfig** (live only; no change to BaseEngine or BacktestEngine):

| #   | Feature                            | Where       | Config / behavior                                                                                                                                                                                                                                                                   |
| --- | ---------------------------------- | ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **Order state consistency**        | OrderRouter | `verify_open_orders_with_broker()` compares broker open orders with IntentStore and PositionManager; on mismatch logs `order_state_mismatch`, calls `reconcile_positions_on_start()`, optionally pauses entries. Trigger: startup + every `order_state_check_interval_min` minutes. |
| 2   | **Duplicate signal protection**    | LiveEngine  | `_last_signal_hash_per_symbol`; before entry, hash(symbol, timeframe, candle_timestamp, signal_type); if already processed skip and log `duplicate_signal_blocked`.                                                                                                                 |
| 3   | **Broker circuit breaker**         | OrderRouter | On broker failure increment `consecutive_failures`; if ≥ `circuit_breaker_threshold` (default 5) call `risk_manager.trigger_kill_switch("broker_failure")` and log `broker_circuit_breaker_triggered`. Reset on successful order.                                                   |
| 4   | **Max open positions**             | RiskManager | Already present; blocks entry when `open_count >= max_open_positions`; logs `max_positions_blocked`.                                                                                                                                                                                |
| 5   | **Time-of-day guard**              | LiveEngine  | `allowed_trading_hours = [(start, end)]` in "HH:MM" UTC; outside window skip entry and log `time_window_blocked`. Exits always allowed.                                                                                                                                             |
| 6   | **Slippage monitor**               | OrderRouter | `report_fill(expected_price, fill_price, ...)`; when fill is reported, if slippage > `slippage_threshold_pct` log `high_slippage_warning`. No auto-adjust.                                                                                                                          |
| 7   | **Memory guard**                   | LiveEngine  | Uses `psutil`; when process memory % ≥ `memory_threshold_percent` log `memory_pressure_warning` and pause new entries. No auto shutdown.                                                                                                                                            |
| 8   | **Graceful shutdown**              | LiveEngine  | Handles SIGINT/SIGTERM; on shutdown saves position snapshot to `reports/{engine_id}_shutdown_{timestamp}.csv`, logs `graceful_shutdown`, closes broker if it has `close()`. Per-engine.                                                                                             |
| 9   | **Candle integrity validation**    | LiveEngine  | When using a candle, validates high ≥ max(open, close), low ≤ min(open, close); on mismatch log `candle_integrity_error` and skip candle. No crash.                                                                                                                                 |
| 10  | **Symbol-level failure isolation** | LiveEngine  | `symbol_state[symbol] = {paused, feed_stale, error_count}`; if symbol repeatedly fails (≥ `symbol_error_threshold`) pause only that symbol and log `symbol_paused`. Other symbols keep trading.                                                                                     |
| 11  | **Strategy timeout guard**         | LiveEngine  | If strategy evaluation time > `strategy_timeout_seconds` log `strategy_timeout` and skip order placement. No crash.                                                                                                                                                                 |
| 12  | **Latency alert levels**           | LiveEngine  | normal &lt; 50ms, warning 50–150ms, critical &gt; 150ms (configurable `latency_critical_ms`). If critical for `latency_critical_cycles` consecutive cycles, pause new entries and log `latency_critical_pause`.                                                                     |

**EngineConfig** (run/engine_config.py) fields for the above: `order_state_check_interval_min`, `circuit_breaker_threshold`, `allowed_trading_hours`, `slippage_threshold_pct`, `memory_threshold_percent`, `strategy_timeout_seconds`, `latency_critical_ms`, `latency_critical_cycles`, `symbol_error_threshold`. All optional; defaults preserve existing behavior.

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

11. Implement a strategy (subclass BaseStrategy, implement `on_candle`, etc.) and register it in `core/strategies/registry.py` under `STRATEGY_MAP` with `allowed_modes`. Example: **IPOBreakout** (Dhan equity) in `core/strategies/Equity/IPOBreakout/`.
12. Add a new job in `STRATEGY_JOBS` in `run/config.py` with `name`, `venue`, `symbols`, `backtest`, `live`, and optionally `capital`, `risk_per_trade_percent`.
13. Run as above; the new job will get its own engine when its venue is selected.

### Production hardening

14. Set **capital** and **risk_per_trade_percent** (and optionally **daily_max_loss**) per job so RiskManager enforces per-trade and daily limits.
15. Optionally call **RiskManager.trigger_kill_switch(reason)** from a monitoring script or manually when you need to stop entries.
16. Use **reports/** and **logs/** for audits and debugging; no print() in engine path when EngineLogger is set.
17. Run Dhan and Delta in **separate processes** (two terminals or two services) for fault isolation.

### Optional next steps

18. **DhanWebSocketFeed** is implemented; use **DhanDepthFeed** when strategies need full market depth (20/200 level).
19. Use **Supervisor** (see `docs/MULTI_VENUE.md`) if you want both venues in one process (e.g. for dev).
20. Hook **RiskManager.record_realized_pnl(amount)** when a position is closed (e.g. from PositionManager or broker callback) so daily_max_loss is accurate.

---

## Environment and dependencies

### Python

- 3.8+ recommended. Key deps: `requests`, `pandas`, `numpy`, `websocket-client`, `python-dateutil`, `pytz`, `dhanhq`, `Dhan-Tradehull`. See `requirements.txt`.

### Environment variables

- **Dhan**: `DHAN_CLIENT_CODE`, `DHAN_ACCESS_TOKEN`.
- **Delta**: `DELTA_API_KEY`, `DELTA_API_SECRET`; optional `DELTA_BASE_URL` (defaults depend on testnet/india in config). For **demo/testnet** runs (`delta_testnet: True`), set `DEMO_DELTA_API_KEY` and `DEMO_DELTA_API_SECRET` in `.env`. India testnet uses `https://cdn-ind.testnet.deltaex.org` (REST and WebSocket); use keys from that environment.
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
- **docs/OPTIMIZATION_AUDIT.md** – Optimization audit: queue sizing, pause resets, pandas in live path, backtest perf, etc.
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

| Time (IST)   | 09:00 | 12:00 | 15:30 | 19:00 | 22:00 | 03:00 | 09:00 |
| ------------ | ----- | ----- | ----- | ----- | ----- | ----- | ----- |
| Office Hours | 🏢    | 🏢    | 🏢    |       |       |       |
| Home Hours   |       |       |       | 🏠    | 🏠    | 🏠    | 🏠    |
| Dhan Engine  | 🔵    | 🔵    | 🔵    | ⬜    | ⬜    | ⬜    | ⬜    |
| Delta Engine | ⬜    | ⬜    | ⬜    | 🔴    | 🔴    | 🔴    | 🔴    |

🏢 – Office hours (light monitoring only)

🏠 – Home hours (can fully monitor/control engines)

🔵 – Dhan engine active (intraday + positional trades)

🔴 – Delta engine active (evening/night crypto strategies)

⬜ – Engine OFF

<!-- Multi-Venue Engine Lifecycle & Safeguards -->

                      ┌─────────────────────────┐
                      │   Engine Startup        │
                      │------------------------│
                      │ - Load EngineConfig     │
                      │ - Reconcile broker      │
                      │   positions → PM        │
                      │ - Init logs/reports     │
                      └──────────┬────────────┘
                                 │
                                 ▼
                     ┌──────────────────────────┐
                     │   Event Loop (LiveEngine) │
                     │--------------------------│
                     │  1. Receive Candle/Feed  │
                     │  2. Validate candle      │
                     │     (_validate_candle)   │
                     │  3. Check feed health    │
                     │  4. Strategy evaluation  │
                     │     (on_candle)          │
                     │  5. Strategy timeout     │
                     │     guard                 │
                     │  6. Generate Intent      │
                     │  7. Duplicate signal     │
                     │     protection           │
                     │  8. Risk & time-of-day   │
                     │     checks               │
                     │  9. Memory & latency     │
                     │     monitors             │
                     │ 10. Broker circuit       │
                     │     breaker              │
                     │ 11. Place orders via OMS │
                     │ 12. Slippage monitor     │
                     │ 13. Update PositionMgr   │
                     │ 14. Log event (JSON)     │
                     └──────────┬─────────────┘
                                 │
               ┌─────────────────┴─────────────────┐
               ▼                                   ▼
      ┌──────────────────┐                  ┌──────────────────┐
      │ Exits & Cleanup   │                  │ Graceful Shutdown │
      │------------------│                  │------------------│
      │ - Close positions │                  │ - SIGINT/SIGTERM │
      │   if needed       │                  │ - Dump snapshot  │
      │ - Record realized │                  │ - Close broker   │
      │   PnL to reports  │                  │ - Flush logs     │
      └──────────────────┘                  └──────────────────┘
