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

Broker → BrokerApi → Source
Broker (business)
BrokerApi (exchange contract)
Source (transport)

Checking the broker structure to explain why the API layer exists.
There are two layers in the broker package:
Broker (e.g. DhanBroker) – application/order-management layer
Works with OrderIntent (strategy-level object).
Builds the order payload, handles retries, intent_store, idempotency (find_order_by_client_id), sync_positions, exit_position.
Depends on position_manager and intent_store.
BrokerApi (e.g. DhanBrokerApi) – exchange-facing layer
Works with raw order params: tradingsymbol, exchange, quantity, price, etc.
Exposes place_order(...), get_positions(), get_order_list().
For Dhan, it’s a thin wrapper over DhanSource (which actually talks to the broker).
So the “extra” API layer is the BrokerApi between the Broker and the real backend (e.g. DhanSource).
Why it exists
Single contract for all brokers
IBrokerApi defines one interface (place_order with raw params, get_positions, get_order_list). Dhan and Delta both implement that. The Broker only knows “call api.place_order(...)”; it doesn’t care if the backend is Dhan or Delta.
Separation of responsibilities
Broker: intent → payload, retries, intent_store, position sync (order-management logic).
BrokerApi: “how we call this exchange” (same shape for every exchange).
Testability
You can test DhanBroker (retries, payload building, intent_store updates) by passing a mock that implements IBrokerApi, without a real DhanSource or network.
Aligns with data vs orders
DhanSource does both data (candles, LTP, option chain) and orders. The data layer uses it only for data. The broker layer uses DhanBrokerApi (wrapping the same source) only for orders. So the “API” here is the order side of that source, behind a fixed contract.
Could you remove it?
Yes. You could have DhanBroker call DhanSource directly (e.g. dhan_source.place_order(...)), and keep only the Broker layer. You’d lose:
A single IBrokerApi-style contract for swapping Dhan vs Delta.
A clear place to mock “the exchange” when testing the Broker.
So the extra API layer is there to keep exchange communication behind one interface and order-management logic in the Broker, and to make testing and adding new brokers (e.g. Delta) easier. If you prefer a flatter design and are fine with the Broker depending on the concrete source, you could collapse BrokerApi into the Broker and still have a working setup.
