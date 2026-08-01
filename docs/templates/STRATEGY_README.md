# Strategy Name

Registry: `STRATEGY_MAP["StrategyKey"]`  
Implementation: `path/to/StrategyClass.py`  
Engine job: `run/config.py` → `engine_id`

## Overview

One paragraph: what market, what edge, long/short, instrument type.

## Evaluation

| Item | Value |
|------|-------|
| Eval mode | `live_feed` (candle TF) or `scheduled` (`scheduled_times`) |
| Timeframe | e.g. `60`, `15`, `5`, or `None` for scheduled |
| `should_evaluate` | When **entries** are allowed (live_feed only) |
| Exits | `should_exit` / `on_position_exit` — run **every closed bar** before entries |
| Rollover | `on_candle_rollover` — same pass as exits |

## Entry / exit rules

- Entry conditions (signals, premium bands, OI patterns, …)
- Exit conditions (RSI cross, SL-M, time slot, …)
- Optional: hedge, rollover (`on_candle_rollover`)

## Execution

| Item | Value |
|------|-------|
| Default | LIMIT / SL-M |
| Opt-in | `execution_mode: GTT` or `HYBRID_GTT` + `gtt_fallback` spec |
| Post-fill | `on_main_entry_filled` (SL/target), `on_main_exit_filled` |

## Expiry / strikes

- `expiryType`, rollover rules, strike step, premium band

## Run

```bash
python -m run.main --engine-id your_engine_id
```

## Wiring

| Item | Location |
|------|----------|
| Strategy class | `...` |
| Registry | `core/strategies/registry.py` |
| Runtime spec | `core/strategies/runtime_spec.py` |
| Mixins | `IndiaMktMixins`, `MarketStructureMixin`, … |

## Backtest data

Where historical data comes from (DHAN CSVs, Delta candles, Yahoo bootstrap, …).

## Known doc/code gaps

List anything intentionally not implemented yet.
