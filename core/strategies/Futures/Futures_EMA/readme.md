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
