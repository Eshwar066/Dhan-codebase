# GauthamLiquiditySweep

> 22 nodes

## Key Concepts

- **GauthamLiquiditySweep** (31 connections) — `core/strategies/crypto/LiquiditySweepStrategy/gautham_liquidity_sweep.py`
- **LiquidityZone** (18 connections) — `core/strategies/crypto/LiquiditySweepStrategy/four_hour_liquidity.py`
- **.evaluate()** (11 connections) — `core/strategies/crypto/LiquiditySweepStrategy/gautham_liquidity_sweep.py`
- **_SymbolDayState** (8 connections) — `core/strategies/crypto/LiquiditySweepStrategy/gautham_liquidity_sweep.py`
- **GauthamEntrySignal** (6 connections) — `core/strategies/crypto/LiquiditySweepStrategy/gautham_liquidity_sweep.py`
- **._detect_sweep()** (6 connections) — `core/strategies/crypto/LiquiditySweepStrategy/gautham_liquidity_sweep.py`
- **.on_sl_hit()** (6 connections) — `core/strategies/crypto/LiquiditySweepStrategy/gautham_liquidity_sweep.py`
- **._arm_setup()** (5 connections) — `core/strategies/crypto/LiquiditySweepStrategy/gautham_liquidity_sweep.py`
- **._clear_setup()** (5 connections) — `core/strategies/crypto/LiquiditySweepStrategy/gautham_liquidity_sweep.py`
- **._roll_day()** (5 connections) — `core/strategies/crypto/LiquiditySweepStrategy/gautham_liquidity_sweep.py`
- **._signal_from_candle()** (5 connections) — `core/strategies/crypto/LiquiditySweepStrategy/gautham_liquidity_sweep.py`
- **._ist_date()** (4 connections) — `core/strategies/crypto/LiquiditySweepStrategy/gautham_liquidity_sweep.py`
- **._state()** (4 connections) — `core/strategies/crypto/LiquiditySweepStrategy/gautham_liquidity_sweep.py`
- **._trades_inside_zone()** (4 connections) — `core/strategies/crypto/LiquiditySweepStrategy/gautham_liquidity_sweep.py`
- **._bar_key()** (3 connections) — `core/strategies/crypto/LiquiditySweepStrategy/gautham_liquidity_sweep.py`
- **._allowed_zone_sources()** (2 connections) — `core/strategies/crypto/LiquiditySweepStrategy/gautham_liquidity_sweep.py`
- **._has_open_position()** (2 connections) — `core/strategies/crypto/LiquiditySweepStrategy/gautham_liquidity_sweep.py`
- **.__init__()** (2 connections) — `core/strategies/crypto/LiquiditySweepStrategy/gautham_liquidity_sweep.py`
- **date** (2 connections)
- **Reset sweep arm after SL; count toward daily SL budget.** (1 connections) — `core/strategies/crypto/LiquiditySweepStrategy/gautham_liquidity_sweep.py`
- **True when the entry-TF bar trades back inside the swept liquidity level. High…** (1 connections) — `core/strategies/crypto/LiquiditySweepStrategy/gautham_liquidity_sweep.py`
- **Sub-strategy: 4H zone sweep on 5m + inside-zone entry (SL = candle extreme).** (1 connections) — `core/strategies/crypto/LiquiditySweepStrategy/gautham_liquidity_sweep.py`

## Relationships

- [FourHourLiquidityBook](FourHourLiquidityBook.md) (8 shared connections)
- [_c](_c.md) (8 shared connections)
- [typing](typing.md) (7 shared connections)
- [LiquiditySweepStrategy](LiquiditySweepStrategy.md) (4 shared connections)
- [TestParentFourHourRouting](TestParentFourHourRouting.md) (3 shared connections)
- [._update_zones_after_append](_update_zones_after_append.md) (2 shared connections)
- [RunMode](RunMode.md) (2 shared connections)

## Source Files

- `core/strategies/crypto/LiquiditySweepStrategy/four_hour_liquidity.py`
- `core/strategies/crypto/LiquiditySweepStrategy/gautham_liquidity_sweep.py`

## Audit Trail

- EXTRACTED: 75 (90%)
- INFERRED: 8 (10%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*