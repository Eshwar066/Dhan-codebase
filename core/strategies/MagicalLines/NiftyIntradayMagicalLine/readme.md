# Nifty Intraday Magical Line

Registry: `STRATEGY_MAP["NiftyIntradayMagicalLine"]`  
Implementation: `NiftyIntradayMagicalLine.py`  
Engine job: `run/config.py` → `dhan_nifty_intraday_magical` or `dhan_oi_positional_buy` (multi-strategy)

## Overview

NIFTY intraday options on 15m magical-line signals. Uses `IndiaMktMixins` for chain, expiry, and hedge patterns.

## Evaluation

| Item | Value |
|------|-------|
| Eval mode | `live_feed` |
| Timeframe | `15` |
| `should_evaluate` | Magical-line crossover / signal window |
| Exits | `should_exit` every closed 15m bar |
| Metadata | `nifty_intraday_magical_line` |

## Run

```bash
python -m run.main --engine-id dhan_nifty_intraday_magical
```

## Wiring

| Item | Location |
|------|----------|
| Parent readme | `MagicalLines/readme.md` |
| Profile | `run/strategy_profiles.py` |
