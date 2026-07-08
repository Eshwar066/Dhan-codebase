# Magical Lines (NIFTY option selling)

Registry: `STRATEGY_MAP["MagicalLines"]`  
Implementation: `MagicalLines.py`  
Engine job: `run/config.py` → `dhan_magicallines` (disabled by default)

## Overview

Time-anchored **3:20 PM IST** option selling on NIFTY. Intraday candle color (9:15–15:20) sets direction; magical line levels drive strike selection and reversals.

## Evaluation

| Item | Value |
|------|-------|
| Eval mode | `live_feed` with `valid_times = {"15:20"}` |
| Timeframe | `60` |
| API | NSE option chain via `required_context = ["option_chain"]` |

## Rules

- **Green day** → short PE; **red day** → short CE.
- **Magical line:** MLG = spot × 0.9975 (green), MLR = spot × 1.0025 (red).
- **Main leg:** 100-point strikes, premium **200–400** (`TARGET_PREMIUM_MIN/MAX`).
- **Hedge:** within 500 points of main, net credit **90–120**.
- **Expiry:** monthly; after **13th** → next month series; rollover **one week before** expiry (Wednesday).
- **Reversal:** at 15:20 if price closes opposite magical line → exit and reverse.
- **Pyramid:** up to 3 levels when price moves 2% from first line (`MAX_MAGICAL_LEVELS`).

## Related

- `NiftyIntradayMagicalLine` — intraday variant (`STRATEGY_MAP["NiftyIntradayMagicalLine"]`)

## Run

```bash
python -m run.main --engine-id dhan_magicallines
```

Enable the job in `run/config.py` first.
