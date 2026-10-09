# DosTrailSlMixin

> 18 nodes

## Key Concepts

- **DosTrailSlMixin** (17 connections) — `core/strategies/crypto/DirectionalOptionSelling/trail_sl.py`
- **._modify_broker_trail_sl()** (11 connections) — `core/strategies/crypto/DirectionalOptionSelling/trail_sl.py`
- **._apply_trail_sl_update()** (7 connections) — `core/strategies/crypto/DirectionalOptionSelling/trail_sl.py`
- **Any** (7 connections)
- **._retry_pending_trail_sl()** (6 connections) — `core/strategies/crypto/DirectionalOptionSelling/trail_sl.py`
- **._trail_sl_level()** (6 connections) — `core/strategies/crypto/DirectionalOptionSelling/trail_sl.py`
- **._sl_strike_side_from_position()** (5 connections) — `core/strategies/crypto/DirectionalOptionSelling/trail_sl.py`
- **._strike_from_trading_symbol()** (5 connections) — `core/strategies/crypto/DirectionalOptionSelling/trail_sl.py`
- **._clear_trail_sl_retry()** (4 connections) — `core/strategies/crypto/DirectionalOptionSelling/trail_sl.py`
- **._find_main_sl_record()** (4 connections) — `core/strategies/crypto/DirectionalOptionSelling/trail_sl.py`
- **._queue_trail_sl_retry()** (4 connections) — `core/strategies/crypto/DirectionalOptionSelling/trail_sl.py`
- **Resolve (strike, option_type) for MAIN_SL clamp from meta/instrument.** (1 connections) — `core/strategies/crypto/DirectionalOptionSelling/trail_sl.py`
- **Update resting broker MAIN_SL stop_price to the latest SuperTrend trail level.…** (1 connections) — `core/strategies/crypto/DirectionalOptionSelling/trail_sl.py`
- **Modify broker SL to ``ref_st`` trail; update meta only on success.** (1 connections) — `core/strategies/crypto/DirectionalOptionSelling/trail_sl.py`
- **ST±100 broker trail levels, modify, and pending retry queue.** (1 connections) — `core/strategies/crypto/DirectionalOptionSelling/trail_sl.py`
- **Re-attempt broker trail modifies that failed after an ST move.** (1 connections) — `core/strategies/crypto/DirectionalOptionSelling/trail_sl.py`
- **Broker SL level. Bullish: ST − trail_points. Bearish: ST + trail_points. When…** (1 connections) — `core/strategies/crypto/DirectionalOptionSelling/trail_sl.py`
- **Parse strike from Delta symbols like ``P-BTC-64800-240726`` / ``C-ETH-...``.** (1 connections) — `core/strategies/crypto/DirectionalOptionSelling/trail_sl.py`

## Relationships

- [RunMode](RunMode.md) (4 shared connections)
- [symbol_config](symbol_config.md) (2 shared connections)
- [typing](typing.md) (1 shared connections)
- [DirectionalOptionSelling](DirectionalOptionSelling.md) (1 shared connections)
- [DosHtfMixin](DosHtfMixin.md) (1 shared connections)
- [IntentStore](IntentStore.md) (1 shared connections)
- [normalize_underlying](normalize_underlying.md) (1 shared connections)
- [.update_pending_sl_trigger](update_pending_sl_trigger.md) (1 shared connections)
- [DeltaBroker](DeltaBroker.md) (1 shared connections)
- [KotakSource](KotakSource.md) (1 shared connections)
- [Any](Any.md) (1 shared connections)

## Source Files

- `core/strategies/crypto/DirectionalOptionSelling/trail_sl.py`

## Audit Trail

- EXTRACTED: 41 (84%)
- INFERRED: 8 (16%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*