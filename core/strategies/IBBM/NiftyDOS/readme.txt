Nifty-DOS — Strategy module
======================================
Implementation: NiftyDOS.py (class NiftyDOS)
Shared logic:   core/strategies/IndiaMktMixins.py
Engine job:     run/config.py → nifty_dos

==========================================================================================
RULES
==========================================================================================

Studies:        Supertrend(ATR=16, Mult=2), SMA 9, ADX 14
Timeframe:      30m entry eval, 5m TP/SL check
Main product:   Weekly NIFTY option sell, premium 80–105, must be OTM
Hedging:        Weekly option 500 points OTM from MAIN (CALL K→K+500, PUT K→K−500)
Rollover:       Hedge roll 1 trading day before weekly expiry → next weekly
Event case:     No new entries on NSE holidays, yaml event_no_trade_dates, or expiry day

Entry Signals (NEW - Only Supertrend):
  Supertrend Green (flip to bullish) → SELL OTM PUT (premium 80-105)
  Supertrend Red   (flip to bearish) → SELL OTM CALL (premium 80-105)
  NO MA9 or ADX filter for initial entry on signal change

Exit (MAIN):
  TP/SL checked on 5min candles:
    CALL: SL 3.5%, TP >3.7%
    PUT:  SL 3.5%, TP >3.7%
  Supertrend reversal:
    Short PUT  → exit when Supertrend turns Bearish
    Short CALL → exit when Supertrend turns Bullish

Reentry on SL (on NEXT candle after SL hit):
  1. ADX > 25
  2. Nifty price >= MA9 for bullish ST (PUT) / Nifty price <= MA9 for bearish ST (CALL)
  3. Candle in favor of trend (green for bullish, red for bearish)
  ALL THREE conditions must be met on the next candle

Reentry on TP (IMMEDIATE - same candle):
  Direct reentry on same direction
  Find strike in premium range 80-105
  NO MA/ADX/candle wait - immediate execution

EOD Management (after 3:00 PM):
  If |PnL| >= 3% → exit trade
  Re-entry if ADX > 25 else reentry on next day 9:45

No Entry at 3:15 PM:
  For both CE and PE when ADX < 25

9:15 AM Check:
  If price opposite to signal → exit trade and re-enter on 30min candle close

Expiry Day:
  On day of expiry, new trade triggered with shift to next expiry

==========================================================================================
CONFIG (strategy.yaml → params:)
==========================================================================================

  supertrend_atr_period: 16
  supertrend_multiplier: 2.0
  ma_period: 9
  adx_period: 14
  premium_min / premium_max: 80 / 105
  hedge_distance_points: 500
  weekly_expiry_weekday: 1   # Tuesday
  event_no_trade_dates: []   # extra ISO dates

==========================================================================================
RUN
==========================================================================================

  python -m tools.strategy_manifest generate
  python -m run.main --engine-id nifty_dos