# IndiaMktMixins

> God node · 118 connections · `core/strategies/IndiaMktMixins.py`

**Community:** [IndiaMktMixins](IndiaMktMixins.md)

## Connections by Relation

### contains
- IndiaMktMixins.py `EXTRACTED`

### imports
- DirectionalOptionSelling.py `EXTRACTED`
- LiquiditySweepStrategy.py `EXTRACTED`
- LeapsQuatery_RSI_52_32.py `EXTRACTED`
- RSIBreadAndButter.py `EXTRACTED`
- NiftyDOS.py `EXTRACTED`
- NiftySMA9Weekly.py `EXTRACTED`
- OIPosBuy.py `EXTRACTED`
- BankNiftyBTST.py `EXTRACTED`
- oneDayMagicalLine.py `EXTRACTED`
- BTCZeroDTEElevenPM.py `EXTRACTED`
- BTCZeroDTE.py `EXTRACTED`
- SuperTrendStockRider.py `EXTRACTED`
- NiftyIntradayMagicalLine.py `EXTRACTED`
- Futures_EMA.py `EXTRACTED`
- MagicalLines.py `EXTRACTED`
- IPOBreakout.py `EXTRACTED`
- Futures_EMA_Momentum.py `EXTRACTED`
- signal_flood_test.py `EXTRACTED`
- optionbuildup.py `EXTRACTED`
- Leaps/__init__.py `EXTRACTED`

### inherits
- [DirectionalOptionSelling](DirectionalOptionSelling.md) `EXTRACTED`
- [NiftyDOS](NiftyDOS.md) `EXTRACTED`
- [LiquiditySweepStrategy](LiquiditySweepStrategy.md) `EXTRACTED`
- [OIPositionalBuy](OIPositionalBuy.md) `EXTRACTED`
- [BankNiftyBTST](BankNiftyBTST.md) `EXTRACTED`
- [LeapsQuarterly](LeapsQuarterly.md) `EXTRACTED`
- [RSIBreadAndButter](RSIBreadAndButter.md) `EXTRACTED`
- [OneDayMagicalLine](OneDayMagicalLine.md) `EXTRACTED`
- [BTCZeroDTEElevenPM](BTCZeroDTEElevenPM.md) `EXTRACTED`
- [BTCZeroDTE](BTCZeroDTE.md) `EXTRACTED`
- [NiftySMA9Weekly](NiftySMA9Weekly.md) `EXTRACTED`
- [NiftyIntradayMagicalLine](NiftyIntradayMagicalLine.md) `EXTRACTED`
- [SuperTrendStockRider](SuperTrendStockRider.md) `EXTRACTED`
- [MagicalLines](MagicalLines.md) `EXTRACTED`
- FuturesEMAHighLow `EXTRACTED`
- [FuturesEMAMomentum](FuturesEMAMomentum.md) `EXTRACTED`
- [OptionBuildup](OptionBuildup.md) `EXTRACTED`
- [IPOBreakout](IPOBreakout.md) `EXTRACTED`
- [SignalFloodTestStrategy](SignalFloodTestStrategy.md) `EXTRACTED`

### method
- .find_strike_in_premium_range() `EXTRACTED`
- .get_option_price_at_candle() `EXTRACTED`
- ._append_computed_delta_to_chain_df() `EXTRACTED`
- .get_option_chain_snapshot() `EXTRACTED`
- .map_instrument_to_intent() `EXTRACTED`
- .create_hedge_intent() `EXTRACTED`
- ._expiry_calendar_to_utc_naive_close() `EXTRACTED`
- ._years_to_expiry_bs() `EXTRACTED`
- ._coerce_backtest_option_chain_df() `EXTRACTED`
- ._resolve_option_chain_data() `EXTRACTED`
- ._option_price_from_resolved_chain() `EXTRACTED`
- ._option_chain_premium_column() `EXTRACTED`
- ._entry_order_qty() `EXTRACTED`
- ._selected_expiry_calendar_date() `EXTRACTED`
- ._option_chain_df() `EXTRACTED`
- ._strike_row_from_chain() `EXTRACTED`
- ._execution_price_from_chain_row() `EXTRACTED`
- ._ltp_from_strike_row_backtest() `EXTRACTED`
- .resolve_hedge_expiry() `EXTRACTED`
- .resolve_hedge_entry_price() `EXTRACTED`
- *…and 45 more `method` connection(s) not listed (lowest-degree first to go)*

### rationale_for
- Reusable India market broker logic for option-selling strategies: - Option… `EXTRACTED`

### references
- 1. Strategy Layer `INFERRED`
- Evaluation `INFERRED`
- Overview `INFERRED`
- 4. Shared India options — `IndiaMktMixins` `INFERRED`
- Checklist: new strategy in 30 minutes `INFERRED`
- Wiring `INFERRED`
- Eval `INFERRED`
- Overview `INFERRED`

### uses
- [ExpiryResolver](ExpiryResolver.md) `INFERRED`
- [RunMode](RunMode.md) `INFERRED`
- SessionManager `INFERRED`
- OrderIntent `INFERRED`

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*