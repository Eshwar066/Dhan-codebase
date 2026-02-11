# Broker Layer

**Purpose:** Order placement and position/order lookup only. No market data (LTP, option chain, expiries) — that lives in the **data layer** (`core/data/datalayer`).

## What goes here

- **Place order:** `Broker.place_order(intent, execution_price, retries)`
- **Exit position:** `Broker.exit_position(...)`
- **Position / order lookup:** via `IBrokerApi.get_positions()`, `get_order_list()`

Engines get **data** from `IDataProvider`; **OrderRouter** sends intents to a **Broker** (which uses an `IBrokerApi`).

## Brokers

- **DhanBroker** – uses `DhanBrokerApi` (wraps Dhan for orders only).
- **DeltaBroker** – uses `DeltaBrokerApi` (stub for Delta Exchange; wire real API when ready).
- **SimulatedBroker** – backtest; no exchange.

## Flow

```
Strategy → Intent → RiskManager → OrderRouter → Broker.place_order()
                                              → IBrokerApi (Dhan / Delta)
                                              → Fill → PositionManager
```

## Files

| File | Role |
|------|------|
| `base_broker.py` | BaseBroker ABC: place_order(intent, execution_price, retries), exit_position(...) |
| `broker_api.py` | IBrokerApi: place_order(...), get_positions(), get_order_list() |
| `dhan_broker_api.py` | DhanBrokerApi – wraps DhanSource for orders only |
| `dhanbroker.py` | DhanBroker – converts OrderIntent to payload, calls api.place_order |
| `delta_broker_api.py` | DeltaBrokerApi (stub) |
| `delta_broker.py` | DeltaBroker |
| `simulated_broker.py` | SimulatedBroker – backtest; on_fill → PositionManager |

## Adding Delta Exchange

1. Implement real `DeltaBrokerApi` (place_order, get_positions, get_order_list) using Delta SDK/API.
2. In `run/main.py`, set `BROKER_NAME = "DELTA"` and pass `DeltaBrokerApi(...)` into `DeltaBroker`.
3. Data can stay on Dhan/NSE until Delta provides a data feed; then add `DeltaDataProvider` in the data layer.

