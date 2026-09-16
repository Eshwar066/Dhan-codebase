# performance.py

> 18 nodes

## Key Concepts

- **performance.py** (13 connections) — `core/analytics/performance.py`
- **calculate_pnl()** (8 connections) — `core/analytics/performance.py`
- **performance_summary()** (6 connections) — `core/analytics/performance.py`
- **analytics/__init__.py** (6 connections) — `core/analytics/__init__.py`
- **load_trade_log()** (5 connections) — `core/analytics/performance.py`
- **sharpe_ratio()** (5 connections) — `core/analytics/performance.py`
- **trades_with_equity_and_drawdown()** (5 connections) — `core/analytics/performance.py`
- **DataFrame** (4 connections)
- **print_performance_summary()** (3 connections) — `core/analytics/performance.py`
- **warnings** (2 connections)
- **Series** (1 connections)
- **Trade log and performance analytics. - Trade log: trade_id, entry_time,…** (1 connections) — `core/analytics/performance.py`
- **Full performance summary from a trades DataFrame. Trades must have columns:…** (1 connections) — `core/analytics/performance.py`
- **Return a copy of the trades DataFrame with equity curve and drawdown columns…** (1 connections) — `core/analytics/performance.py`
- **Compute PnL for a single trade row. BUY: (exit_price - entry_price) * qty SELL:…** (1 connections) — `core/analytics/performance.py`
- **Print performance summary in a readable format.** (1 connections) — `core/analytics/performance.py`
- **Load trade log from CSV into a DataFrame. Args: csv_path: Path to trade_log.csv…** (1 connections) — `core/analytics/performance.py`
- **Sharpe ratio from trade PnL: (mean return - risk_free_rate) / std(return). Each…** (1 connections) — `core/analytics/performance.py`

## Relationships

- [typing](typing.md) (2 shared connections)
- [logging.py](logging.py.md) (2 shared connections)
- [factory.py](factory.py.md) (1 shared connections)

## Source Files

- `core/analytics/__init__.py`
- `core/analytics/performance.py`

## Audit Trail

- EXTRACTED: 31 (89%)
- INFERRED: 4 (11%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*