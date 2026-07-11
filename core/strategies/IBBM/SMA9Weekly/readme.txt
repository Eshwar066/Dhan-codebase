Nifty SMA9 Weekly — Strategy module
======================================
Implementation: NiftySMA9Weekly.py (class NiftySMA9Weekly)
Shared logic:   core/strategies/IndiaMktMixins.py
Engine job:     run/config.py → dhan_sma9_weekly

==========================================================================================
RULES
==========================================================================================

Study:        SMA(9) on close
Timeframe:    2 hours (120m), closed-bar evaluation only
Main product: Weekly NIFTY option sell, premium 80–100, must be OTM
Hedging:      Weekly option ~2–2.5% from sold strike (same weekly series)
Rollover:     Hedge roll 1 trading day before weekly expiry → next weekly
Event case:   No new entries on NSE holidays, yaml event_no_trade_dates, or expiry day

Signals:
  Close crosses above SMA9 → SELL PUT  + BUY PUT hedge
  Close crosses below SMA9 → SELL CALL + BUY CALL hedge

Exit (MAIN):
  Short PUT  → exit when close < SMA9
  Short CALL → exit when close > SMA9
  (+ matching HEDGE_EXIT)

==========================================================================================
CONFIG (strategy.yaml → params:)
==========================================================================================

  sma_period: 9
  premium_min / premium_max: 80 / 100
  hedge_distance_pct: 0.0225
  weekly_expiry_weekday: 1   # Tuesday
  event_no_trade_dates: []   # extra ISO dates

==========================================================================================
RUN
==========================================================================================

  python -m tools.strategy_manifest generate
  python -m run.main --engine-id dhan_sma9_weekly
