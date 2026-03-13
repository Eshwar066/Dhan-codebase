run/ – Entry point and config
=============================

main.py
-------
- Loads STRATEGY_JOBS from run/config.py.
- For each enabled job:
  - Builds data_provider = DhanDataProvider(DhanSource())  [data layer]
  - Builds broker = DhanBroker(DhanBrokerApi(dhan_source)) or DeltaBroker/SimulatedBroker
  - Builds order_router, position_manager, intent_store, risk_manager, instrument_store
  - BACKTEST: BacktestEngine(...).run(...)
- LIVE/PAPER: LiveEngine(...).start(...); broker is SimulatedBroker for PAPER, real broker for LIVE (per config.run_mode from job run_mode or RUN_MODE)

config.py
---------
- RUN_MODE: default RunMode.BACKTEST | RunMode.PAPER | RunMode.LIVE when a job does not set run_mode
- Per-job run_mode: set "run_mode": "PAPER" or "run_mode": "LIVE" on a job to override; mix paper and live in one process
- STRATEGY_JOBS: list of { name, venue, enabled, run_mode (optional), capital, symbols, backtest: {...}, live: {...}, delta_leverage (Delta only, optional), ... }

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
