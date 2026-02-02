If nifty rsi is below 32 will sell call option in 1hr candle, until it crosses rsi 52

If nifty rsi is above 52 will sell put option in 1hr candle, until it crosses rsi 32

timeframe to check the logic is at 10:15,11:15,12:15,1:15,2:15,3:15 since we are using 1hr candle

sell 500-1000 roundoff strikes in quaterly month
jan-march, below 15th feb, take march strikes
after 15th feb, sell June strikes
april-June, in may after 15th we take september strikes
july-september, in aug after 15th will take december strikes
oct- decemeber, in nov after 15th will take march strikes

Hedging in monthly of current expiry: Buy Monthly Hedge from nifty, approx 2per away from selling strike
Rollover hedging on 18th of every month, if 18th is holiday or saturaday or sunday will do 1 day before

if new tradas comes 15th or after that then take hedging of next month only


In live: while placing order will get market_depth and place limit order for best price.
==========================================================================================

"""
LEAPS QUARTERLY RSI OPTION SELLING STRATEGY
==========================================

Strategy Type:
--------------
Regime-based option selling using RSI on 1-hour candles.

Underlying:
-----------
NIFTY

Core Logic:
-----------
- RSI < 32  → SELL CALL options
- RSI > 52  → SELL PUT options
- Maintain position until RSI crosses the opposite band

Timeframe:
----------
1 Hour candles

Signal Evaluation Times (IST):
------------------------------
10:15
11:15
12:15
13:15
14:15
15:15

No trades outside these timestamps.

------------------------------------------------------------
OPTION SELECTION RULES
------------------------------------------------------------

1. Expiry Selection (Quarterly)
--------------------------------
Quarterly expiries are chosen based on trade date:

Jan – Feb 15        → March expiry
After Feb 15        → June expiry

Apr – May 15        → June expiry
After May 15        → September expiry

Jul – Aug 15        → September expiry
After Aug 15        → December expiry

Oct – Nov 15        → December expiry
After Nov 15        → March (next year)

Monthly cutoff date: 15th of the mid-month.

------------------------------------------------------------

2. Strike Selection
-------------------
- Only round strikes (multiples of 500 / 1000)
- Premium filters:
    CALL → LTP between 300–400
    PUT  → LTP between 200–400

Strike closest to ideal premium (~350) is selected.

------------------------------------------------------------
TRADE RULES
------------------------------------------------------------

SELL CALL CONDITIONS:
---------------------
- RSI < 32
- Trade only at valid timestamps
- Sell quarterly CALL option
- Hold until RSI > 52

SELL PUT CONDITIONS:
--------------------
- RSI > 52
- Trade only at valid timestamps
- Sell quarterly PUT option
- Hold until RSI < 32

------------------------------------------------------------
HEDGING RULES
------------------------------------------------------------

Hedge Type:
-----------
BUY Monthly option (not quarterly)

Hedge Distance:
---------------
~2% away from the sold strike

Expiry:
-------
- Use current month hedge
- If new trade occurs on or after 15th:
  → Use NEXT month hedge

------------------------------------------------------------

Hedge Rollover:
---------------
- Roll hedge on 18th of every month
- If 18th is Holiday / Saturday / Sunday:
  → Roll one working day earlier

------------------------------------------------------------
EXIT RULES
------------------------------------------------------------

Exit position if:
-----------------
1. RSI regime flips
   - CALL → RSI > 52
   - PUT  → RSI < 32

2. Hedge rollover day

3. Forced risk / engine exit

------------------------------------------------------------
EXECUTION (LIVE MODE)
------------------------------------------------------------

- Fetch market depth
- Place LIMIT orders only
- Price = best bid/ask
- Avoid market orders to reduce slippage

------------------------------------------------------------
RISK CHARACTERISTICS
------------------------------------------------------------

- Low frequency
- Directional regime based
- Quarterly decay advantage
- Monthly hedge protection
- Controlled rollover logic

------------------------------------------------------------
INTENT FORMAT (REFERENCE)
------------------------------------------------------------

Example intent produced by strategy:

{
    "intent_id": "<uuid>",
    "symbol": "NIFTY",
    "trading_symbol": "NIFTY 30 MAR 25000 PUT",
    "side": "SELL",
    "option_type": "PUT",
    "strike": 25000,
    "expiry": "2026-03-30",
    "qty": 1,
    "price": 350,
    "strategy": "LEAPS_RSI",
    "trade_type": "MARGIN",
    "exchange": "NSE",
    "segment": "D",
    "lot_size": 65
}

------------------------------------------------------------
IMPORTANT NOTES
------------------------------------------------------------

- Strategy is SIGNAL ONLY
- Execution, risk checks, and order placement handled by engine
- No overtrading due to fixed time evaluation
- Designed for capital-efficient, slow theta harvesting

============================================================
END OF STRATEGY SPEC
============================================================
=============================================================
============================================================
============================================================
==============================================================







"""
📘 LEAPS Quarterly RSI Option Selling Strategy
Strategy Name

