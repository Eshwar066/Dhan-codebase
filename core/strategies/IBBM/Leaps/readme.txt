LEAPS RSI – Strategy module
======================================
Implementation: LeapsQuatery_RSI_52_32.py (class LeapsQuarterly)
Shared logic:   core/strategies/IndiaMktMixins.py (IndiaMktMixins)
Registry:       core/strategies/registry.STRATEGY_MAP["LEAPS_RSI"]
Engine job:     run/config.py → dhan_leaps_rsi

Emergency (manual only; NOT loaded by live engine):
  core/strategies/Leaps/emergency/force_leaps_cycle.py
  core/strategies/Leaps/emergency/retry_leaps_main.py
  Run with engine stopped:
    .venv/bin/python -m core.strategies.IBBM.Leaps.emergency.force_leaps_cycle
    .venv/bin/python -m core.strategies.IBBM.Leaps.emergency.retry_leaps_main

==========================================================================================
STRATEGY OVERVIEW
==========================================================================================

Regime-based NIFTY option selling on 1-hour RSI with monthly hedge protection.

- RSI crosses below 32  → SELL CALL (MAIN) + BUY monthly CALL hedge
- RSI crosses above 52  → SELL PUT  (MAIN) + BUY monthly PUT hedge
- Exit when RSI crosses opposite band (MAIN + hedge)

Strategy is signal-only. Execution, risk, fills, and SL are handled by LiveEngine + OrderRouter.

==========================================================================================
EVALUATION (LIVE)
==========================================================================================

Timeframe: 60m NIFTY bars (closed bar only).

NSE hourly bar close window (IST) — evaluation allowed after bar close + grace:
  10:15, 11:15, 12:15, 13:15, 14:15, 15:15, 16:15

Entry requires RSI CROSSOVER (not sustained level):
  CALL entry: prev_rsi >= 32 and rsi < 32
  PUT  entry: prev_rsi <= 52 and rsi > 52

One evaluation per closed hourly bar (deduped by bar open key).

Live path:
  1. CandleAggregator closed 60m bar
  2. indicator_manager enriches RSI / EMA
  3. LiveEngine._run_exits_and_rollover (exits + hedge rollover every closed bar)
  4. should_evaluate → on_candle (entries on crossover only)

Backtest path:
  BacktestEngine runs exit + rollover every candle; gates entry on should_evaluate.

==========================================================================================
MAIN LEG EXPIRY — dual MAIN bundles (toggle in strategy.yaml → legs:)
==========================================================================================

Two optional MAIN+HEDGE bundles on the same RSI signal (separate structure_id):

  mini_leaps (default on):
    expiry_pref: LEAPS_ROLL — monthly rollover table (16th cutoff in resolver)
    structure_id: LEAPS_RSI:NIFTY:{regime}

  quarterly_leaps (default off):
    expiry_pref: QUARTERLY — Mar/Jun/Sep/Dec last Tuesday
    structure_id: LEAPS_RSI:NIFTY:{regime}:QTR
    Quarterly mid-month cutoff: 15th (Feb/May/Aug/Nov)

Toggle in core/strategies/Leaps/strategy.yaml → legs: → enabled: true/false
Or class attrs: mini_leaps_enabled / quarterly_leaps_enabled

Hedge is unchanged for both: monthly BUY ~2% OTM (15th calendar cutoff).

==========================================================================================
MAIN LEG EXPIRY — LEAPS_ROLL detail (mini leg)
==========================================================================================

Code: expiryType = "LEAPS_ROLL" (ExpiryResolver._leaps_rollover_month_year)

Monthly stepping calendar (cutoff = day 16 onward in code):

  Month   Days 1–15 → sell expiry in   Days 16–end → sell expiry in
  Jan     February                  March
  Feb     March                     April
  Jul     August                    September
  Nov     December                  January (next year)
  …       (see ExpiryResolver.LEAPS_ROLL roll table)

Expiry date = last Tuesday of target month.

NOTE: Older docs described Mar/Jun/Sep/Dec quarterly — that is QUARTERLY mode,
not what LEAPS_RSI runs today. To use classic quarterly, change expiryType to
"QUARTERLY" in LeapsQuatery_RSI_52_32.py (separate strategy decision).

==========================================================================================
STRIKE SELECTION
==========================================================================================

- NIFTY LEAPS grid: 500-point steps (22000, 22500, 23000, …)
- Premium bands (on_candle):
    CALL → 200–400 (ideal ~350)
    PUT  → 200–400 (ideal ~350)
- Closest to ideal premium in band is selected.

==========================================================================================
HEDGING
==========================================================================================

- BUY monthly option (~2% OTM from sold strike; 500-step grid)
  CALL main 24500 → hedge ~25000
  PUT  main 24500 → hedge ~24000

- Hedge expiry (resolve_hedge_expiry):
    trade before 15th → current month (last Tuesday)
    trade on/after 15th → next month

- Separate option chain fetch for hedge (hedge_option_chain_snapshots/).

- parent_intent_id links hedge ENTRY to MAIN sell intent.

==========================================================================================
HEDGE ROLLOVER (LIVE + BACKTEST)
==========================================================================================

IndiaMktMixins.on_candle_rollover — wired in LiveEngine._run_exits_and_rollover.

Window: calendar days 15–18 of month.
Roll when: current date >= adjusted 18th (weekends + NSE holidays → prior session).
Action: new HEDGE ENTRY (next month) first, then HEDGE_EXIT (sell old).
  Buying first avoids a margin spike from briefly unhedged MAIN.
Deduped: one roll per structure per calendar day (rolled_hedges set).

==========================================================================================
EXECUTION (LIVE)
==========================================================================================

- HEDGE + MAIN ENTRY: fill-gated bundle on Dhan (hedge BUY → wait fill → MAIN SELL)
- Hedge auto-retry with refreshed bid/ask (LEAPS_RSI only, up to 3 attempts)
- LIMIT prices from live depth (engine price_map → OrderRouter)
- Hedge exit / MAIN exit: depth-based limit at eval bar

==========================================================================================
EMERGENCY HEDGE ROLLOVER (manual, after market open)
==========================================================================================

Stop dhan-leaps-rsi.service first, then:

  .venv/bin/python -m core.strategies.IBBM.Leaps.emergency.roll_leaps_hedge --dry-run
  .venv/bin/python -m core.strategies.IBBM.Leaps.emergency.roll_leaps_hedge

Order: BUY next-month hedge → wait fill → EXIT current-month hedge.
Default target expiry = next month (last Tuesday). Use --use-calendar for 15th cutoff.
Optional: --structure-id <sid> (repeatable).

==========================================================================================
EXIT RULES
==========================================================================================

MAIN (should_exit):
  Short CALL → exit when RSI > 52
  Short PUT  → exit when RSI < 32

on_position_exit: MAIN_EXIT + HEDGE_EXIT intents (structure unwind).

==========================================================================================
ROADMAP / NOT YET IMPLEMENTED
==========================================================================================

- Regime lock (one open structure per regime globally)
- Hedge PnL attribution
- Delta-aware hedge distance

==========================================================================================
INTENT REFERENCE
==========================================================================================

Structure ID: LEAPS_RSI:NIFTY:{RSI_LT_32|RSI_GT_52}
Tags: MAIN (sell), HEDGE (buy), HEDGE_EXIT, MAIN_EXIT

Example MAIN sell intent fields: side=SELL, action=ENTRY, tag=MAIN, trade_type=MARGIN

==========================================================================================
END OF STRATEGY SPEC
==========================================================================================
