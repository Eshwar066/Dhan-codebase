# SuperTrendStockRider

> 23 nodes

## Key Concepts

- **SuperTrendStockRider** (25 connections) — `core/strategies/Equity/SuperTrendStockRider/SuperTrendStockRider.py`
- **._is_check_time()** (4 connections) — `core/strategies/Equity/SuperTrendStockRider/SuperTrendStockRider.py`
- **.prepare_indicators()** (4 connections) — `core/strategies/Equity/SuperTrendStockRider/SuperTrendStockRider.py`
- **.should_evaluate()** (4 connections) — `core/strategies/Equity/SuperTrendStockRider/SuperTrendStockRider.py`
- **.__init__()** (3 connections) — `core/strategies/Equity/SuperTrendStockRider/SuperTrendStockRider.py`
- **.on_structure_exit()** (3 connections) — `core/strategies/Equity/SuperTrendStockRider/SuperTrendStockRider.py`
- **.should_exit()** (3 connections) — `core/strategies/Equity/SuperTrendStockRider/SuperTrendStockRider.py`
- **._get_lot_size()** (2 connections) — `core/strategies/Equity/SuperTrendStockRider/SuperTrendStockRider.py`
- **.on_candle_rollover()** (2 connections) — `core/strategies/Equity/SuperTrendStockRider/SuperTrendStockRider.py`
- **.on_position_exit()** (2 connections) — `core/strategies/Equity/SuperTrendStockRider/SuperTrendStockRider.py`
- **.get_warmup_period()** (1 connections) — `core/strategies/Equity/SuperTrendStockRider/SuperTrendStockRider.py`
- **.persisted_indicator_keys()** (1 connections) — `core/strategies/Equity/SuperTrendStockRider/SuperTrendStockRider.py`
- **DataFrame** (1 connections)
- **Check if it's 15:15 PM (daily evaluation time).** (1 connections) — `core/strategies/Equity/SuperTrendStockRider/SuperTrendStockRider.py`
- **Evaluate on daily candles - in backtest mode evaluate all, in live only at…** (1 connections) — `core/strategies/Equity/SuperTrendStockRider/SuperTrendStockRider.py`
- **Get lot size for equity instruments (always 1 for stocks).** (1 connections) — `core/strategies/Equity/SuperTrendStockRider/SuperTrendStockRider.py`
- **Required by backtest engine - when position structure exits.** (1 connections) — `core/strategies/Equity/SuperTrendStockRider/SuperTrendStockRider.py`
- **Required by backtest engine - called on candle rollover.** (1 connections) — `core/strategies/Equity/SuperTrendStockRider/SuperTrendStockRider.py`
- **Required by backtest engine - called when position structure exits.** (1 connections) — `core/strategies/Equity/SuperTrendStockRider/SuperTrendStockRider.py`
- **Check if position should be exited.** (1 connections) — `core/strategies/Equity/SuperTrendStockRider/SuperTrendStockRider.py`
- **Generate exit intents for position.** (1 connections) — `core/strategies/Equity/SuperTrendStockRider/SuperTrendStockRider.py`
- **Supertrend-based equity swing with trailing stop at entry candle low.** (1 connections) — `core/strategies/Equity/SuperTrendStockRider/SuperTrendStockRider.py`
- **Compute Supertrend(16, 1.7).** (1 connections) — `core/strategies/Equity/SuperTrendStockRider/SuperTrendStockRider.py`

## Relationships

- [.on_candle](on_candle.md) (10 shared connections)
- [typing](typing.md) (3 shared connections)
- [IndiaMktMixins](IndiaMktMixins.md) (1 shared connections)
- [Strategy index](Strategy_index.md) (1 shared connections)
- [RunMode](RunMode.md) (1 shared connections)
- [indicator_helpers.py](indicator_helpers.py.md) (1 shared connections)

## Source Files

- `core/strategies/Equity/SuperTrendStockRider/SuperTrendStockRider.py`

## Audit Trail

- EXTRACTED: 38 (93%)
- INFERRED: 3 (7%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*