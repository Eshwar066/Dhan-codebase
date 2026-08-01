# Scale plan: many strategies + many accounts

How to run on the order of **~100 strategies** and **~50–100 accounts** on a droplet (or small fleet), given how this repo works today.

## What you have today

| Piece | Behavior at scale |
|-------|-------------------|
| `ENGINE_JOBS` + `--engine-id` | One OS process per engine (recommended); file lock prevents duplicates (`run/engine_lock.py`) |
| Multi-strategy per engine | Already works (`strategies: [...]`) — share feed/OMS |
| `AccountRouter` | Maps intent → `account_id` list; OMS queues / throttle / breaker per account |
| Broker / feed | **One** Dhan/Delta credential stack per engine (`DHAN_*` / `DELTA_*` in env) |
| Event bus | In-process only — not shared across droplets/processes |

**Important:** `account_id` today is routing + rate-limit isolation, not “50 different broker logins,” unless you add a broker pool. You cannot simply enable everything in one `ENGINE_JOBS` list and expect 100×100 to work safely.

Related docs: `README.md` (live flow), `docs/EVENT_BUS.md`, `docs/EVENT_DRIVEN_STRATEGY_GUIDE.md`, `docs/STRATEGY_MANIFEST.md`.

---

## Target topology (recommended)

```
                    ┌─────────────────────────────┐
                    │  Market data plane (shared) │
                    │  1–N feed processes / WS     │
                    └─────────────┬───────────────┘
                                  │ ticks / bars (queue or redis)
        ┌─────────────────────────┼─────────────────────────┐
        ▼                         ▼                         ▼
   Engine A                  Engine B                  Engine C
   (venue DHAN)              (venue DHAN)              (venue DELTA)
   strategies 1–20           strategies 21–40          crypto set
   accounts subset           accounts subset           accounts subset
        │                         │                         │
        └──────────► OMS workers per (account_id, symbol) ──┘
                              │
                              ▼
                    BrokerPool[account_id] → place_order
```

### Rules of thumb

- **Do not** run 100 strategies in one process (memory, one WS, one GIL, blast radius).
- **Do** pack **5–15 related strategies** per engine (same venue, similar TF/symbols).
- **Do** run **one systemd unit (or Docker) per `engine_id`**.
- **Accounts** fan out at OMS; strategies stay account-agnostic.

### Rough packing

| Dimension | Suggestion |
|-----------|------------|
| Strategies | ~100 → **8–20 engine processes** (not 100) |
| Accounts | 50–100 → routed via `account_routing`; real multi-login needs BrokerPool |
| Droplets | Start **1–2** (data+engines / or split DHAN vs DELTA); add more by venue or risk book |

---

## Product model (pick one)

1. **Copy-trade / fanout** — one signal → N accounts (same size or scaled capital). Fits current `AccountRouter` once broker-per-account exists.
2. **Assigned books** — strategy S only on accounts A1..Ak (`strategy_accounts`).
3. **Per-client engines** — each client gets own process + credentials (simplest ops, worst density; ~50–100 processes).

For 50–100 accounts, **(1)+(2)** on shared engines is the default. Use (3) only for VIP isolation.

---

## Phased plan

### Phase 0 — Decide the product model

Lock fanout vs assigned books vs per-client engines before building BrokerPool.

### Phase 1 — Config and ops shape (low code)

1. **Stop growing `run/config.py` as a mega-list.** Prefer:
   - `config/engines/*.yaml` — one file per `engine_id`
   - `config/accounts.yaml` — account ids, capital caps, enabled
   - `config/routing.yaml` — `default_accounts` / `strategy_accounts` / `symbol_accounts`
2. Wire `account_routing` into `job_to_engine_config` (`EngineConfig.account_routing` exists; ensure jobs pass it through `run/main.py` → factory).
3. **Packing policy**
   - Same venue + overlapping symbols → same engine
   - Heavy option-chain / scheduled BTST → own engine
   - PAPER vs LIVE → never same process
