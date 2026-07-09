# RSI Bread & Butter (Delta crypto futures)

Registry: `STRATEGY_MAP["RSIBreadAndButter"]`  
Implementation: `RSIBreadAndButter.py`  
Engine job: `run/config.py` → `delta_rsi_bread_butter`

## Overview

Delta **BTCUSD** (and optional ETH) perpetual futures. Mean-reversion + structure: RSI(14) regular divergence near 70/30, BOS entry on signal timeframe, partial profit + structure trail.

## Evaluation

| Item | Value |
|------|-------|
| Eval mode | `live_feed` |
| Timeframe | `1` (1m bars; configurable via `signal_timeframe_minutes`) |
| Venue | `api = "DELTA"` |
| Mixins | `MarketStructureMixin`, `IndiaMktMixins` (shared helpers) |

## Rules

- **Signal:** RSI divergence in overbought/oversold zones (`RSI_OVERBOUGHT=70`, `RSI_OVERSOLD=30`).
- **Entry:** divergence + break of structure on same TF; signal valid up to `SIGNAL_MAX_AGE_BARS` bars.
- **Exit:** book **60%** at 1:1 target (`PARTIAL_BOOK_FRAC`); trail remainder on last swing; bracket tags `MAIN_SL` / `MAIN_TARGET`.
- **Risk cap:** `MAX_STOP_POINTS` from entry.

## Indicator bootstrap

```bash
python utils/delta/refresh_crypto_indicator_history.py --only 1
python utils/delta/refresh_crypto_indicator_history.py --only 5
```

Persists under `logs/indicators/` for live `IndicatorManager`.

## Run

```bash
python -m run.main --engine-id delta_rsi_bread_butter
```

## Logs

- `logs/RSIBreadAndButter_trades.csv`, `logs/RSIBreadAndButter_trade_log.csv`
- Indicator history per symbol/TF
