# Algo - Multi-Venue Trading System

Production-focused algorithmic trading system for:
- `DHAN` (India markets)
- `DELTA` (crypto markets)

Each engine is isolated (broker, OMS, risk, positions, logging) so venues can run independently and safely.

## Quick Start

```bash
# run enabled jobs for one venue
python -m run.main --venue DHAN
python -m run.main --venue DELTA

# run all enabled jobs
python -m run.main
```

## Core Runtime Modes

- `BACKTEST`: historical replay with `SimulatedBroker`
- `PAPER`: live data + full live OMS/safety checks, no real orders
- `LIVE`: real broker execution

Set defaults and jobs in `run/config.py`.

## High-Level Architecture

`run/main.py` -> `EngineFactory` -> per-job engine instance

- `BacktestEngine`: historical candles, deterministic replay
- `LiveEngine`: feed-driven loop, closed-candle evaluation, OMS fanout
- `OrderRouter`: risk checks, broker placement, trade-led state sync
- `IntentStore`: intent lifecycle and idempotency metadata

## Live Execution Flow

Current live path is feed-first and queue-isolated:

1. WebSocket feed (`DhanWebSocketFeed` / `DeltaWebSocketFeed`)
2. Tick queue (engine-owned)
3. `CandleAggregator` (closed bars only)
4. Main engine loop
5. Per-strategy worker threads (deterministic per strategy)
6. Bounded global intent queue
7. Account router
8. Bounded queues per `(account_id, symbol)` with active-key cap and fallback
9. OMS workers with:
   - retry + exponential backoff
   - token-bucket throttling (per account)
   - per-account circuit breaker
   - watchdog supervision
10. Broker API

## Safety and Reliability Features

- Startup broker-position reconciliation
- Duplicate signal blocking
- Time-window guard
- Memory and latency guards
- Symbol-level pause on repeated failures
- Feed health and feed stall alerting
- Trade-led OMS sync from broker fills
- Graceful shutdown with position snapshots
- Structured logs per engine (`logs/{engine_id}.log`)
- Intent pipeline audit journal (`logs/{engine_id}_intent_pipeline.jsonl`)

## Configuration Surface

Primary configuration points:
- `run/config.py` - runtime defaults and `STRATEGY_JOBS`
- `run/engine_config.py` - engine dataclass and safeguards

Important live fields (non-exhaustive):
- `feed_stale_seconds`
- `order_state_check_interval_min`
- `circuit_breaker_threshold`
- `latency_critical_ms`, `latency_critical_cycles`
- `intent_queue_maxsize`, `account_queue_maxsize`
- `queue_overflow_policy`
- `oms_retry_max_attempts`, `oms_retry_base_delay_seconds`
- `oms_rate_limit_per_sec`, `oms_token_bucket_capacity`
- `max_active_account_symbol_keys`
- `account_circuit_breaker_threshold`
- `worker_watchdog_interval_seconds`

## Environment

Set credentials in `.env` (do not commit):

- Dhan:
  - `DHAN_CLIENT_CODE`
  - `DHAN_ACCESS_TOKEN`

- Delta:
  - `DELTA_API_KEY`
  - `DELTA_API_SECRET`
  - optional `DELTA_BASE_URL`
  - for demo/testnet: `DEMO_DELTA_API_KEY`, `DEMO_DELTA_API_SECRET`

## Repository Map

```text
run/
  main.py                # entrypoint and venue filter
  config.py              # jobs, default mode, venue defaults
  engine_config.py       # EngineConfig schema

core/engine/
  base_engine.py
  backtest_engine.py
  live_engine.py
  factory.py
  supervisor.py

core/orderExecution/
  order_router.py
  intent_store.py
  account_router.py
  risk_manager.py
  position_manager.py

core/data/
  feeds/
  candle_aggregator.py
  sources/
  datalayer/
```

## Typical Operation Pattern

- Run one venue per process for operational isolation.
- Keep `PAPER` jobs enabled for validation before `LIVE`.
- Monitor:
  - `logs/{engine_id}.log`
  - `reports/{engine_id}_*.csv`
  - intent journal files in `logs/`

## Notes

- Live candle evaluation is feed/aggregator-based.
- OMS is trade-led: positions are updated from fills, not inferred order state.
- Multi-strategy mode is supported via `strategy_name` + optional `strategy_names` list in `EngineConfig`.

## Further Reading

- `docs/MULTI_VENUE.md`
- `docs/PRODUCTION_UPGRADES.md`
- `core/engine/factory.py`
- `core/engine/live_engine.py`
