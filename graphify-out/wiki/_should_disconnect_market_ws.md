# ._should_disconnect_market_ws

> 8 nodes

## Key Concepts

- **._should_disconnect_market_ws()** (6 connections) — `core/engine/live_engine_common.py`
- **._is_market_open_for_live_candles()** (5 connections) — `core/engine/live_engine_common.py`
- **._should_run_live_candle_pipeline()** (5 connections) — `core/engine/live_engine_common.py`
- **._sync_market_ws_to_session()** (4 connections) — `core/engine/live_engine_common.py`
- **._has_unevaluated_session_partial_candle()** (3 connections) — `core/engine/live_engine_common.py`
- **Gate tick drain and live candle evaluation (same calendar as feed health).** (1 connections) — `core/engine/live_engine_common.py`
- **True after NSE index regular session end (post 15:30 IST), not pre-market.** (1 connections) — `core/engine/live_engine_common.py`
- **Disconnect Dhan market WS after close; reconnect when session reopens.** (1 connections) — `core/engine/live_engine_common.py`

## Relationships

- [LiveEngineHelpersMixin](LiveEngineHelpersMixin.md) (5 shared connections)
- [Any](Any.md) (1 shared connections)
- [._is_market_open_for_feed_health](_is_market_open_for_feed_health.md) (1 shared connections)
- [NiftySMA9Weekly](NiftySMA9Weekly.md) (1 shared connections)

## Source Files

- `core/engine/live_engine_common.py`

## Audit Trail

- EXTRACTED: 17 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*