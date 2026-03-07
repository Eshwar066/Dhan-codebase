Rules
1 Hour Time Frame
2 EMA 8 Period High/Low
If Close above High EMA line then Buy Futures with Tgt 0.6% of buy price and SL of 0.4%
If Closure Below Low EMA line then Sell Futures with Tgt 0.6% of Sell price and SL of 0.4%
SL 0.4% of value of trade
Re-entry – If Stoploss hit, then wait for 1 hour candle close to enter again and accordingly new TGT and SL
Re-entry – If TARGET booked and price touches the Upper or Lower EMA and closes in same trend, re-enter with fresh TGT and SL

Deploy using synthetic trade strategy, dont use futures

# 15-02-2026

# PERFORMANCE SUMMARY

Total Trades: 382
Win Rate %: 49.21
Profit Factor: 1.22
Net Profit: 21714.5
Max Drawdown: -7688.5
Max Drawdown %: -7.69
Avg Win: 648.89
Avg Loss: -516.89
Expectancy: 56.84
==================================================
factors to be added in this.

Profit Factor interpretation: Tradable
Expectancy > 0 → strategy has edge
If you want to turn 1.22 → 1.4+:
Add volatility filter (ATR expansion)
Avoid low ADX regimes
Increase target slightly in trending regimes
Skip first candle after session open
Reduce trades during sideways months
Even removing 10–15% worst trades can boost PF significantly

=============================
Add quaterly points collection, monthly percentage this can give.


Next plans to implement:

1. If we are buying two lots, buy 1 at where signal is generated and other but a limit price of 300 away, and calculate 0.004per from avg price for SL.
    Here check how many trades are taken avg proce and hit SL and hit target. Based on this will decide will include ths or not.
    total_trades
    trades_where_2nd_lot_filled
    2nd_lot_fill_rate %
    avg_pnl_when_2nd_filled
    avg_pnl_when_2nd_not_filled
    sl_hit_rate_when_2nd_filled

2. Use ATR or ADX based regime for more confirmation.
    ATR(14) > ATR(14) rolling mean
    or
    ADX(14) > 20

3. use ema 21 and super trend or 45 if price is above super trend or 45 dont take short positions and vice versa.
4. For targets once price as reached 0.006 per book 1lot and and check if the price is above or below ema. until it closes below 1st ema or previous candle low or touches 2nd ema dont exit. so the ride can be captured.
5. Monitor:
    Longest losing streak
    Time to recover equity high
    Monthly return stability

