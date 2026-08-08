# Nifty 500 Equity Momentum (weekly backtest)

Standalone Yahoo Finance backtest modeled on `core/strategies/ETF/etfOne.py`.

## Production rules

| Rule | Setting |
|------|---------|
| Universe | Nifty 500 (`Dependencies/universe/ind_nifty500list.csv`) |
| Rebalance | Every Friday |
| Trend | Close > EMA200 |
| Confirmation | EMA50 > EMA200 |
| Momentum | Mean of RET252, RET126, RET63 |
| RSI | RSI(14) > 55 |
| Liquidity | 20d ADV (Close×Volume) ≥ ₹5 crore |
| Book | Top 10, equal weight |
| Switch | Replace only if challenger composite − holding composite ≥ **7%** |

## Run

```bash
cd /root/Dhan-codebase
source .venv/bin/activate
pip install yfinance pyarrow matplotlib   # if needed
MPLBACKEND=Agg python3 core/strategies/Equity/MomentumStocks/momentum_stocks.py
```

First run downloads OHLCV and caches to:

`Dependencies/universe/nifty500_ohlcv_cache.pkl`

Outputs under `logs/MomentumStocks/`:

- `summary.csv`
- `trade_log.csv` — closed trades: Symbol, Shares, EntryDate, EntryPrice, ExitDate, ExitPrice, MTM, Return_%, Days, ExitReason
- `trade_fills.csv` — raw BUY/SELL fills (optional audit)
- `portfolio.csv`
- `weights.csv`
- `equity_curve.png` / `drawdown.png`

## Smoke test (faster)

In `momentum_stocks.py` set:

```python
MAX_SYMBOLS = 80
```

then re-run (delete the pickle cache if you previously saved a partial universe).
