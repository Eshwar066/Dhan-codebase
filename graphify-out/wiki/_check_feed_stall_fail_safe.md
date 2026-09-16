# ._check_feed_stall_fail_safe

> 5 nodes

## Key Concepts

- **._check_feed_stall_fail_safe()** (5 connections) — `core/engine/live_engine.py`
- **NoMarketDataError** (4 connections) — `core/engine/live_engine.py`
- **._feed_health_symbols()** (3 connections) — `core/engine/live_engine.py`
- **RuntimeError** (1 connections)
- **Raised when WebSocket stays alive but market ticks stop arriving.** (1 connections) — `core/engine/live_engine.py`

## Relationships

- [LiveEngine](LiveEngine.md) (2 shared connections)
- [factory.py](factory.py.md) (1 shared connections)
- [make_event](make_event.md) (1 shared connections)
- [.start](start.md) (1 shared connections)
- [._is_market_open_for_feed_health](_is_market_open_for_feed_health.md) (1 shared connections)

## Source Files

- `core/engine/live_engine.py`

## Audit Trail

- EXTRACTED: 9 (90%)
- INFERRED: 1 (10%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*