# Instrument Store

**Purpose:** Load and query the instrument master (symbols, strikes, expiries, lot sizes) for order building and symbol resolution.

## File

- **`instrument_store.py`**
  - **Instrument** – dataclass-like object: `trading_symbol`, `custom_symbol`, `exchange`, `segment`, `instrument_type`, `expiry`, `strike`, `option_type`, `lot_size`, etc. `contract_key` property for uniqueness.
  - **InstrumentStore** – loads CSV (e.g. `all_instrument{date}.csv` from Dependencies), provides:
    - `intent_creation_details(trading_symbol, exchange, expiry, option_type, strike)` → Instrument or None
    - Other lookup helpers as needed.

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
