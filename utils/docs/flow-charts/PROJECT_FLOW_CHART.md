# Project Flow Chart (Current Runtime)

This file documents the **current** execution flow using actual module names.

## 1) Module Map

```mermaid
flowchart TB
    subgraph Entry["Entry + Config"]
      A["run/main.py"]
      B["run/config.py (STRATEGY_JOBS, RUN_MODE)"]
      C["run/engine_config.py (EngineConfig)"]
    end

    subgraph Orchestration["Engine Orchestration"]
      D["core/engine/factory.py"]
      E["core/engine/live_engine.py"]
      F["core/engine/backtest_engine.py"]
      G["core/engine/base_engine.py"]
      H["core/engine/supervisor.py"]
    end

    subgraph Strategies["Strategies"]
      I["core/strategies/registry.py"]
      J["core/strategies/base.py"]
      K["core/strategies/*"]
    end

    subgraph Data["Data + Feeds"]
      L["core/data/sources/*"]
      M["core/data/datalayer/*"]
      N["core/data/candle_aggregator.py"]
      O["core/data/feeds/dhan_feed.py"]
      P["core/data/feeds/delta_feed.py"]
      Q["core/data/feeds/dhan_order_update_feed.py"]
    end

    subgraph OMS["OMS + Risk + Routing"]
      R["core/orderExecution/intent_store.py"]
      S["core/orderExecution/risk_manager.py"]
      T["core/orderExecution/position_manager.py"]
      U["core/orderExecution/account_router.py"]
      V["core/orderExecution/order_router.py"]
    end

    subgraph Broker["Broker Adapters"]
      W["core/broker/internal/dhan/*"]
      X["core/broker/internal/delta/*"]
      Y["core/broker/internal/simulated/broker.py"]
    end

    subgraph Logs["Observability"]
      Z["logger/engine_logger.py"]
      ZA["logger/trade_logger.py"]
      ZB["logger/open_positions_logger.py"]
    end

    B --> A
    C --> A
    A --> D
    D --> E
    D --> F
    D --> I
    D --> L
    D --> M
    D --> O
    D --> P
    D --> Q
    D --> U
    D --> V
    D --> W
    D --> X
    D --> Y
    E --> N
    E --> K
    V --> R
    V --> S
    V --> T
    E --> Z
    E --> ZA
    E --> ZB
    D --> H
```

## 2) Live Runtime Flow (Feed-Driven)

```mermaid
flowchart TD
    A["python -m run.main --venue DHAN/DELTA"] --> B["run/main.py"]
    B --> C["job_to_engine_config()"]
    C --> D["EngineFactory.create_live_engine()"]

    D --> E["Build strategy + optional strategy_names"]
    D --> F["Build provider + broker + OMS"]
    D --> G["Build websocket feed(s)"]
    D --> H["Optional tick_queue + CandleAggregator"]
    D --> I["LiveEngine.start()"]

    I --> J["Main loop: feed health, memory/risk checks, order-state checks"]
    J --> K{"tick_queue + aggregator available?"}
    K -- yes --> L["drain tick_queue -> CandleAggregator.on_tick()"]
    L --> M["get last closed candle per symbol"]
    K -- no --> N["use feed candle/ticker snapshot path"]

    M --> O["dispatch candle to per-strategy worker threads"]
    N --> O
    O --> P["strategy.on_candle -> intents"]
    P --> Q["bounded intent_queue (non-blocking policy)"]
    Q --> R["AccountRouter.route(intent)"]
    R --> S["bounded queue per (account_id, symbol)"]
    S --> T["OMS worker per key: token bucket + retry + per-account breaker"]
    T --> U["OrderRouter.process_intent()"]
    U --> V["Broker.place_order()"]

    G --> W["Dhan order-update feed / Delta user trades"]
    W --> X["OrderRouter.process_trade() (trade-led fills)"]
    X --> Y["PositionManager update from fills"]

    I --> Z["Structured logs + intent journal"]
```

## 3) OMS Detail (Threaded Fanout)

```mermaid
flowchart LR
    A["Per-strategy worker (1 thread each)"] --> B["intent_queue (bounded)"]
    B --> C["AccountRouter"]
    C --> D["Queue key: (account_id, symbol)"]
    D --> E["OMS worker per key"]
    E --> F["token bucket per account"]
    E --> G["retry w/ exponential backoff"]
    E --> H["execution_attempt_id logging"]
    E --> I["OrderRouter -> Broker"]
```

## 4) Operational Boundaries

- `run/` handles process entry, CLI and job -> `EngineConfig`.
- `core/engine/` owns orchestration and lifecycle.
- `core/data/` owns sources, providers, websocket feeds, candle aggregation.
- `core/strategies/` owns signal generation (`on_candle`).
- `core/orderExecution/` owns intent lifecycle, risk, routing, position state.
- `core/broker/internal/*` maps orders/fills to broker APIs.
- `logger/` and `core/analytics/` handle telemetry and reporting.

## 5) Current Notes

- Live path is feed/aggregator-driven; no REST candle fallback in live loop.
- `PAPER` uses live data path with simulated execution.
- Multi-strategy live mode runs one worker thread per strategy.
- Queue growth is bounded at strategy, intent, and account-symbol stages.

## 6) LLD - Candle to Intent Path

