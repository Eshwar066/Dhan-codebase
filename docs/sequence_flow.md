# Sequence Flows

Low-level message paths between engine components.

- [Candle → intent](#candle-to-intent)
- [Trade-led fills](#trade-led-fill-update)
- [Strategy → broker (entry handoff)](#strategy-to-broker-entry-handoff)

---

## Candle to intent

```mermaid
sequenceDiagram
    participant LE as LiveEngine main loop
    participant CA as CandleAggregator
    participant IM as IndicatorManager
    participant SW as StrategyWorker(strategy_id)
    participant SQ as strategy_queue[strategy_id]
    participant IQ as intent_queue

    LE->>CA: on_tick() / get_last_closed_candle(symbol, tf)
    CA-->>LE: closed candle
    LE->>IM: enrich_candle_for_strategy (per strategy, main thread)
    IM-->>LE: candle + indicators (RSI, etc.)
    LE->>SQ: enqueue {candle, response_q} (non-blocking)
    SQ->>SW: dequeue task
    SW->>SW: ctx = build_context_only(candle)
    SW->>SW: intent = strategy.on_candle(candle, ctx)
    SW-->>LE: response {intent, strategy_time_ms}
    LE->>IQ: enqueue normalized intent payload
    Note over LE,IQ: includes intent_id, strategy_id, symbol,<br/>created_at, strategy_time_ms
```

---

## Trade-led fill update

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

---

## Strategy to broker (entry handoff)

Main thread receives strategy worker response, runs risk/depth checks, then routes to OMS.

```mermaid
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
```

See [oms_flow.md](oms_flow.md) for routing and retry detail.
