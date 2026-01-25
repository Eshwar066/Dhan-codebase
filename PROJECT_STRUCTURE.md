# Project Structure (Dhan as single source of truth)

Run all scripts from the **project root** so imports resolve.

## Layout

```
core/                    # Dhan API as single source of truth
  api/                   # Data from Dhan only
    dhan_data.py         # DhanDataProvider, get_instrument_file
  broker/                # Order execution
    base.py              # BaseBroker (abstract)
    paper.py             # PaperBroker (Dhan data + simulated orders)
  config/
    constants.py         # INTERVAL_PARAMS, INDEX_STEP_DICT, get_step_df, etc.
  feed/
    dhan_websocket.py    # Dhan LTP WebSocket; uses core.api.get_instrument_file

legacy/                  # Non-Dhan (use only if needed)
  free_nse_fetcher.py    # FreeNSEFetcher (nsepy / nsepython)

runners/                 # Entrypoints: all use Dhan for data
  run_backtest.py        # DhanDataProvider
  run_paper.py           # DhanDataProvider + PaperBroker
  run_live.py            # Tradehull (Dhan live)

Strategies/
  InSideBarCandle/
    main.py              # from Dhan_Tradehull import Tradehull

Dhan_Tradehull.py        # Live broker + data; uses core.config, core.api.get_instrument_file
Dhan_websocket.py        # Re-exports core.feed.main_loop
FreeNSEFetcher.py        # Re-exports legacy.free_nse_fetcher.FreeNSEFetcher
```

## Data flow

- **Backtest**: `core.api.DhanDataProvider` (historical, intraday, instruments).
- **Paper**: `core.api.DhanDataProvider` + `core.broker.PaperBroker`.
- **Live**: `Dhan_Tradehull` (Dhan for data and orders); LTP via `Dhan_websocket` (Dhan feed) or Excel.

## Running

- Backtest: `python runners/run_backtest.py` (set `DHAN_CLIENT_CODE`, `DHAN_ACCESS_TOKEN` or edit).
- Paper: `python runners/run_paper.py`
- Live: `python runners/run_live.py`
- WebSocket LTP: `python Dhan_websocket.py`


## functions we have
get_login(self, ClientCode, token_id)
get_instrument_file(self)
order_placement(
        self,
        tradingsymbol: str,
        exchange: str,
        quantity: int,
        price: int,
        trigger_price: int,
        order_type: str,
        transaction_type: str,
        trade_type: str,
    )
convert_to_date_time(self, time)
get_balance(self)
get_live_pnl(self)
kill_switch(self, status)
get_ltp(self, name)get_lot_size(self, tradingsymbol: str)
get_lot_size(self, tradingsymbol: str)
resample_timeframe(self, df, timeframe="5T")
get_intraday_data(self, tradingsymbol, exchange, timeframe, from_date, to_date)
get_historical_data(self, tradingsymbol, exchange, days)
ATM_Strike_Selection(self, Underlying, Expiry):
OTM_Strike_Selection(self, Underlying, Expiry, OTM_count=1):
ITM_Strike_Selection(self, Underlying, Expiry, ITM_count=1):
cancel_all_orders(self)
order_report(self) -> Tuple[Dict, Dict]
get_option_greek(
        self,
        strike: int,
        expiry_date: str,
        asset: str,
        interest_rate: float,
        flag: str,
        scrip_type: str,
    )
get_expiry(self, underlying):     
check_expiry_date(self, underlying, Expiry):
get_freeze_quantity(self, strike):   
get_split_order_variables(self, strike, lots):
get_bid_ask(self, name):
get_data_for_single_script(self, names: list) -> dict:
get_stock_data(self, names: list) -> dict:
get_quote(self, names):
get_orderhistory(self, order_id):    
get_executed_price(self, order_id):     
cancel_order(self, OrderID: str) -> None:
check_valid_instrument(self, name):  
send_telegram_alert(self, message, receiver_chat_id, bot_token=None):
modify_order(
        self,
        appOrderID: str,
        modifiedOrderType: str,
        modifiedOrderQuantity: int,
        modifiedLimitPrice: int,
        modifiedStopPrice: int,
        trade_type: str,
    )