4. **systemd** (or Docker Compose) template:

```ini
# /etc/systemd/system/algo@.service
[Service]
ExecStart=/opt/algo/.venv/bin/python -m run.main --engine-id %i
Restart=on-failure
EnvironmentFile=/opt/algo/env/%i.env
```

Then: `systemctl enable --now algo@dhan_leaps_rsi algo@dhan_btst ...`

5. **Secrets**: one env file per engine *or* a vault; avoid one global `.env` with 100 tokens until BrokerPool exists.

### Phase 2 — Must-build for real multi-account (platform)

Without these, “100 accounts” is mostly labels on one login.

| Change | Why |
|--------|-----|
| **`BrokerPool` / `AccountBrokerRegistry`** | `account_id` → credentials + `IBrokerApi` instance |
| **OMS place path uses pool** | `ExecutionEngine` / `OrderRouter` call `pool.get(account_id).place_order(...)` |
| **Per-account position + risk** | Capital, daily loss, max positions scoped by account (and optionally strategy) |
| **Fill / order WS per account** (or multiplex) | Reconcile fills to the right book |
| **Intent idempotency includes `account_id`** | Same signal must not double-fill one account; fanout must be explicit |
| **Sizing policy** | `qty = f(account.capital, risk%)` at route time, not hardcoded lots in strategy |

Keep strategies dumb: they emit intents; platform fans out and sizes.

### Phase 3 — Must-build for 100 strategies (platform)

| Change | Why |
|--------|-----|
| **Shared market-data process** | Avoid 20× Dhan WS for the same NIFTY/BANKNIFTY set (broker limits + CPU) |
| **Engine packs from manifests** | Auto-group by venue/TF/symbols; don’t hand-edit 20 job files forever |
| **Hard caps** | `max_strategies_per_engine`, `max_symbols_per_feed`, eval timeouts |
| **Supervisor / health** | Process dead → alert; feed stall → pause entries (bus already has feed events) |
| **Central metrics** | Per engine_id / strategy / account: evals, intents, fills, queue depth, breaker trips |

Event bus stays **per engine**. Do **not** make one global bus across 100 strategies first — use process isolation + shared feed.

### Phase 4 — Droplet / server layout

#### Small start (≤ ~20 engines, ≤ ~30 accounts, one venue)

- 1 droplet: **4–8 vCPU, 16–32 GB RAM**
- SSD for logs; separate volume if logs grow
- `ulimit -n` high (many WS + files)
- NTP synced; IST-aware jobs already in code
- Logrotate on `logs/{engine_id}*.log` and `*_events.jsonl`

#### Medium (target: ~100 strategies / ~50–100 accounts)

| Role | Droplet | Runs |
|------|---------|------|
| **Feed / data** | 2–4 vCPU, 8 GB | Shared WS → republish ticks/bars |
| **DHAN engines** | 4–8 vCPU, 16–32 GB | systemd units for India engines |
| **DELTA engines** | separate if crypto concurrent | Crypto jobs |
| **Ops** | small | Prometheus/Grafana or simple health + Telegram |

#### Hard rules on the box

1. One live process per `engine_id` (lock already enforces this).
2. Never `python -m run.main --venue DHAN` with dozens of enabled jobs in one process at this scale — always `--engine-id`.
3. Cap concurrent OMS: tune `oms_rate_limit_per_sec`, `max_active_account_symbol_keys`, `account_queue_maxsize` per engine.
4. Disk: event tap + intent pipeline JSONL will explode at 100×50 — sample or ship to remote logging.
5. Backups: intent_store / position snapshots; restart must reconcile broker positions (extend per account).

#### Horizontal scale later

- Shard engines by symbol universe or client book across droplets.
- Shared feed stays single-writer; engines are consumers.
- No shared SQLite across hosts without a real DB if you outgrow local stores.

