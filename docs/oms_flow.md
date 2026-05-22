# OMS Flow

Order management: routing, per-account-symbol workers, token bucket, and broker handoff. Implemented in `core/engine/execution_engine.py` (delegated from `LiveEngine`).

See also: [retry_state_machine.md](retry_state_machine.md), [sequence_flow.md](sequence_flow.md), [watchdog.md](watchdog.md).

## Threaded fanout (overview)

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

## Intent routing and ordering

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

## OMS worker path (per account–symbol key)

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

## Key modules

| Module | Role |
|--------|------|
| `core/orderExecution/intent_store.py` | Intent lifecycle and dedupe |
| `core/orderExecution/account_router.py` | Account selection per intent |
| `core/orderExecution/order_router.py` | `process_intent`, `process_trade` |
| `core/orderExecution/risk_manager.py` | Pre-trade checks, realized PnL |
| `core/orderExecution/position_manager.py` | Positions from fills |
| `core/engine/execution_engine.py` | Queues, workers, token bucket, retries, watchdog hooks |
