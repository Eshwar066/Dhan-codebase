# Signal Flood Test

Registry: `STRATEGY_MAP["SignalFloodTest"]`  
Implementation: `core/strategies/PipelineTest/signal_flood_test.py`  
Engine jobs: `dhan_test_pipeline`, `delta_test_pipeline`

## Overview

Pipeline stress test — emits rapid ENTRY intents to validate OMS, risk, and fill paths. **Not** a production strategy.

## Evaluation

| Item | Value |
|------|-------|
| Modes | `PAPER`, `LIVE` only (no backtest in registry) |
| Purpose | Latency / queue / order-state validation |

## Run

```bash
python -m run.main --engine-id dhan_test_pipeline
python -m run.main --engine-id delta_test_pipeline
```

## Wiring

| Item | Location |
|------|----------|
| Profile | `run/strategy_profiles.py` → `SignalFloodTest` |
