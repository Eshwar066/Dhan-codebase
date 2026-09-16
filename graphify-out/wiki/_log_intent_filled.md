# ._log_intent_filled

> 13 nodes

## Key Concepts

- **._log_intent_filled()** (6 connections) — `core/engine/live_engine.py`
- **._normalize_delta_ws_trade()** (5 connections) — `core/engine/live_engine.py`
- **._normalize_dhan_ws_synthetic_trade()** (5 connections) — `core/engine/live_engine.py`
- **._on_dhan_ws_synthetic_trade()** (5 connections) — `core/engine/live_engine.py`
- **.on_ws_trade()** (5 connections) — `core/engine/live_engine.py`
- **._retry_dhan_pending_fills()** (5 connections) — `core/engine/live_engine.py`
- **._sync_delta_ws_trades()** (5 connections) — `core/engine/live_engine.py`
- **._enqueue_dhan_pending_fill()** (3 connections) — `core/engine/live_engine.py`
- **Normalize Delta user-trade websocket payload to OrderRouter.process_trade shape.** (1 connections) — `core/engine/live_engine.py`
- **Apply websocket user-trades to OMS immediately (faster than periodic fills API…** (1 connections) — `core/engine/live_engine.py`
- **Event-driven websocket trade callback: apply fills immediately.** (1 connections) — `core/engine/live_engine.py`
- **Map incremental order-update fill to OrderRouter.process_trade shape. Primary…** (1 connections) — `core/engine/live_engine.py`
- **Replay fills that arrived before broker_order_id / CorrelationId was visible.** (1 connections) — `core/engine/live_engine.py`

## Relationships

- [LiveEngine](LiveEngine.md) (8 shared connections)
- [Any](Any.md) (6 shared connections)
- [.start](start.md) (2 shared connections)

## Source Files

- `core/engine/live_engine.py`

## Audit Trail

- EXTRACTED: 30 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*