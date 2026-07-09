# Registry registration snippet

Copy into the three wiring files when adding a strategy. Replace `MyStrategy` / paths.

## 1. `core/strategies/registry.py`

```python
from core.strategies.path.MyStrategy import MyStrategy

STRATEGY_MAP["MyStrategy"] = {
    "strategy": MyStrategy,
    "instrument": "OPTION",  # OPTION | FUTURE | EQUITY
    "allowed_modes": [RunMode.BACKTEST, RunMode.PAPER, RunMode.LIVE],
}
```

Class **must** set `name = "MyStrategy"` (same as registry key).

## 2. `run/strategy_profiles.py`

```python
"MyStrategy": {
    "symbols": ["NIFTY"],
    "exchange": "NSE",
    "eval_mode": "live_feed",  # or "scheduled"
    "live": {"exchange": "INDEX", "sector": "YES"},
    "backtest": {
        "start_date": "2026-01-01",
        "end_date": "2026-02-01",
        "timeframe": "60",
        "exchange": "INDEX",
        "sector": "YES",
    },
},
```

Delta crypto: add `"delta": {"india": True, "testnet": False, "leverage": 5}` and `"exchange": "DELTA"` in live/backtest blocks.

## 3. `core/strategies/runtime_spec.py`

```python
"MyStrategy": {
    RunMode.BACKTEST: {"data": {"option_chain": {...}}},
    RunMode.PAPER: {"data": {"option_chain": {...}}},
    RunMode.LIVE: {"data": {"option_chain": {...}}},
},
```

Crypto / futures-only strategies may use `{"data": {}}` when data comes from `DeltaDataProvider` / `CandleService`.

## 4. `run/config.py` (optional engine)

```python
{
    "engine_id": "dhan_my_strategy",
    "venue": "DHAN",
    "enabled": False,
    "run_mode": "PAPER",
    "strategies": ["MyStrategy"],
},
```

## 5. Index entry

Add a row to `docs/STRATEGY_INDEX.md`.
