# Instrument Store

**Purpose:** Load and query the instrument master (symbols, strikes, expiries, lot sizes) for order building and symbol resolution.

## Layout (broker-specific)

- **`base.py`** – **Instrument** (shared), **BaseInstrumentStore** (abstract: `intent_creation_details`, `futures_intent_creation_details`).
- **`dhan.py`** – **DhanInstrumentProvider** (CSV), **DhanInstrumentStore** (SEM_*, NSE/NFO/BSE, backtest dummies).
- **`delta.py`** – **DeltaInstrumentProvider** (Delta `/v2/products`), **DeltaInstrumentStore** (product id/symbol, Delta dummies).
- **`instrument_store.py`** – Facade: **Instrument**, **InstrumentStore(broker=..., csv_path=..., base_url=...)** → Dhan or Delta store.
- **`providers.py`** – **fetch_delta_products**, **get_provider_for_path** (Dhan CSV vs Delta fallback).

Use **InstrumentStore(csv_path=path)** for Dhan or **InstrumentStore(broker="DELTA")** for Delta; same interface for `intent_creation_details` and `futures_intent_creation_details`.

## CSV columns (Dhan / project convention)

| Canonical field   | CSV column                 |
|-------------------|----------------------------|
| exchange          | SEM_EXM_EXCH_ID            |
| segment           | SEM_SEGMENT                |
| instrument_id     | SEM_SMST_SECURITY_ID       |
| trading_symbol    | SEM_TRADING_SYMBOL         |
| custom_symbol     | SEM_CUSTOM_SYMBOL          |
| symbol            | SM_SYMBOL_NAME             |
| instrument_type   | SEM_EXCH_INSTRUMENT_TYPE   |
| option_type       | SEM_OPTION_TYPE            |
| strike            | SEM_STRIKE_PRICE           |
| expiry            | SEM_EXPIRY_DATE            |
| lot_size          | SEM_LOT_UNITS              |
| tick_size         | SEM_TICK_SIZE              |
| series            | SEM_SERIES                 |

Instrument file is typically the same as used by **core/library/dhan_tradehull.py** (from Dependencies/).
