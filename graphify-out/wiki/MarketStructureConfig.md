# MarketStructureConfig

> 26 nodes

## Key Concepts

- **MarketStructureConfig** (20 connections) — `core/utils/structure/pipeline.py`
- **add_market_structure()** (19 connections) — `core/utils/structure/pipeline.py`
- **MarketStructureMixin** (14 connections) — `core/strategies/market_structure_mixin.py`
- **market_structure_column_names()** (12 connections) — `core/utils/structure/pipeline.py`
- **market_structure_mixin.py** (10 connections) — `core/strategies/market_structure_mixin.py`
- **structure_signature()** (8 connections) — `core/utils/structure/pipeline.py`
- **.market_structure_config()** (6 connections) — `core/strategies/market_structure_mixin.py`
- **prepare_market_structure()** (5 connections) — `core/strategies/indicator_helpers.py`
- **.prepare_indicators()** (4 connections) — `core/strategies/market_structure_mixin.py`
- **default_persisted_keys_for_market_structure()** (3 connections) — `core/strategies/indicator_helpers.py`
- **shared_signature_for_market_structure()** (3 connections) — `core/strategies/indicator_helpers.py`
- **.persisted_indicator_keys()** (3 connections) — `core/strategies/market_structure_mixin.py`
- **.shared_indicator_signature()** (3 connections) — `core/strategies/market_structure_mixin.py`
- **.get_structure_lookback()** (2 connections) — `core/strategies/market_structure_mixin.py`
- **.liquidity_config()** (2 connections) — `core/utils/structure/pipeline.py`
- **Any** (1 connections)
- **Any** (1 connections)
- **Alias for ``add_market_structure`` — use inside ``prepare_indicators``.** (1 connections) — `core/strategies/indicator_helpers.py`
- **Opt-in mixin: market structure columns on every enriched candle (live +…** (1 connections) — `core/strategies/market_structure_mixin.py`
- **Add SMC-style features via ``prepare_indicators`` when enabled.** (1 connections) — `core/strategies/market_structure_mixin.py`
- **Override for custom swing/FVG/BOS/liquidity parameters.** (1 connections) — `core/strategies/market_structure_mixin.py`
- **Bars of OHLC history ``IndicatorManager`` should retain.** (1 connections) — `core/strategies/market_structure_mixin.py`
- **Full SMC-style feature pass on OHLCV dataframe. Safe to call from…** (1 connections) — `core/utils/structure/pipeline.py`
- **Stable cache key for ``IndicatorManager.shared_indicator_signature``.** (1 connections) — `core/utils/structure/pipeline.py`
- **Tunable parameters for ``add_market_structure``.** (1 connections) — `core/utils/structure/pipeline.py`
- *... and 1 more nodes in this community*

## Relationships

- [structure/__init__.py](structure-__init__.py.md) (12 shared connections)
- [typing](typing.md) (8 shared connections)
- [test_structure.py](test_structure.py.md) (7 shared connections)
- [indicator_helpers.py](indicator_helpers.py.md) (7 shared connections)
- [liquidity.py](liquidity.py.md) (4 shared connections)
- [LiquiditySweepStrategy](LiquiditySweepStrategy.md) (2 shared connections)
- [RSIBreadAndButter](RSIBreadAndButter.md) (2 shared connections)
- [Any](Any.md) (1 shared connections)
- [RSI Bread & Butter (Delta crypto futures)](RSI_Bread_&_Butter_Delta_crypto_futures.md) (1 shared connections)
- [Strategy Name](Strategy_Name.md) (1 shared connections)
- [refresh_nifty_indicator_history.py](refresh_nifty_indicator_history.py.md) (1 shared connections)
- [fvg.py](fvg.py.md) (1 shared connections)

## Source Files

- `core/strategies/indicator_helpers.py`
- `core/strategies/market_structure_mixin.py`
- `core/utils/structure/pipeline.py`

## Audit Trail

- EXTRACTED: 83 (97%)
- INFERRED: 3 (3%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*