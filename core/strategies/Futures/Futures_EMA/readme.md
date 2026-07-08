# Futures EMA High/Low (FuturesEMAHighLow)

Implementation: `core/strategies/Futures/Futures_EMA/Futures_EMA.py`  
Registry: `STRATEGY_MAP["FuturesEMAHighLow"]`

## Rules (implemented)

| Item | Value |
|------|--------|
| Timeframe | 1 hour |
| EMA | 8-period on **high** and **low** |
| Entry long | Close **above** EMA-high → BUY NIFTY futures |
| Entry short | Close **below** EMA-low → SELL NIFTY futures |
| Target | **0.6%** from entry (`target_pct = 0.006`) |
| Stop loss | **0.4%** from entry (`sl_pct = 0.004`) |

## Re-entry

- **After SL:** wait for next 1h bar close, then allow fresh signal with new TGT/SL.
- **After TARGET:** if price touches EMA band and closes in trend direction, re-enter with fresh TGT/SL.

## Instrument

Uses **NSE index futures** via `futures_intent_creation_details` (not synthetic spot).

> Note: An older line in this file said “don't use futures / synthetic” — that is **outdated**. The live implementation trades futures contracts.

## Backtest performance (2026-02-15 snapshot)

Historical backtest stats in this folder are for reference only; re-run before deployment decisions.

## Roadmap (not implemented)

- ATR/ADX regime filter
- Partial scale-out at target
- SuperTrend / EMA-45 trend filter
- Two-lot staggered entry experiment

See bottom of this file for archived backtest notes and experiment ideas.

---

# PERFORMANCE SUMMARY (archived)

Total Trades: 382  
Win Rate %: 49.21  
Profit Factor: 1.22  
Net Profit: 21714.5  
Max Drawdown: -7688.5  

## Next plans (experiments)

1. Two-lot staggered entry (1 market + 1 limit 300 away)
2. ATR(14) > rolling mean or ADX(14) > 20 confirmation
3. SuperTrend / EMA-45 directional filter
4. Trail after partial target at EMA
