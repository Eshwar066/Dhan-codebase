LEAPS RSI – Strategy module
======================================
Implementation: LeapsQuatery_RSI_52_32.py (class LeapsQuarterly)
Shared logic:   core/strategies/IndiaMktMixins.py (IndiaMktMixins)
Config YAML:    core/strategies/IBBM/Leaps/strategy.yaml
Registry:       STRATEGY_MAP / strategy id "LEAPS_RSI"
Engine job:     run/config.py → engine_id dhan_leaps_rsi
                strategies: ["LEAPS_RSI", ...]
systemd:        utils/systemd/dhan-leaps-rsi.service
                python -m run.main --engine-id dhan_leaps_rsi

Emergency (manual only; stop live engine first):
  core/strategies/IBBM/Leaps/emergency/force_leaps_cycle.py
  core/strategies/IBBM/Leaps/emergency/retry_leaps_main.py
  core/strategies/IBBM/Leaps/emergency/roll_leaps_hedge.py
  Run:
    .venv/bin/python -m core.strategies.IBBM.Leaps.emergency.force_leaps_cycle
    .venv/bin/python -m core.strategies.IBBM.Leaps.emergency.retry_leaps_main
    .venv/bin/python -m core.strategies.IBBM.Leaps.emergency.roll_leaps_hedge [--dry-run]

==========================================================================================
STRATEGY OVERVIEW
==========================================================================================

Regime-based NIFTY option selling on 1-hour RSI(14) with monthly hedge protection.

- RSI crosses below 32  → SELL CALL (MAIN) + BUY monthly CALL hedge
- RSI crosses above 52  → SELL PUT  (MAIN) + BUY monthly PUT hedge
- Exit MAIN when RSI crosses opposite band; hedge exits with MAIN

Optional dual MAIN bundles on the same RSI signal (separate structure_id each):
  mini_leaps      — expiry_pref LEAPS_ROLL (default ON)
  quarterly_leaps — expiry_pref QUARTERLY  (default OFF)

Strategy is signal-only. Execution, risk, fills, and SL are handled by
LiveEngine + OrderRouter (venue DHAN for dhan_leaps_rsi).

==========================================================================================
INDICATORS
==========================================================================================

prepare_indicators:
  - rsi / prev_rsi  — TA-Lib RSI(14)
  - EMA high/low    — ema_period = 8 (persisted via indicator_helpers)

requires_live_rsi_patch = True  (live RSI enrichment on closed 60m bars)

==========================================================================================
EVALUATION (LIVE)
==========================================================================================

Timeframe: 60m NIFTY bars (closed bar only).

NSE hourly bar close window (IST) — should_evaluate uses
nse_60m_bar_close_eval_window(grace_minutes=8):
  after closes near 10:15, 11:15, 12:15, 13:15, 14:15, 15:15 (+ grace)

Entry requires RSI CROSSOVER (not sustained level):
  CALL entry: prev_rsi >= 32 and rsi < 32
  PUT  entry: prev_rsi <= 52 and rsi > 52

One evaluation per closed hourly bar (deduped by bar open key IST).

Live path:
  1. CandleAggregator closed 60m bar
  2. indicator_manager enriches RSI / EMA
  3. LiveEngine._run_exits_and_rollover (exits + hedge rollover every closed bar)
  4. should_evaluate → on_candle (entries on crossover only)

Backtest path:
  BacktestEngine runs exit + rollover every candle; gates entry on should_evaluate.

==========================================================================================
MAIN LEGS — dual MAIN+HEDGE bundles (strategy.yaml → legs:)
==========================================================================================

Toggle in core/strategies/IBBM/Leaps/strategy.yaml:

  legs:
    mini_leaps:
      enabled: true          # class: mini_leaps_enabled
      expiry_pref: LEAPS_ROLL
      structure_suffix: ""
    quarterly_leaps:
      enabled: false         # class: quarterly_leaps_enabled
      expiry_pref: QUARTERLY
      structure_suffix: ":QTR"

On each RSI signal, each enabled leg:
  1. Builds structure_id = LEAPS_RSI:NIFTY:{regime}{suffix}
  2. Finds MAIN strike in premium band 200–400 (ideal ~350), 500-pt grid
  3. Creates MAIN SELL ENTRY + monthly HEDGE BUY ENTRY

Blocks new ENTRY if that structure (or same leg family) already has open MAIN,
pending ENTRY intent, or prior entry for structure (unless RSI-reversal defer).

==========================================================================================
MAIN LEG EXPIRY — LEAPS_ROLL (mini)
==========================================================================================

expiry_pref = LEAPS_ROLL → ExpiryResolver._leaps_rollover_month_year
Cutoff day = 16 in resolver (days 1–15 vs 16–end).

Expiry date = last Tuesday of the target month from the LEAPS_ROLL table
(see ExpiryResolver.LEAPS_ROLL).

==========================================================================================
MAIN LEG EXPIRY — QUARTERLY (optional)
==========================================================================================