### Phase 5 — Rollout sequence (safe)

1. **Paper**: 1 engine × 5 strategies × 3 fake accounts (routing only).
2. **Live**: 1 engine × 1 strategy × 2 real accounts (BrokerPool).
3. Scale accounts on that strategy (10 → 50) while watching rate limits / breakers.
4. Add engines (strategy packs), not more strategies into one process.
5. Only then approach 100 strategies / 100 accounts.

---

## What not to do

- 100 `ENGINE_JOBS` each with one strategy and one process on a 2 GB droplet.
- One mega-process with 100 strategies and one Dhan token for 100 clients.
- Rely on the event bus alone for multi-tenant isolation — **process + account broker + risk** isolate money.
- Put account credentials or routing inside strategy classes.

---

## Priority change list

1. Pass `account_routing` from job → `EngineConfig` → factory (almost there).
2. Externalize engines / accounts / routing config.
3. systemd `@` template + one env per engine.
4. **BrokerPool** + per-account risk / positions / fills.
5. Shared feed process when engine count > ~5 on same symbols.
6. Metrics + log volume control.
7. Optional: auto-pack strategies from manifests into engines.

---

## Bottom line

- **100 strategies** → many **small engine processes**, packed by venue/symbols, managed by systemd on the droplet.
- **50–100 accounts** → `AccountRouter` fanout **plus** a real **per-account broker/risk** layer (the main missing piece).
- **Event-driven** helps strategy wiring inside each engine; **ops scale** is process sharding + shared market data + account pool, not one giant bus.



====================
GPT:

This is a solid roadmap. Based on everything we've discussed about your architecture, I would make a few additions and change the implementation order slightly so you don't have to refactor later.

Updated Scale Roadmap (Production Grade)
P0 — Foundation (Do First)

These are prerequisites before adding more strategies.

