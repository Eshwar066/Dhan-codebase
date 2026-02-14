# Core Library – Dhan Tradehull

This folder contains the **in-project** Dhan Tradehull implementation (`dhan_tradehull.py`) used for all Dhan API access.

## Usage in the project

- **Do not** import `Dhan_Tradehull` from an external package. Use:
  ```python
  from core.library.dhan_tradehull import Tradehull
  ```
- **For strategy and engine code:** use **DhanSource** (data + orders), **DhanDataProvider** (data only), and **DhanBrokerApi** / **DhanBroker** (orders only). They wrap Tradehull so that data feeding and order placement are consistent and configurable.

## Data feeding (engines)

| Need            | Use |
|-----------------|-----|
| Candles / intraday | `DhanSource.get_intraday()` or `DhanDataProvider.get_intraday()` |
| Latest OHLC/LTP | `DhanSource.get_latest_candles()` |
| LTP / quote     | `DhanSource.get_ltp_data()`, `get_quote_data()` |
| Expiry list     | `DhanSource.get_live_expiry()` |
| Live option chain | `DhanSource.get_live_option_chain(symbol, exchange, expiry_index, strikes)` |
| Historical option chain | `DhanSource.get_expired_optionchain(...)` or NSE `get_nse_optionchain_historical()` |
| ATM/OTM/ITM    | `DhanSource.get_atm_options()`, `get_otm_options()`, `get_itm_options()` |

## Order placement

| Need        | Use |
|-------------|-----|
| Place order | `DhanSource.place_order(...)` or **DhanBroker** (via OrderRouter) |
| Positions   | `DhanSource.get_positions()` |
| Order list  | `DhanSource.get_order_list()` |
| Cancel      | `DhanSource.cancel_order(order_id)` |

## Dependencies

- **Tradehull** uses the **dhanhq** package (see `requirements.txt`).
- Instrument file: Tradehull expects a `Dependencies` folder at **project root** and will create/use `all_instrument{date}.csv` there. `DhanSource` sets the working directory to the project root so this works when running from any folder.

## File

- `dhan_tradehull.py` – Tradehull class (login, instrument file, OHLC, option chain, expiries, order placement, positions, order book, etc.).
