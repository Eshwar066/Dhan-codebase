# ExecutionEngine

> 19 nodes

## Key Concepts

- **ExecutionEngine** (23 connections) — `core/engine/execution_engine.py`
- **Any** (9 connections)
- **._append_intent_journal()** (6 connections) — `core/engine/execution_engine.py`
- **._process_intent_with_retry()** (6 connections) — `core/engine/execution_engine.py`
- **._can_restart_worker()** (5 connections) — `core/engine/execution_engine.py`
- **._process_account_symbol_queue()** (5 connections) — `core/engine/execution_engine.py`
- **.safe_queue_put()** (5 connections) — `core/engine/execution_engine.py`
- **.enqueue_intent_bundle()** (4 connections) — `core/engine/execution_engine.py`
- **._ensure_workers_healthy()** (4 connections) — `core/engine/execution_engine.py`
- **._log_oms_pipeline()** (4 connections) — `core/engine/execution_engine.py`
- **.enqueue_intent()** (3 connections) — `core/engine/execution_engine.py`
- **._route_intents_worker()** (3 connections) — `core/engine/execution_engine.py`
- **._worker_id()** (3 connections) — `core/engine/execution_engine.py`
- **.__init__()** (2 connections) — `core/engine/execution_engine.py`
- **.start()** (2 connections) — `core/engine/execution_engine.py`
- **._token_bucket_wait()** (2 connections) — `core/engine/execution_engine.py`
- **._watchdog_loop()** (2 connections) — `core/engine/execution_engine.py`
- **Enqueue hedge+main (or other multi-leg) as one OMS unit for combined margin.** (1 connections) — `core/engine/execution_engine.py`
- **OMS execution pipeline extracted from LiveEngine: intent enqueue -> account…** (1 connections) — `core/engine/execution_engine.py`

## Relationships

- [factory.py](factory.py.md) (4 shared connections)
- [._is_retryable_intent_error](_is_retryable_intent_error.md) (2 shared connections)
- [Any](Any.md) (1 shared connections)
- [Phased plan](Phased_plan.md) (1 shared connections)
- [Watchdog and Worker Recovery](Watchdog_and_Worker_Recovery.md) (1 shared connections)
- [LiveEngine](LiveEngine.md) (1 shared connections)

## Source Files

- `core/engine/execution_engine.py`

## Audit Trail

- EXTRACTED: 47 (94%)
- INFERRED: 3 (6%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*