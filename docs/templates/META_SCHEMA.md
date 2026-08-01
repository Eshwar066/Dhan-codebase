# Strategy metadata schema

Use `core/strategies/meta.py` for all new strategies. Legacy snake_case keys remain readable.

## Canonical shape

```python
from core.strategies.meta import pack_strategy_meta, unpack_strategy_meta

metadata_extras = {
    **pack_strategy_meta("MyStrategy", {
        "symbol": "NIFTY",
        "side": "SELL",
        "entry_price": 100.0,
        # strategy-specific fields...
    }),
    "execution_mode": "HYBRID_GTT",  # top-level execution hints stay outside strategy_meta
}
```

Persisted / fill hooks receive the same dict on `metadata_extras`.

## Read path

```python
from core.strategies.meta import unpack_strategy_meta, underlying_from_metadata

payload = unpack_strategy_meta(intent.metadata_extras, registry_key="MyStrategy")
symbol = underlying_from_metadata(intent.metadata_extras)
```

## Legacy keys (read-only compatibility)

| Registry key | Legacy `metadata_extras` key |
|--------------|------------------------------|
| `RSIBreadAndButter` | `rsi_bread_butter` |
| `LiquiditySweepStrategy` | `liquidity_sweep` |
| `OIPositionalBuy` | `oi_positional_buy` |
| `BankNiftyBTST` | `banknifty_btst` |
| `NiftyIntradayMagicalLine` | `nifty_intraday_magical_line` |
| `OneDayMagicalLine` | `one_day_magical_line` (+ alias `one_day_ml1`) |

`LiveEngine._underlying_from_strategy_meta` delegates to `underlying_from_metadata`.

## Required fields

| Field | Purpose |
|-------|---------|
| `symbol` | Underlying for fill hooks / logging |
| `side` | `BUY` / `SELL` (MAIN leg) |
| `entry_price` | Reference entry for risk / partials |

Add strategy-specific fields inside the payload; document them in the strategy readme.
