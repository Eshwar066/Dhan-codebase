# Liquidity Sweep (Delta crypto futures)

Registry: `STRATEGY_MAP["LiquiditySweepStrategy"]`  
Implementation: `LiquiditySweepStrategy.py`, `gautham_liquidity_sweep.py`  
Engine job: add `ENGINE_JOBS` entry or run via backtest config

## Overview

Delta **BTCUSD** / **ETHUSD** perpetuals. Parent strategy hosts sub-strategies; first sub-strategy is **Gautham**: PDH/PDL liquidity sweep + 3-candle reversal on 1m. Brackets with 50% partial at 1:1 and swing trail.

## Evaluation

| Item | Value |
|------|-------|
| Eval mode | `live_feed` |
| Timeframe | `1` (1m) |
| Venue | `api = "DELTA"` |
| `should_evaluate` | Sub-strategy gates (Gautham: sweep + reversal window) |
| Exits | `should_exit` / structure hooks every closed bar |

## Rules (Gautham)

- Track prior-day high/low sweeps on 1m bars.
- Entry after sweep + reversal pattern; max **2 SL hits per day** per symbol.
- Partial book 50% at 1:1; trail on swings; `MAIN_SL` / `MAIN_TARGET` brackets.

## Metadata

Legacy key: `liquidity_sweep` — see `core/strategies/meta.py`.

## Indicator bootstrap

```bash
python utils/delta/refresh_crypto_indicator_history.py --only 1
```

## Run

```bash
python -m run.main --engine-id <your_engine_id>
```

## Wiring

| Item | Location |
|------|----------|
| Registry | `core/strategies/registry.py` |
| Profile | `run/strategy_profiles.py` → `LiquiditySweepStrategy` |
| Runtime spec | `core/strategies/runtime_spec.py` |
| PDH/PDL helpers | `core/utils/structure/liquidity.py` |
