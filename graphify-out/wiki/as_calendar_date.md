# .as_calendar_date

> 43 nodes

## Key Concepts

- **.as_calendar_date()** (15 connections) — `core/utils/expiry_resolver.py`
- **.dhan_expiry_index_to_date()** (15 connections) — `core/utils/expiry_resolver.py`
- **.is_calendar_expiry()** (10 connections) — `core/utils/expiry_resolver.py`
- **.current_month_expiry()** (9 connections) — `core/utils/expiry_resolver.py`
- **.next_month_expiry()** (9 connections) — `core/utils/expiry_resolver.py`
- **date** (9 connections)
- **.coerce_to_dhan_expiry_index()** (8 connections) — `core/utils/expiry_resolver.py`
- **.quarterly_target_expiry_date()** (8 connections) — `core/utils/expiry_resolver.py`
- **._derive_monthly_series()** (7 connections) — `core/utils/expiry_resolver.py`
- **.last_weekday_of_month()** (7 connections) — `core/utils/expiry_resolver.py`
- **.get_live_option_chain()** (6 connections) — `core/data/sources/dhan_source.py`
- **._resolve_main_expiry()** (6 connections) — `core/strategies/IBBM/Leaps/LeapsQuatery_RSI_52_32.py`
- **.leaps_rollover_target_expiry_date()** (6 connections) — `core/utils/expiry_resolver.py`
- **.resolve_hedge_expiry()** (5 connections) — `core/strategies/IBBM/Leaps/LeapsQuatery_RSI_52_32.py`
- **.resolve_hedge_expiry()** (5 connections) — `core/strategies/IndiaMktMixins.py`
- **.dhan_calendar_expiry_to_index()** (5 connections) — `core/utils/expiry_resolver.py`
- **.index_in_expiry_list()** (5 connections) — `core/utils/expiry_resolver.py`
- **.index_in_expiry_list_same_month()** (5 connections) — `core/utils/expiry_resolver.py`
- **.normalize_expiry_date()** (5 connections) — `core/utils/expiry_resolver.py`
- **.parse_compact_trading_symbol_expiry()** (5 connections) — `core/utils/expiry_resolver.py`
- **._parse_expiry_list()** (5 connections) — `core/utils/expiry_resolver.py`
- **.get_option_chain()** (4 connections) — `core/data/adapters/kotak_adapter.py`
- **._leaps_rollover_month_year()** (4 connections) — `core/utils/expiry_resolver.py`
- **Any** (4 connections)
- **.get_historical_option_chain()** (3 connections) — `core/data/adapters/dhan_adapter.py`
- *... and 18 more nodes in this community*

## Relationships

- [typing](typing.md) (19 shared connections)
- [main](main.md) (9 shared connections)
- [StrategyContext](StrategyContext.md) (6 shared connections)
- [IndiaMktMixins](IndiaMktMixins.md) (6 shared connections)
- [LeapsQuarterly](LeapsQuarterly.md) (5 shared connections)
- [MagicalLines](MagicalLines.md) (3 shared connections)
- [OIOptionChainMixin](OIOptionChainMixin.md) (3 shared connections)
- [NiftyIntradayMagicalLine](NiftyIntradayMagicalLine.md) (3 shared connections)
- [DhanSource](DhanSource.md) (2 shared connections)
- [NiftySMA9Weekly](NiftySMA9Weekly.md) (2 shared connections)
- [load_expired_option_chain_from_files](load_expired_option_chain_from_files.md) (2 shared connections)
- [kotak_data_provider.py](kotak_data_provider.py.md) (1 shared connections)

## Source Files

- `core/data/adapters/dhan_adapter.py`
- `core/data/adapters/kotak_adapter.py`
- `core/data/sources/dhan_source.py`
- `core/strategies/IBBM/Leaps/LeapsQuatery_RSI_52_32.py`
- `core/strategies/IndiaMktMixins.py`
- `core/strategies/MagicalLines/MagicalLines.py`
- `core/utils/expiry_resolver.py`

## Audit Trail

- EXTRACTED: 130 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*