expiry_pref = QUARTERLY → Mar / Jun / Sep / Dec last Tuesday.
Mid-month style cutoffs live in ExpiryResolver.quarterly_target_expiry_date.

structure_id suffix: :QTR
  Example: LEAPS_RSI:NIFTY:RSI_LT_32:QTR

==========================================================================================
STRIKE SELECTION (MAIN)
==========================================================================================

- NIFTY LEAPS grid: option_chain_strike_step = 500
- Premium band: 200–400 (option_chain_ideal_premium = 350)
- find_strike_in_premium_range + closest-to-ideal sort (IndiaMktMixins)
- Snapshot logs: leaps_rsi / leaps_rsi_quarterly under option_chain_snapshots/

==========================================================================================
HEDGING
==========================================================================================

- BUY monthly option ~2% OTM from sold strike, snapped to 500-step grid
    CALL MAIN K → hedge ~ round(K * 1.02 / 500) * 500
    PUT  MAIN K → hedge ~ round(K * 0.98 / 500) * 500

- Hedge expiry (resolve_hedge_expiry) — ignores MAIN mini vs quarterly:
    trade_date.day < 15 → current month last Tuesday (weekday=1)
    trade_date.day >= 15 → next month last Tuesday
  Config: hedge_monthly_rollover_after_calendar_day = 15
          hedge_monthly_expiry_weekday = 1

- Separate hedge chain fetch (expiry_flag MONTH, ±60 strikes).
- Snapshot target: leaps_rsi_hedge
- parent_intent_id links hedge ENTRY to MAIN sell intent.

==========================================================================================
HEDGE ROLLOVER (LIVE + BACKTEST)
==========================================================================================

IndiaMktMixins.on_candle_rollover — LiveEngine._run_exits_and_rollover.

Window: calendar days 15–18 of month.
Roll when: date >= adjusted 18th (weekends + NSE holidays → prior session).
Action: new HEDGE ENTRY (next month) first, then HEDGE_EXIT (sell old)
  — buy-first avoids a margin spike from briefly unhedged MAIN.
Deduped: one roll per structure per calendar day.

==========================================================================================
RSI REVERSAL DEFERRAL (same-bar flip)
==========================================================================================

If on_candle wants the opposite side but MAIN is still open (exit already
enqueued this bar), entry is deferred:

  1. _arm_pending_rsi_reversal prebuilds reverse HEDGE+MAIN intents
     (ignore_open_main=True) while option chain is warm
  2. on_main_exit_filled fires after MAIN_EXIT fill → place deferred ENTRY

Guards: MAIN_EXIT tag; optional structure_id match to pending.exit_structure_id.
Tests: core/strategies/IBBM/Leaps/tests/test_rsi_reversal_defer.py

==========================================================================================
EXIT RULES
==========================================================================================

should_exit (MAIN only):
  Short CALL → exit when RSI > 52
  Short PUT  → exit when RSI < 32

on_position_exit:
  MAIN_EXIT (BUY to cover short) + HEDGE_EXIT (sell hedge)

==========================================================================================
EXECUTION (LIVE / DHAN)
==========================================================================================

- HEDGE + MAIN ENTRY: fill-gated bundle (hedge BUY → wait fill → MAIN SELL)
- Hedge auto-retry with refreshed bid/ask (LEAPS_RSI, up to 3 attempts)
- LIMIT prices from live depth (engine price_map → OrderRouter)
- Hedge exit / MAIN exit: depth-based limit at eval bar

Run:
  sudo systemctl start dhan-leaps-rsi.service
  # or
  python -m run.main --engine-id dhan_leaps_rsi

==========================================================================================
EMERGENCY HEDGE ROLLOVER (manual)
==========================================================================================

Stop dhan-leaps-rsi.service first, then:

  .venv/bin/python -m core.strategies.IBBM.Leaps.emergency.roll_leaps_hedge --dry-run
  .venv/bin/python -m core.strategies.IBBM.Leaps.emergency.roll_leaps_hedge

Order: BUY next-month hedge → wait fill → EXIT current-month hedge.
Default target expiry = next month (last Tuesday). Use --use-calendar for 15th cutoff.
Optional: --structure-id <sid> (repeatable).

==========================================================================================
INTENT REFERENCE
==========================================================================================

Structure ID (mini):
  LEAPS_RSI:NIFTY:{RSI_LT_32|RSI_GT_52}

Structure ID (quarterly):
  LEAPS_RSI:NIFTY:{RSI_LT_32|RSI_GT_52}:QTR

Tags / actions:
  MAIN       ENTRY  SELL
  HEDGE      ENTRY  BUY
  MAIN_EXIT  EXIT   BUY (cover)
  HEDGE_EXIT EXIT   SELL

trade_type: MARGIN (India equity options via Dhan mapping)

==========================================================================================
ROADMAP / NOT YET IMPLEMENTED
==========================================================================================

- Global regime lock across both mini and quarterly legs
- Hedge PnL attribution
- Delta-aware hedge distance

==========================================================================================
END OF STRATEGY SPEC
==========================================================================================
