# main

> 29 nodes

## Key Concepts

- **main()** (20 connections) — `core/strategies/IBBM/NiftyDOS/emergency/dhan_live_order_placement.py`
- **.resolve()** (13 connections) — `core/utils/expiry_resolver.py`
- **.current_weekly_expiry()** (12 connections) — `core/utils/expiry_resolver.py`
- **._resolve_main_expiry()** (9 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`
- **.next_weekly_expiry()** (9 connections) — `core/utils/expiry_resolver.py`
- **.resolve_hedge_expiry()** (4 connections) — `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`
- **calculate_hedge_strike()** (3 connections) — `core/strategies/IBBM/NiftyDOS/emergency/dhan_live_order_placement.py`
- **calculate_margin_dhan()** (3 connections) — `core/strategies/IBBM/NiftyDOS/emergency/dhan_live_order_placement.py`
- **fetch_live_spot()** (3 connections) — `core/strategies/IBBM/NiftyDOS/emergency/dhan_live_order_placement.py`
- **find_strike_in_premium_range()** (3 connections) — `core/strategies/IBBM/NiftyDOS/emergency/dhan_live_order_placement.py`
- **get_option_chain_dhan()** (3 connections) — `core/strategies/IBBM/NiftyDOS/emergency/dhan_live_order_placement.py`
- **get_trading_symbol_from_instrument_df()** (3 connections) — `core/strategies/IBBM/NiftyDOS/emergency/dhan_live_order_placement.py`
- **load_dhan_credentials()** (3 connections) — `core/strategies/IBBM/NiftyDOS/emergency/dhan_live_order_placement.py`
- **parse_dhan_chain()** (3 connections) — `core/strategies/IBBM/NiftyDOS/emergency/dhan_live_order_placement.py`
- **place_order_dhan()** (3 connections) — `core/strategies/IBBM/NiftyDOS/emergency/dhan_live_order_placement.py`
- **save_chain_snapshot()** (3 connections) — `core/strategies/IBBM/NiftyDOS/emergency/dhan_live_order_placement.py`
- **Parse Dhan option chain to extract strikes and premiums.** (1 connections) — `core/strategies/IBBM/NiftyDOS/emergency/dhan_live_order_placement.py`
- **Find OTM strike with premium in range, closest to ATM.** (1 connections) — `core/strategies/IBBM/NiftyDOS/emergency/dhan_live_order_placement.py`
- **Calculate hedge strike (500 points OTM from MAIN), ensuring it's a valid strike.** (1 connections) — `core/strategies/IBBM/NiftyDOS/emergency/dhan_live_order_placement.py`
- **Save option chain snapshot to logs directory.** (1 connections) — `core/strategies/IBBM/NiftyDOS/emergency/dhan_live_order_placement.py`
- **Get trading symbol from instrument dataframe.** (1 connections) — `core/strategies/IBBM/NiftyDOS/emergency/dhan_live_order_placement.py`
- **Calculate margin using Dhan's margin_calculator_multi API.** (1 connections) — `core/strategies/IBBM/NiftyDOS/emergency/dhan_live_order_placement.py`
- **Place order using Dhan API.** (1 connections) — `core/strategies/IBBM/NiftyDOS/emergency/dhan_live_order_placement.py`
- **Load Dhan credentials from env or config file.** (1 connections) — `core/strategies/IBBM/NiftyDOS/emergency/dhan_live_order_placement.py`
- **Fetch live NIFTY spot from Dhan using ticker_data.** (1 connections) — `core/strategies/IBBM/NiftyDOS/emergency/dhan_live_order_placement.py`
- *... and 4 more nodes in this community*

## Relationships

- [typing](typing.md) (15 shared connections)
- [.as_calendar_date](as_calendar_date.md) (9 shared connections)
- [NiftySMA9Weekly](NiftySMA9Weekly.md) (6 shared connections)
- [._attempt_sl_reentry](_attempt_sl_reentry.md) (5 shared connections)
- [indicator_helpers.py](indicator_helpers.py.md) (2 shared connections)
- [NiftyDOS](NiftyDOS.md) (2 shared connections)
- [IndiaMktMixins](IndiaMktMixins.md) (2 shared connections)
- [Tradehull](Tradehull.md) (1 shared connections)
- [DhanContext](DhanContext.md) (1 shared connections)
- [._check_eod_exit](_check_eod_exit.md) (1 shared connections)
- [test_structure.py](test_structure.py.md) (1 shared connections)
- [._select_expiry_month](_select_expiry_month.md) (1 shared connections)

## Source Files

- `core/strategies/IBBM/NiftyDOS/NiftyDOS.py`
- `core/strategies/IBBM/NiftyDOS/emergency/dhan_live_order_placement.py`
- `core/utils/expiry_resolver.py`

## Audit Trail

- EXTRACTED: 72 (92%)
- INFERRED: 6 (8%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*