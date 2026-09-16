# DhanInstrumentStore

> 21 nodes

## Key Concepts

- **DhanInstrumentStore** (24 connections) — `core/utils/instruments/dhan.py`
- **.intent_creation_details()** (11 connections) — `core/utils/instruments/dhan.py`
- **._pick_option_row_for_expiry()** (9 connections) — `core/utils/instruments/dhan.py`
- **._resolve_option_row_fallback()** (9 connections) — `core/utils/instruments/dhan.py`
- **._sem_expiry_to_date()** (7 connections) — `core/utils/instruments/dhan.py`
- **.map_row_to_instrument()** (6 connections) — `core/utils/instruments/dhan.py`
- **Any** (5 connections)
- **.equity_intent_creation_details()** (4 connections) — `core/utils/instruments/dhan.py`
- **.futures_intent_creation_details()** (3 connections) — `core/utils/instruments/dhan.py`
- **._option_type_to_ce_pe()** (3 connections) — `core/utils/instruments/dhan.py`
- **_row_expiry()** (3 connections) — `core/utils/instruments/dhan.py`
- **._underlying_root_from_option_trading_symbol()** (3 connections) — `core/utils/instruments/dhan.py`
- **DataFrame** (3 connections)
- **.get_lot_size()** (2 connections) — `core/utils/instruments/dhan.py`
- **_same_month_year()** (2 connections) — `core/utils/instruments/dhan.py`
- **date** (1 connections)
- **Return lot size for symbol from instrument data (LOT_SIZE / SEM_LOT_UNITS);…** (1 connections) — `core/utils/instruments/dhan.py`
- **Resolve equity (cash) scrip to Instrument for order intent. Used by equity…** (1 connections) — `core/utils/instruments/dhan.py`
- **Narrow candidate rows to the intended calendar expiry (and monthly series when…** (1 connections) — `core/utils/instruments/dhan.py`
- **When SEM_TRADING_SYMBOL / SEM_CUSTOM_SYMBOL do not match…** (1 connections) — `core/utils/instruments/dhan.py`
- **Instrument store for Dhan: SEM_* columns, NSE/NFO/BSE mapping, backtest dummies.** (1 connections) — `core/utils/instruments/dhan.py`

## Relationships

- [Instrument](Instrument.md) (6 shared connections)
- [RunMode](RunMode.md) (5 shared connections)
- [._exchange_to_feed_segment](_exchange_to_feed_segment.md) (3 shared connections)
- [DhanInstrumentProvider](DhanInstrumentProvider.md) (2 shared connections)
- [normalize_dhan_tick_size](normalize_dhan_tick_size.md) (2 shared connections)
- [NiftyIntradayMagicalLine](NiftyIntradayMagicalLine.md) (2 shared connections)
- [InstrumentStore](InstrumentStore.md) (1 shared connections)
- [typing](typing.md) (1 shared connections)
- [.as_calendar_date](as_calendar_date.md) (1 shared connections)
- [.option_identity_key](option_identity_key.md) (1 shared connections)

## Source Files

- `core/utils/instruments/dhan.py`

## Audit Trail

- EXTRACTED: 58 (94%)
- INFERRED: 4 (6%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*