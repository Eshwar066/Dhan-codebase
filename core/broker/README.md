# Broker Layer

**Purpose:** Order placement and position/order lookup only. No market data (LTP, option chain, expiries) — that lives in the **data layer** (`core/data/datalayer`).

## What goes here

- **Place order:** `Broker.place_order(intent, execution_price, retries)`
- **Exit position:** `Broker.exit_position(...)`
- **Position / order lookup:** via `IBrokerApi.get_positions()`, `get_order_list()`

Engines get **data** from `IDataProvider`; **OrderRouter** sends intents to a **Broker** (which uses an `IBrokerApi`).

## File structure (internal layout)

```
core/broker/
  base.py              # IBrokerApi, BaseBroker (abstract contracts)
  __init__.py          # Public API: re-exports all brokers and base
  internal/
    __init__.py        # Re-exports DhanBroker, DhanBrokerApi, DeltaBroker, DeltaBrokerApi, SimulatedBroker
    dhan/
      api.py           # DhanBrokerApi
      broker.py        # DhanBroker
    delta/
      api.py           # DeltaBrokerApi (stub)
      broker.py        # DeltaBroker
    simulated/
      broker.py        # SimulatedBroker (backtest)
```

**Use in app code:** `from core.broker import DhanBroker, DhanBrokerApi, DeltaBroker, DeltaBrokerApi, SimulatedBroker, BaseBroker, IBrokerApi`  
Do not import from `core.broker.internal.*` in application code; use the package root.

## Brokers

- **DhanBroker** – uses `DhanBrokerApi` (wraps Dhan for orders only).
- **DeltaBroker** – uses `DeltaBrokerApi` (Delta Exchange). Leverage is set from config: per-job `delta_leverage` (e.g. 10) is applied at engine start for the job's symbols via Delta API (`set_leverage_for_symbols`). Order payloads set `reduce_only` from intent action: ENTRY → `false`, EXIT → `true` (see main README “Delta Exchange: reduce_only (OMS rule)”).
- **SimulatedBroker** – used for PAPER and BACKTEST; no exchange.

**Funds/margin check:** The broker's `check_funds_before_order` is invoked by OrderRouter only for **ENTRY** intents. **EXIT** and **FORCE_EXIT** never undergo funds check so positions can always be closed.

## Flow

```
Strategy → Intent → RiskManager → OrderRouter → Broker.place_order()
                                              → IBrokerApi (Dhan / Delta)
                                              → Fill → PositionManager
```

## Adding Delta Exchange

1. Implement real `DeltaBrokerApi` in `internal/delta/api.py` (place_order, get_positions, get_order_list) using Delta SDK/API.
2. In `run/main.py`, set `BROKER_NAME = "DELTA"` and pass `DeltaBrokerApi(...)` into `DeltaBroker`.
3. Data can stay on Dhan/NSE until Delta provides a data feed; then add `DeltaDataProvider` in the data layer.

## Layering (Source → Api → Broker)

```
Strategy → OrderRouter → Broker (intent, retries, intent_store)
                              → BrokerApi (IBrokerApi: raw place_order params)
                                   → Source (DhanSource / DeltaSource transport)
```

| Layer | Responsibility | Do not |
|-------|----------------|--------|
| **Source** | HTTP/WS to exchange; candles, quotes, raw `place_order` | Build `OrderIntent` payloads |
| **BrokerApi** | Thin `IBrokerApi` adapter over Source | Risk checks, position accounting |
| **Broker** | `OrderIntent` → payload, retries, fill sync, `exit_position` | Fetch option chains / indicators |

**Data vs orders:** `DhanSource` can do both; the data layer uses it for market data only. The broker stack uses `DhanBrokerApi` → same source for orders only. Do not duplicate order placement in strategies or the data layer.

**App imports:** `from core.broker import DhanBroker, DhanBrokerApi` — not `core.broker.internal.*`.

