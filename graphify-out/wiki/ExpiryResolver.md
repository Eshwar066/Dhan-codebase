# ExpiryResolver

> God node · 80 connections · `core/utils/expiry_resolver.py`

**Community:** [typing](typing.md)

## Connections by Relation

### contains
- expiry_resolver.py `EXTRACTED`

### imports
- live_engine.py `EXTRACTED`
- order_router.py `EXTRACTED`
- IndiaMktMixins.py `EXTRACTED`
- [roll_leaps_hedge.py](roll_leaps_hedge.py.md) `EXTRACTED`
- dhan_source.py `EXTRACTED`
- gtt_fallback_book.py `EXTRACTED`
- LeapsQuatery_RSI_52_32.py `EXTRACTED`
- position_manager.py `EXTRACTED`
- deltaMktMixins.py `EXTRACTED`
- NiftyDOS.py `EXTRACTED`
- dhan_live_order_placement.py `EXTRACTED`
- NiftySMA9Weekly.py `EXTRACTED`
- OIPosBuy.py `EXTRACTED`
- BankNiftyBTST.py `EXTRACTED`
- SuperTrendStockRider.py `EXTRACTED`
- NiftyIntradayMagicalLine.py `EXTRACTED`
- [kotak_data_provider.py](kotak_data_provider.py.md) `EXTRACTED`
- oi_option_chain.py `EXTRACTED`
- dhan.py `EXTRACTED`
- test_overnight_reconcile_symbol_map.py `EXTRACTED`
- *…and 3 more `imports` connection(s) not listed (lowest-degree first to go)*

### method
- .as_calendar_date() `EXTRACTED`
- .dhan_expiry_index_to_date() `EXTRACTED`
- .build_option_symbol() `EXTRACTED`
- .option_identity_key() `EXTRACTED`
- .resolve() `EXTRACTED`
- .current_weekly_expiry() `EXTRACTED`
- .is_calendar_expiry() `EXTRACTED`
- .current_month_expiry() `EXTRACTED`
- .next_weekly_expiry() `EXTRACTED`
- .next_month_expiry() `EXTRACTED`
- .quarterly_target_expiry_date() `EXTRACTED`
- .coerce_to_dhan_expiry_index() `EXTRACTED`
- .last_weekday_of_month() `EXTRACTED`
- ._derive_monthly_series() `EXTRACTED`
- .parse_dhan_space_option_symbol() `EXTRACTED`
- .leaps_rollover_target_expiry_date() `EXTRACTED`
- .normalize_expiry_date() `EXTRACTED`
- .normalize_option_side_compact() `EXTRACTED`
- .build_dhan_compact_option_symbol() `EXTRACTED`
- .parse_compact_trading_symbol_expiry() `EXTRACTED`
- *…and 12 more `method` connection(s) not listed (lowest-degree first to go)*

### rationale_for
- Resolves expiry for: - NSE historical (exact expiry date) - DHAN option chain… `EXTRACTED`

### references
- 4. Shared India options — `IndiaMktMixins` `INFERRED`
- Anti-patterns to avoid `INFERRED`

### uses
- [LiveEngine](LiveEngine.md) `INFERRED`
- [OrderRouter](OrderRouter.md) `INFERRED`
- [IndiaMktMixins](IndiaMktMixins.md) `INFERRED`
- [NiftyDOS](NiftyDOS.md) `INFERRED`
- [PositionManager](PositionManager.md) `INFERRED`
- [GttFallbackBook](GttFallbackBook.md) `INFERRED`
- [DhanSource](DhanSource.md) `INFERRED`
- [OIPositionalBuy](OIPositionalBuy.md) `INFERRED`
- [BankNiftyBTST](BankNiftyBTST.md) `INFERRED`
- [LeapsQuarterly](LeapsQuarterly.md) `INFERRED`
- [OIOptionChainMixin](OIOptionChainMixin.md) `INFERRED`
- [NiftySMA9Weekly](NiftySMA9Weekly.md) `INFERRED`
- [NiftyIntradayMagicalLine](NiftyIntradayMagicalLine.md) `INFERRED`
- [DhanInstrumentStore](DhanInstrumentStore.md) `INFERRED`
- [MagicalLines](MagicalLines.md) `INFERRED`
- main() `INFERRED`
- [KotakDataProvider](KotakDataProvider.md) `INFERRED`
- KotakAdapter `INFERRED`
- DhanAdapter `INFERRED`
- TestOvernightReconcileSymbolMap `INFERRED`
- *…and 1 more `uses` connection(s) not listed (lowest-degree first to go)*

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*