LEAPS_RSI

Strategy Type

Regime-based quarterly option selling with monthly hedging

Underlying

NIFTY Index

1. Strategy Overview

The LEAPS Quarterly RSI Strategy is a low-frequency, regime-based options selling system designed to harvest long-dated theta while maintaining controlled risk using monthly hedges.

The strategy uses RSI on 1-hour candles to determine whether the market is in a bullish or bearish regime and sells quarterly options accordingly.

Execution, risk checks, position sizing, and order placement are handled by the engine.
The strategy itself is signal-only.

2. Market Regime Logic
RSI Condition	Action
RSI < 32	Sell CALL option
RSI > 52	Sell PUT option
Between 32–52	No new trades

Positions are held until the RSI crosses the opposite band.

3. Timeframe & Evaluation Schedule
Candle Timeframe

1 Hour

Allowed Evaluation Times (IST)

Signals are evaluated only at the following times:

10:15

11:15

12:15

13:15

14:15

15:15

This prevents overtrading and ensures consistent signal timing.

4. Expiry Selection Logic (Quarterly)

The strategy always sells quarterly expiry options, determined dynamically based on the trade date.

Quarterly Expiry Rules
Trade Period	Before 15th	After 15th
Jan – Feb	March	June
Apr – May	June	September
Jul – Aug	September	December
Oct – Nov	December	March (next year)

The cutoff day is 15th of the mid-month.

5. Strike Selection Rules
Strike Constraints

Only round strikes (multiples of 500 / 1000)

Strike must be near ATM

Premium Filters
Option Type	Premium Range
CALL	300 – 400
PUT	200 – 400

From the filtered strikes, the strike closest to premium ≈ 350 is selected.

6. Trade Entry Rules
Sell CALL

RSI < 32

Valid evaluation time

Quarterly expiry

Premium filter satisfied

Sell PUT

RSI > 52

Valid evaluation time

Quarterly expiry

Premium filter satisfied

Only one position per signal is generated.

7. Hedging Rules
Hedge Type

BUY Monthly option

Hedge Distance

Approximately 2% away from the sold strike

Hedge Expiry

Default: Current month

If new trade occurs on or after 15th:

Hedge is taken in next month expiry

8. Hedge Rollover Rules

Hedge rollover date: 18th of every month

If 18th is:

Holiday

Saturday

Sunday
→ Rollover is done one trading day earlier

Hedge rollover forces an exit of the existing hedge and creation of a new hedge.

9. Exit Conditions

A position is exited if any of the following occur:

RSI Regime Exit
Position	Exit Condition
CALL	RSI > 52
PUT	RSI < 32
Hedge Rollover Exit

On hedge rollover day

Engine / Risk Exit

Risk limits breached

Forced system exit

10. Execution Rules (Live Mode)

Orders are placed as LIMIT orders

Market depth is fetched before placing orders

Best bid/ask is used as limit price

Market orders are avoided to reduce slippage

11. Risk Characteristics

Low trade frequency

Long-dated theta decay advantage

Monthly hedge for tail risk

No intraday churn

Capital-efficient structure

This strategy is designed for steady drawdown-controlled returns, not aggressive scalping.

12. Intent Structure (Reference)

Example intent generated by the strategy:

{
  "intent_id": "uuid",
  "symbol": "NIFTY",
  "trading_symbol": "NIFTY 30 MAR 25000 PUT",
  "side": "SELL",
  "option_type": "PUT",
  "strike": 25000,
  "expiry": "2026-03-30",
  "qty": 1,
  "price": 350,
  "strategy": "LEAPS_RSI",
  "trade_type": "MARGIN",
  "exchange": "NSE",
  "segment": "D",
  "lot_size": 65
}

13. Design Philosophy

Strategy generates intent only

No broker-specific logic

Fully engine-driven execution

Deterministic decision points

Easy to audit and backtest

14. Disclaimer

This strategy is for educational and system-design purposes.
Live trading involves risk. Always validate with paper trading and strict risk limits.

15. Versioning

Strategy Version: 1.0

Engine Compatibility: Codebase v3.1+

