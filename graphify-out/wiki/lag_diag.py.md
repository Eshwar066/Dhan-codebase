# lag_diag.py

> 20 nodes

## Key Concepts

- **lag_diag.py** (17 connections) — `core/utils/lag_diag.py`
- **lag_diag_enabled()** (7 connections) — `core/utils/lag_diag.py`
- **ws_tick_diag_enabled()** (6 connections) — `core/utils/lag_diag.py`
- **ws_tick_should_drop_stale()** (6 connections) — `core/utils/lag_diag.py`
- **parse_tick_exchange_time_from_message()** (5 connections) — `core/utils/lag_diag.py`
- **parse_tick_time_value()** (5 connections) — `core/utils/lag_diag.py`
- **print_data_check()** (5 connections) — `core/utils/lag_diag.py`
- **print_ws_tick_vs_now()** (5 connections) — `core/utils/lag_diag.py`
- **.build_context()** (3 connections) — `core/engine/base_engine.py`
- **ws_max_tick_lag_sec()** (3 connections) — `core/utils/lag_diag.py`
- **datetime** (3 connections)
- **Any** (1 connections)
- **Optional lag diagnostics (see repo ``cursor.md``). Enable with environment…** (1 connections) — `core/utils/lag_diag.py`
- **Max allowed lag (exchange tick time → UTC now) before dropping a WS tick. Unset…** (1 connections) — `core/utils/lag_diag.py`
- **Parse exchange time: int/float epoch or microseconds, or ISO string (cursor.md).** (1 connections) — `core/utils/lag_diag.py`
- **Best-effort exchange time from Delta-style ticker/candle WS payload.** (1 connections) — `core/utils/lag_diag.py`
- **If ``ALGO_WS_MAX_TICK_LAG_SEC`` is set, drop ticks older than that many seconds…** (1 connections) — `core/utils/lag_diag.py`
- **Tick-time vs IST prints (WebSocket); on if LAG_DIAG or WS_TICK_DIAG is set.** (1 connections) — `core/utils/lag_diag.py`
- **Step 1: verify data delay (exchange → you) before strategy runs.…** (1 connections) — `core/utils/lag_diag.py`
- **Inside WebSocket handler (raw ticker dict): compare exchange time vs wall…** (1 connections) — `core/utils/lag_diag.py`

## Relationships

- [typing](typing.md) (5 shared connections)
- [logging.py](logging.py.md) (5 shared connections)
- [factory.py](factory.py.md) (4 shared connections)
- [Any](Any.md) (3 shared connections)
- [StrategyContext](StrategyContext.md) (1 shared connections)
- [OneDayMagicalLine](OneDayMagicalLine.md) (1 shared connections)
- [BTCZeroDTE](BTCZeroDTE.md) (1 shared connections)

## Source Files

- `core/engine/base_engine.py`
- `core/utils/lag_diag.py`

## Audit Trail

- EXTRACTED: 47 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*