```mermaid
sequenceDiagram
    participant LE as LiveEngine main loop
    participant CA as CandleAggregator
    participant SW as StrategyWorker(strategy_id)
    participant SQ as strategy_queue[strategy_id]
    participant IQ as intent_queue

    LE->>CA: on_tick() / get_last_closed_candle(symbol, tf)
    CA-->>LE: closed candle
    LE->>SQ: enqueue {candle, response_q} (non-blocking)
    SQ->>SW: dequeue task
    SW->>SW: ctx = build_context_only(candle)
    SW->>SW: intent = strategy.on_candle(candle, ctx)
    SW-->>LE: response {intent, strategy_time_ms}
    LE->>IQ: enqueue normalized intent payload
    Note over LE,IQ: includes intent_id, strategy_id, symbol,<br/>created_at, strategy_time_ms
```

## 7) LLD - Intent Routing and Ordering

```mermaid
flowchart TD
    A["intent_queue.get()"] --> B{"already routed intent_id?"}
    B -- yes --> Z["skip"]
    B -- no --> C["accounts = AccountRouter.route(intent)"]
    C --> D["for each account_id"]
    D --> E["symbol = intent.symbol || instrument.trading_symbol"]
    E --> F{"active key count >= max_active_keys?"}
    F -- yes --> G["key = (account_id, __FALLBACK__)"]
    F -- no --> H["key = (account_id, symbol)"]
    G --> I["get/create bounded queue per key"]
    H --> I
    I --> J["get/create OMS worker for key"]
    J --> K["enqueue routed payload (non-blocking policy)"]
    K --> L["mark intent as ROUTED"]
```

## 8) LLD - OMS Worker Path (Per Account-Symbol Key)

```mermaid
flowchart TD
    A["worker loop: queue.get(timeout)"] --> B{"account paused?"}
    B -- yes --> A
    B -- no --> C{"intent_id already executed?"}
    C -- yes --> A
    C -- no --> D["oms_start_ts = now"]
    D --> E["token_bucket_wait(account_id)"]
    E --> F["_process_intent_with_retry(item)"]
    F --> G{"ok?"}
    G -- no --> H["account_failure_count++"]
    H --> I{"count >= account_circuit_breaker_threshold?"}
    I -- yes --> J["pause account_id"]
    I -- no --> A
    G -- yes --> K["executed_intent_ids.add(intent_id)"]
    K --> L["journal SENT to logs/{engine_id}_intent_pipeline.jsonl"]
    L --> M["compute end-to-end latency"]
    M --> N{"latency > latency_critical_ms?"}
    N -- yes --> O["entries_paused_latency = true"]
    N -- no --> A
    O --> A
```

## 9) LLD - Retry State Machine

```mermaid
stateDiagram-v2
    [*] --> Attempt_1
    Attempt_1 --> Success: process_intent ok
    Attempt_1 --> Retry_2: retryable error
    Attempt_1 --> Failed: fatal/non-retryable

    Retry_2 --> Success: process_intent ok
    Retry_2 --> Retry_3: retryable error
    Retry_2 --> Failed: fatal/non-retryable

    Retry_3 --> Success: process_intent ok
    Retry_3 --> Failed: max attempts reached

    Success --> [*]
    Failed --> [*]
```

## 10) LLD - Trade-Led Fill Update Path

```mermaid
sequenceDiagram
    participant Feed as Broker user-trade feed / fills API
    participant OR as OrderRouter
    participant IS as IntentStore
    participant PM as PositionManager
    participant RM as RiskManager

    Feed->>OR: process_trade(trade)
    OR->>OR: dedup by trade_id
    OR->>IS: resolve intent by client_order_id / tag / broker_order_id
    OR->>PM: on_fill(...)
    PM-->>OR: position_closed?, realized_pnl
    OR->>RM: record_realized_pnl() if closed
    OR->>IS: update status FILLED + order_state
    OR-->>Feed: ack internally (idempotent)
```

## 11) LLD - Watchdog and Worker Recovery

```mermaid
flowchart TD
    A["watchdog loop every worker_watchdog_interval_seconds"] --> B["check route worker"]
    B --> C["check strategy workers"]
    C --> D["check OMS key workers"]
    D --> E{"worker dead?"}
    E -- no --> A
    E -- yes --> F{"restart count in last 60s < limit?"}
    F -- yes --> G["restart worker + track timestamp"]
    F -- no --> H["disable worker_id + critical alert"]
    G --> A
    H --> A
```

sequenceDiagram
    participant Main as Main loop
    participant SW as strategy_worker
    participant RS as _run_strategy
    participant PE as _process_entry_like_intent
    participant Q as intent_queue
    participant Router as route_intents_worker
    participant OMS as account_symbol OMS worker
    participant Broker as order_router / broker

    Main->>SW: task on strategy queue
    SW->>SW: on_candle → [OrderIntent]
    SW->>Main: response_q.put(intent, ctx, ...)
    Main->>RS: _run_strategy(...)
    RS->>PE: for each entry intent
    PE->>PE: risk, hours, dedupe, depth price
    PE->>Q: _enqueue_intent
    Router->>OMS: route by account/symbol
    OMS->>Broker: process_intent (LIMIT BUY)
    Broker-->>Main: fill → position_manager

