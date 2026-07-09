# Futures EMA Momentum (Delta)

Registry: `STRATEGY_MAP["Futures_EMA_Momentum"]`  
Implementation: `Futures_EMA_Momentum.py`  
Engine job: `run/config.py` → `delta_futures_ema_momentum`

## Overview

Delta crypto futures momentum strategy using EMA high/low bands. Distinct from `FuturesEMAHighLow` (NIFTY index futures on DHAN).

## Evaluation

| Item | Value |
|------|-------|
| Eval mode | `live_feed` |
| Timeframe | `60` (profile default) |
| Venue | DELTA (`delta` block in profile) |
| Exits | Per `should_exit` on closed bars |

## Run

```bash
python -m run.main --engine-id delta_futures_ema_momentum
```

## Wiring

| Item | Location |
|------|----------|
| Registry key | `Futures_EMA_Momentum` |
| Class `name` | `Futures_EMA_Momentum` |
| Profile | `run/strategy_profiles.py` |
