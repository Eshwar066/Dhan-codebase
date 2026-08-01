# Option Buildup

Registry: `STRATEGY_MAP["OptionBuildup"]`  
Implementation: `core/strategies/OpenIntrest/optionbuildup.py`  
Engine job: add to `ENGINE_JOBS` or multi-strategy engine as needed

## Overview

NIFTY option open-interest buildup scanner. Complements `OIPositionalBuy`; shares India options infrastructure (`IndiaMktMixins`).

## Evaluation

| Item | Value |
|------|-------|
| Eval mode | `live_feed` (default) |
| Timeframe | `15` (profile) |
| Venue | DHAN / NSE INDEX |

## Run

Wire an engine job with `"strategies": ["OptionBuildup"]` and run:

```bash
python -m run.main --engine-id <engine_id>
```

## Wiring

| Item | Location |
|------|----------|
| Profile | `run/strategy_profiles.py` → `OptionBuildup` |
| Runtime spec | `core/strategies/runtime_spec.py` |
| Related | `OpenIntrest/OIPostionalBuy/readme.md` |