Engine Configuration
Move to config/engines/*.yaml
config/accounts.yaml
config/routing.yaml

Each engine becomes completely configurable without editing Python.

Example

config/
    engines/
        dhan_intraday.yaml
        dhan_btst.yaml
        delta_crypto.yaml

    accounts.yaml

    routing.yaml
Strategy Manifest

Every strategy should expose

strategy_id
venue
symbols
timeframes
required_feed
required_greeks
required_option_chain
risk_profile
capital_required

Later this enables automatic packing.

One process = One Engine

Never run

python run.main --venue DHAN

Instead

python run.main --engine-id dhan_intraday
systemd Template

Exactly as you've written.

One engine = one service.

P1 — Observability (Must Build Early)

This is one area I would move much earlier.

When you have 20+ engines, debugging without observability becomes impossible.

Add

OpenTelemetry

Instrument

strategy evaluation
signal generation
OMS latency
broker latency
websocket latency
order placement
fills

Useful spans

Strategy Evaluation
    ↓
Signal Generated
    ↓
Risk Check
    ↓
Order Routed
    ↓
Broker API
    ↓
Fill
Prometheus Metrics

Expose

engine_up

strategy_evaluations_total

signals_generated_total

orders_sent_total

orders_rejected_total

fills_total

feed_disconnects_total

feed_latency_ms

broker_latency_ms

account_queue_depth

account_breaker_open

risk_rejections

positions_open

capital_used

capital_available
Grafana Dashboards

Create dashboards

Engine

CPU
Memory
Queue Depth
Feed Status

Strategy

Evaluations/sec
Signals
Win Rate
Latency

OMS

Queue Size
Broker Errors
Fill Delay

Account

Capital Used
Daily PnL
Daily Loss
Breaker Status
Loki (optional)

Instead of storing

logs/*.jsonl

ship

Promtail
↓

Loki
↓

Grafana

Searching logs becomes much easier.

Alertmanager

Send alerts for

Feed disconnected
Broker disconnected
Strategy panic
Daily loss exceeded
OMS queue overflow
Engine dead
Order rejection spike

Telegram

Slack

Email

P2 — Broker Layer

Biggest missing component.

Today

Strategy

↓

OMS

↓

Broker

Future

Strategy

↓

OMS

↓

BrokerPool

↓

Broker(account1)

↓

Broker(account2)

↓

Broker(account3)

Each account has

credentials

websocket

positions

orders

risk

rate limiter

breaker
P3 — Multi-Account Fanout

Current flow

Signal

↓

Intent

↓

Order

Future

Signal

↓

Intent

↓

AccountRouter

↓

Account A

↓

Account B

↓

Account C

↓

OMS Queue

↓

BrokerPool

Each account independently

sizes quantity
risk checks
places order
receives fills
updates positions

One account failing must never affect another.

P4 — Shared Feed

Very important once engine count grows.

Today

20 engines

↓

20 websocket connections

Future

One Feed Service

↓

Redis / NATS

↓

All Engines

Benefits

fewer websocket connections
broker limits
less CPU
synchronized ticks
P5 — OMS Improvements

Current

Signal

↓

OrderRouter

↓

Broker

Future

Signal

↓

Intent Queue

↓

Risk Queue

↓

Sizing

↓

Account Queue

↓

Broker Queue

↓

Broker

Every stage becomes independently scalable.

P6 — Position Service

Instead of every engine owning positions

Engine

↓

PositionManager

Eventually

Position Service

↓

Engine A

Engine B

Engine C

Single source of truth.

P7 — Risk Service

Current

RiskManager

Future

Global Risk

↓

Engine Risk

↓

Account Risk

↓

Strategy Risk

Limits

max capital

daily loss

max positions

max open lots

max option exposure

max delta

max gamma

max vega
P8 — Event Streaming

Current

Python EventBus

Future

Engine

↓

Kafka / NATS

↓

Consumers

Consumers

Metrics
Position Service
Notification
Audit
Dashboard

Keep EventBus inside each engine.

Never share Python EventBus between engines.

P9 — Deployment
GitHub

↓

GitHub Actions

↓

Docker Image

↓

Docker Registry

↓

Droplet

↓

systemd / docker compose

Automatic

tests
lint
deploy
P10 — Autoscaling

Eventually

Engine Packer

↓

reads manifests

↓

packs strategies

↓

starts engines

↓

systemd

or

Docker

No manual configuration.

Multi-Account Order Flow

I would slightly refine your proposed order placement flow.

Strategy

↓

Signal

↓

AccountRouter

↓

Account A
Account B
Account C
Account D

↓

RiskManager(account)

↓

Quantity Calculator(account)

↓

OMS Queue(account)

↓

Broker(account)

↓

Exchange

↓

Fill

↓

Position(account)

↓

PnL(account)

This gives complete isolation.

Recommended Technology Stack
Component	Technology
Metrics	OpenTelemetry
Metrics Store	Prometheus
Dashboards	Grafana
Logs	Loki
Log Shipping	Promtail
Alerts	Alertmanager
Distributed Queue	Redis Streams / NATS (later Kafka if needed)
Config	YAML
Secrets	Vault or per-engine env
Deployment	Docker + systemd
CI/CD	GitHub Actions
Reverse Proxy	Nginx
Process Monitoring	systemd
Health Checks	/health endpoint
Profiling	OpenTelemetry + Pyroscope (optional)
Revised Priority Order
Strategy manifests
Externalized YAML configs
account_routing wiring
systemd engine template
OpenTelemetry instrumentation
Prometheus metrics
Grafana dashboards
BrokerPool / AccountBrokerRegistry
Multi-account OMS with per-account queues
Per-account risk, positions, and fills
Shared market-data service
Centralized logging (Loki + Promtail)
Alerting (Alertmanager + Telegram/Slack)
Deployment automation (Docker + GitHub Actions)
Auto-packing of strategies into engine groups