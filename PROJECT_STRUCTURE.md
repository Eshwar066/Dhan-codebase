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
