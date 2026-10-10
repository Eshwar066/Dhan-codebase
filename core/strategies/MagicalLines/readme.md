# Magical Lines (NIFTY option selling)

Registry: `STRATEGY_MAP["MagicalLines"]`  
Implementation: `MagicalLines.py`  
Engine job: `run/config.py` → `dhan_magicallines` (disabled by default)

## Overview

Quarterly **NIFTY** short options. The daily decision is the NSE **30-minute** bar that opens **15:15 IST** (the bar that contains 15:20). Candle colour is that bar's close versus the **09:15** session open.

## Evaluation

| Item | Value |
|------|-------|
| Eval mode | `live_feed` |
| Timeframe | `30` |
| API | Dhan option chain (`expiryType = QUARTERLY`) |

## Rules

- **Green day** (close > 09:15 open) → short PE. **Red day** → short CE.
- **Magical line:** put = spot − spot × 0.25%; call = spot + spot × 0.25%.
- **Main strike:** nearest 50-point strike to the magical line.
- **Hedge:** 500 points further OTM, **same quarterly expiry** as the main leg.
- **Spacing:** no new line while an open magical line sits inside ±3% of spot. After the first line, the next line is the same direction once spot has moved 3% beyond that first line and the 15:15 candle still matches (green → put, red → call).
- **Expiry exit:** flat from 7 calendar days before the position's quarterly expiry. No new entries in that week.
- **Next-day cross (15:15):** spot through the magical line by more than **0.2%** → exit and sell the opposite side. A close inside the 0.2% buffer is held until the next day.
- **30-minute stop:** spot **0.5% or more** through the magical line → exit immediately, no reverse.

## Related

- `NiftyIntradayMagicalLine` — intraday variant (`STRATEGY_MAP["NiftyIntradayMagicalLine"]`)

## Run

```bash
python -m run.main --engine-id dhan_magicallines
```

Enable the job in `run/config.py` first.
