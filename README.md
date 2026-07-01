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

#dummy feed command
cd /root/Dhan-codebase
source .venv/bin/activate
python -m run.dummy_live
```

On **Debian/Ubuntu**, the system Python is [PEP 668](https://peps.python.org/pep-0668/) *externally managed*: use a **virtualenv** (as above) and `pip install` **inside** the activated venv — not `pip install` globally. Use **`python3`** if the `python` command is missing (`sudo apt install python-is-python3` is optional).

### Yahoo NIFTY hourly + RSI (optional)

```bash
cd ~/Dhan-codebase
source .venv/bin/activate   # create .venv first with: python3 -m venv .venv
pip install yfinance pandas numpy TA-Lib
python3 utils/yfinance_nifty_rsi.py
```

To **rebuild LEAPS bootstrap logs** (150+ ``dhan_leaps_rsi_candles.log`` rows + RSI history tail aligned to Yahoo) so live startup skips intraday API::

    python3 utils/seed_leaps_bootstrap_logs.py

Keep a backup of ``logs/LEAPS_RSI/`` first; the seed script preserves RSI history lines **before** ``2026-05-12 09:15`` and replaces from that timestamp onward.

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

## Systemd services

Unit files live in `utils/systemd/`. They assume the repo at `/root/Dhan-codebase`, a `.env` in that directory, and Python in `.venv` (except `delta.service`, which uses `venv`).

### One-time install

```bash
cd /root/Dhan-codebase

sudo cp utils/systemd/dhan-leaps-rsi.service /etc/systemd/system/
sudo cp utils/systemd/dhan-oi-positional-buy.service /etc/systemd/system/
sudo cp utils/systemd/dhan-dual.target /etc/systemd/system/
sudo cp utils/systemd/option-buildup-scheduler.service /etc/systemd/system/
# Optional / legacy:
sudo cp utils/systemd/dhan-trading.service /etc/systemd/system/
sudo cp utils/systemd/delta.service /etc/systemd/system/

sudo systemctl daemon-reload
```

If your virtualenv is `venv` instead of `.venv`, edit the `ExecStart=` lines in `/etc/systemd/system/` before running `daemon-reload`.

### Both Dhan engines (recommended)

Starts **LEAPS RSI** (LIVE) and **OI positional buy** (PAPER) together via `dhan-dual.target`.

```bash
sudo systemctl enable dhan-dual.target
sudo systemctl start dhan-dual.target

sudo systemctl status dhan-dual.target
sudo systemctl status dhan-leaps-rsi.service dhan-oi-positional-buy.service

tail -f /root/dhan-leaps-rsi.log /root/dhan-leaps-rsi.err.log
tail -f /root/dhan-oi-positional-buy.log /root/dhan-oi-positional-buy.err.log

sudo systemctl stop dhan-dual.target
```

| Unit | Command |
|------|---------|
| `dhan-leaps-rsi.service` | `python -m run.main --engine-id dhan_leaps_rsi` (LIVE) |
| `dhan-oi-positional-buy.service` | `python -m run.main --engine-id dhan_oi_positional_buy` (PAPER) |

### Individual Dhan services

```bash
sudo systemctl enable --now dhan-leaps-rsi.service
sudo systemctl status dhan-leaps-rsi.service
sudo systemctl stop dhan-leaps-rsi.service

sudo systemctl enable --now dhan-oi-positional-buy.service
sudo systemctl status dhan-oi-positional-buy.service
sudo systemctl stop dhan-oi-positional-buy.service
```

### Option buildup scheduler

Requires `DHAN_CLIENT_CODE` and `DHAN_ACCESS_TOKEN` in `.env`.

```bash
sudo systemctl enable --now option-buildup-scheduler.service
sudo systemctl status option-buildup-scheduler.service
sudo journalctl -u option-buildup-scheduler.service -f
sudo systemctl stop option-buildup-scheduler.service
```

Runs `run/option_buildup_scheduler.py --symbols NIFTY --exchange NSE` (adjust flags in the unit file as needed).

### Delta engine

```bash
sudo systemctl enable --now delta.service
sudo systemctl status delta.service
tail -f /root/delta.log /root/delta.err.log
sudo systemctl stop delta.service
```

Runs `python -m run.main --venue DELTA`.

### Legacy unit

`dhan-trading.service` is a legacy alias for LEAPS RSI only. Prefer `dhan-dual.target` or the two separate services above.

### Run without systemd (same as the units)

```bash
cd /root/Dhan-codebase
source .venv/bin/activate   # or: source venv/bin/activate for delta

python -m run.main --engine-id dhan_leaps_rsi
python -m run.main --engine-id dhan_oi_positional_buy
PYTHONPATH=/root/Dhan-codebase python run/option_buildup_scheduler.py --symbols NIFTY --exchange NSE
python -m run.main --venue DELTA
```

### Maintenance

```bash
sudo systemctl daemon-reload          # after editing unit files
sudo systemctl restart dhan-leaps-rsi.service


sudo systemctl enable --now delta.service
python3 utils/delta/refresh_crypto_indicator_history.py --only 1 --days 60

sudo systemctl start dhan-oi-positional-buy.service
sudo systemctl enable option-buildup-scheduler.service
sudo systemctl list-units 'dhan*' 'option-buildup*' 'delta*'
```

## Notes

- Live candle evaluation is feed/aggregator-based.
- OMS is trade-led: positions are updated from fills, not inferred order state.
- Multi-strategy mode is supported via `strategy_name` + optional `strategy_names` list in `EngineConfig`.

## Further Reading

- `docs/MULTI_VENUE.md`
- `docs/PRODUCTION_UPGRADES.md`
- `core/engine/factory.py`
- `core/engine/live_engine.py`

## most repeated
sudo systemctl daemon-reload
sudo systemctl start dhan-oi-positional-buy.service
sudo systemctl start dhan-leaps-rsi.service
sudo systemctl enable option-buildup-scheduler.service