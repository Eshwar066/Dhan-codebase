run/ – Entry point and config
=============================

main.py
-------
- Loads STRATEGY_JOBS from run/config.py.
- For each enabled job:
  - Builds data_provider = DhanDataProvider(DhanSource())  [data layer]
  - Builds broker = DhanBroker(DhanBrokerApi(dhan_source)) or DeltaBroker/SimulatedBroker
  - Builds order_router, position_manager, intent_store, risk_manager, instrument_store
  - BACKTEST: BacktestEngine(data_provider, strategy, order_router, ...).run(...)
  - LIVE/PAPER: LiveEngine(..., candle_service=CandleService(data_provider), ...).start(...)

Broker choice: set BROKER_NAME = "DHAN" or "DELTA" in main.py (Delta is stub).

config.py
---------
- RUN_MODE: RunMode.BACKTEST | RunMode.PAPER | RunMode.LIVE
- STRATEGY_JOBS: list of { name, enabled, capital, symbols, backtest: {...}, live: {...} }

Strategy config is wired via core/strategies/registry.STRATEGY_MAP and runtime_spec.

Dependencies
------------
- DhanSource uses core/library/dhan_tradehull.Tradehull, which expects:
  - Dependencies/ at project root
  - all_instrument{date}.csv (created/fetched by Tradehull on login)
- InstrumentStore in main.py loads: Dependencies/all_instrument{current_date}.csv
- Run from project root (or DhanSource will chdir to project root for Dependencies).

Credentials
-----------
- .env: DHAN_CLIENT_CODE, DHAN_ACCESS_TOKEN (used by DhanSource).
