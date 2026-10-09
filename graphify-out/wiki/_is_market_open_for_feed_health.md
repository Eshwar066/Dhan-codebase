# ._is_market_open_for_feed_health

> 11 nodes

## Key Concepts

- **._is_market_open_for_feed_health()** (6 connections) — `core/engine/live_engine_common.py`
- **.check_feed_health()** (5 connections) — `core/engine/live_engine_common.py`
- **_within_trading_hours_utc()** (5 connections) — `core/engine/live_engine_common.py`
- **._notify_dhan_feed_connection_state()** (3 connections) — `core/engine/live_engine_common.py`
- **._within_trading_hours()** (3 connections) — `core/engine/live_engine_common.py`
- **_parse_time()** (3 connections) — `core/engine/live_engine_common.py`
- **Parse 'HH:MM' to (hour, minute).** (1 connections) — `core/engine/live_engine_common.py`
- **True if now (UTC) falls within any (start, end) window. Times in 'HH:MM' UTC.** (1 connections) — `core/engine/live_engine_common.py`
- **When False, skip feed staleness checks (no ticks overnight is expected). If…** (1 connections) — `core/engine/live_engine_common.py`
- **Send Telegram updates for Dhan feed connect/disconnect transitions.** (1 connections) — `core/engine/live_engine_common.py`
- **Warn if no tick/candle received for feed_stale_seconds; optionally pause…** (1 connections) — `core/engine/live_engine_common.py`

## Relationships

- [LiveEngineHelpersMixin](LiveEngineHelpersMixin.md) (4 shared connections)
- [factory.py](factory.py.md) (2 shared connections)
- [._check_feed_stall_fail_safe](_check_feed_stall_fail_safe.md) (1 shared connections)
- [NiftySMA9Weekly](NiftySMA9Weekly.md) (1 shared connections)
- [._should_disconnect_market_ws](_should_disconnect_market_ws.md) (1 shared connections)
- [._candle_timestamp_to_utc_naive](_candle_timestamp_to_utc_naive.md) (1 shared connections)

## Source Files

- `core/engine/live_engine_common.py`

## Audit Trail

- EXTRACTED: 19 (95%)
- INFERRED: 1 (5%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*