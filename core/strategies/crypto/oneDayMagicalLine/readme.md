# One Day Magical Line (Delta crypto)

Registry: `STRATEGY_MAP["OneDayMagicalLine"]`  
Implementation: `core/strategies/crypto/oneDayMagicalLine.py`  
Engine job: `run/config.py` → `delta_oneday_magicalline`

## Overview

Delta **BTCUSD** daily magical-line style positional logic on hourly (or configured) bars. Uses structure mixins and Delta perpetual execution.

## Evaluation

| Item | Value |
|------|-------|
| Eval mode | `live_feed` |
| Timeframe | `60` (profile) |
| Venue | DELTA |
| Exits | Structure / magical-line exit hooks on closed bars |
| Metadata | `one_day_magical_line` (alias `one_day_ml1`) |

## Run

```bash
python -m run.main --engine-id delta_oneday_magicalline
```

## Wiring

| Item | Location |
|------|----------|
| Profile | `run/strategy_profiles.py` → `OneDayMagicalLine` |
| Runtime spec | `core/strategies/runtime_spec.py` (empty `data` — Delta candles) |
