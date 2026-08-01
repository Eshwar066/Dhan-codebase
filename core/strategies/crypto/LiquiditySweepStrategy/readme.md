# Liquidity Sweep (Delta crypto futures)

Registry: `STRATEGY_MAP["LiquiditySweepStrategy"]`  
Implementation: `LiquiditySweepStrategy.py`, `gautham_liquidity_sweep.py`, `four_hour_liquidity.py`  

## Overview

Delta **BTCUSD** perpetual. **Gautham**: 4H liquidity zones swept on **1m**, then a 2-candle reversal entry.

## Candle source

| TF | Path |
|----|------|
| Entry `1` | `logs/indicators/{SYMBOL}/1/indicator_history.jsonl` (created once strategy subscribes) |
| Zones `4h` | `logs/indicators/{SYMBOL}/4h/indicator_history.jsonl` |

Live appends closed bars to these files. Backtest prefers indicator history when present; 4H zones sync as-of each 1m bar.

## Evaluation

| Item | Value |
|------|-------|
| Eval mode | `live_feed` |
| Primary TF | `1` (1m) |
| Extra TF | `4h` |
| Venue | `api = "DELTA"` |

## Rules (Gautham)

1. Closed **4H** bars update liquidity zones.
2. On **1m**, wick through a 4H zone and close back inside → arm SHORT/LONG.
3. Entry after the 2-candle reversal; max **2 SL hits per day** per symbol.
4. Partial book 50% at 1:1; trail on swings.

Toggle sides in `strategy.yaml` → `params` (applies to live + backtest):

| Param | Default | Meaning |
|-------|---------|---------|
| `enable_high_entries` | `true` | High-zone sweeps → SHORT |
| `enable_low_entries` | `true` | Low-zone sweeps → LONG |

Set `enable_low_entries: false` to run high/SHORT only.

## Liquidity zones file (backtest + live)

Rebuild walks **all** 4H history bars (no rolling window). Swept levels are dropped;
`liquidity_zones_active.json` keeps **only active** highs/lows.

**Backtest** rebuilds zones chronologically from `4h/indicator_history.jsonl` and does
**not** seed from `liquidity_zones_active.json` (that file is an end-state snapshot;
loading its `consumed` set would hide levels that were still active mid-window).

| File | Role |
|------|------|
| `logs/LiquiditySweepStrategy/liquidity_zones.jsonl` | Append-only rebuild/live log |
| `logs/LiquiditySweepStrategy/liquidity_zones_active.json` | Current unswept levels for live |

```bash
python -m core.strategies.crypto.LiquiditySweepStrategy.rebuild_liquidity_zones
```

## Indicator bootstrap

```bash
python utils/delta/refresh_crypto_indicator_history.py --only 4h
# 1m history is created/appended once the live strategy is subscribed to TF=1
```

## Run

```bash
# Rebuild zone reference from 4h history (also used by live)
python -m core.strategies.crypto.LiquiditySweepStrategy.rebuild_liquidity_zones

# 1m strategy backtest (engine job in run/config.py)
python -m run.main --engine-id delta_liquidity_sweep_bt
```
