# Data Layer

**Purpose:** All market data that feeds the engines lives here. Pro-level separation from order placement.

## What goes here

- **LTP / OHLC:** `get_latest_candles`, `get_intraday`
- **Option chain:** live and historical (`get_live_option_chain`, `get_expired_optionchain`, `get_nse_optionchain_historical`)
- **Expiries:** `get_live_expiry`, `get_nse_expiries`

Engines and `OptionChainService` depend only on `IDataProvider`. They never call broker-specific APIs directly. Data sources (e.g. `DhanSource`) use **core/library/dhan_tradehull.py** for Dhan API; see `core/library/README.md`.

## Files

| File | Role |
|------|------|
| `base.py` | `IDataProvider` abstract interface |
| `dhan_data_provider.py` | `DhanDataProvider` – wraps `DhanSource`, data methods only (no `place_order`) |
| `__init__.py` | Exports `IDataProvider`, `DhanDataProvider` |

## Usage

```python
from core.data.sources.dhan_source import DhanSource
from core.data.datalayer import DhanDataProvider

source = DhanSource()  # uses core.library.dhan_tradehull.Tradehull
data_provider = DhanDataProvider(source)
# Pass data_provider to BacktestEngine / LiveEngine and CandleService
```

Order placement is **not** in this layer; it is in the **broker** layer (`core/broker/`).
