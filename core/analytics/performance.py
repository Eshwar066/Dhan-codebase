"""
Trade log and performance analytics.

- Trade log: trade_id, entry_time, exit_time, side, entry_price, exit_price, qty, pnl
- Win rate, profit factor, equity curve, drawdown (absolute and %)
- Bonus: average win/loss, expectancy, Sharpe ratio

Step zero:
- Equity = initial_capital + cumsum(pnl). initial_capital must be > 0 (from config).
- PnL is in currency (position_manager applies lot_size for futures/options).
- Spreads: each leg is one row; equity curve sums all pnl (combined structure).
- Margin is not modeled; equity is capital + realized pnl only.
"""

import os
from typing import Optional

import pandas as pd


def calculate_pnl(row: pd.Series) -> float:
    """
    Compute PnL for a single trade row.
    BUY: (exit_price - entry_price) * qty
    SELL: (entry_price - exit_price) * qty
    """
    if row["side"].upper() == "BUY":
        return (row["exit_price"] - row["entry_price"]) * row["qty"]
    else:
        return (row["entry_price"] - row["exit_price"]) * row["qty"]


def load_trade_log(
    csv_path: str,
    strategy: Optional[str] = None,
    compute_pnl_if_missing: bool = True,
) -> pd.DataFrame:
    """
    Load trade log from CSV into a DataFrame.

    Args:
        csv_path: Path to trade_log.csv (e.g. logs/trade_log.csv)
        strategy: If set, filter to this strategy only
        compute_pnl_if_missing: If True and 'pnl' is missing or NaN, compute from side/entry/exit/qty

    Returns:
        DataFrame with columns including trade_id, entry_time, exit_time, side,
        entry_price, exit_price, qty, pnl (and symbol, strategy if present).
    """
    if not os.path.exists(csv_path):
        return pd.DataFrame(
            columns=[
                "trade_id",
                "entry_time",
                "exit_time",
                "side",
                "entry_price",
                "exit_price",
                "qty",
                "pnl",
            ]
        )

    trades = pd.read_csv(csv_path)

    if strategy is not None and "strategy" in trades.columns:
        trades = trades[trades["strategy"] == strategy].copy()

    # Ensure numeric columns
    for col in ["entry_price", "exit_price", "qty", "pnl"]:
        if col in trades.columns:
            trades[col] = pd.to_numeric(trades[col], errors="coerce")

    if compute_pnl_if_missing and ("pnl" not in trades.columns or trades["pnl"].isna().all()):
        trades["pnl"] = trades.apply(calculate_pnl, axis=1)
    elif "pnl" in trades.columns and trades["pnl"].isna().any():
        mask = trades["pnl"].isna()
        trades.loc[mask, "pnl"] = trades.loc[mask].apply(calculate_pnl, axis=1)

    return trades.reset_index(drop=True)


def sharpe_ratio(
    trades: pd.DataFrame,
    initial_capital: float = 100_000,
    risk_free_rate: float = 0.0,
    annualization_factor: Optional[float] = None,
) -> float:
    """
    Sharpe ratio from trade PnL: (mean return - risk_free_rate) / std(return).

    Each trade is treated as one period; return = pnl / capital (no compounding).
    risk_free_rate: per-period (e.g. 0 for simplicity).
    annualization_factor: if set (e.g. sqrt(252) for daily), multiplies the ratio
        to approximate annualized Sharpe; if None, returns raw (per-trade) Sharpe.

    Returns 0.0 if fewer than 2 trades or std of returns is 0.
    """
    if trades is None or len(trades) < 2:
        return 0.0
    cap = float(initial_capital) if initial_capital and initial_capital > 0 else 100_000.0
    work = trades.copy()
    if "pnl" not in work.columns or work["pnl"].isna().all():
        work["pnl"] = work.apply(calculate_pnl, axis=1)
    returns = work["pnl"] / cap
    mean_r = returns.mean()
    std_r = returns.std()
    if std_r is None or std_r == 0 or (hasattr(std_r, "__float__") and float(std_r) == 0):
        return 0.0
    raw = (mean_r - risk_free_rate) / std_r
    if annualization_factor is not None and annualization_factor > 0:
        raw = raw * (annualization_factor ** 0.5)
    return float(raw)


def performance_summary(
    trades: pd.DataFrame,
    initial_capital: float = 100_000,
) -> dict:
    """
    Full performance summary from a trades DataFrame.

    Trades must have columns: side, entry_price, exit_price, qty, and either pnl
    or we compute pnl via calculate_pnl. PnL must be in currency (not points).

    initial_capital: must be > 0 for sensible equity % and drawdown %. If 0 or
    missing, defaults to 100_000 and a warning is implied (set config.capital).

    Returns dict with:
        Initial Capital, Total Trades, Win Rate %, Profit Factor, Net Profit,
        Max Drawdown, Max Drawdown %, Avg Win, Avg Loss, Expectancy, Sharpe Ratio.
    """
    trades = trades.copy()

    # Guard: equity curve = capital + cumsum(pnl); avoid division by zero / nonsense %
    cap = float(initial_capital) if initial_capital is not None else 100_000.0
    if cap <= 0:
        cap = 100_000.0

    if trades.empty:
        return {
            "Initial Capital": cap,
            "Total Trades": 0,
            "Win Rate %": 0.0,
            "Profit Factor": 0.0,
            "Net Profit": 0.0,
            "Max Drawdown": 0.0,
            "Max Drawdown %": 0.0,
            "Avg Win": 0.0,
            "Avg Loss": 0.0,
            "Expectancy": 0.0,
            "Sharpe Ratio": 0.0,
        }

    if "pnl" not in trades.columns or trades["pnl"].isna().all():
        trades["pnl"] = trades.apply(calculate_pnl, axis=1)

    total_trades = len(trades)
    wins = trades[trades["pnl"] > 0]
    losses = trades[trades["pnl"] < 0]

    win_rate = (len(wins) / total_trades * 100) if total_trades else 0.0

    gross_profit = wins["pnl"].sum() if len(wins) else 0.0
    gross_loss = abs(losses["pnl"].sum()) if len(losses) else 0.0
    profit_factor = (
        (gross_profit / gross_loss) if gross_loss != 0 else (float("inf") if gross_profit > 0 else 0.0)
    )

    # Equity curve: capital + cumulative realized pnl (margin not modeled)
    trades["equity"] = trades["pnl"].cumsum()
    trades["running_max"] = trades["equity"].cummax()
    trades["drawdown"] = trades["equity"] - trades["running_max"]
    max_drawdown = trades["drawdown"].min()

    # Percentage: (capital + equity) / capital; cap > 0 guaranteed
    trades["equity_pct"] = (cap + trades["equity"]) / cap
    trades["running_max_pct"] = trades["equity_pct"].cummax()
    trades["drawdown_pct"] = trades["equity_pct"] - trades["running_max_pct"]
    max_dd_pct = trades["drawdown_pct"].min() * 100

    # Bonus: Average Win / Average Loss
    avg_win = wins["pnl"].mean() if len(wins) else 0.0
    avg_loss = losses["pnl"].mean() if len(losses) else 0.0
    # Expectancy: (win_rate/100 * avg_win) - ((1 - win_rate/100) * abs(avg_loss))
    expectancy = (win_rate / 100 * avg_win) - ((1 - win_rate / 100) * abs(avg_loss))

    sharpe = sharpe_ratio(trades, initial_capital=cap)

    return {
        "Initial Capital": cap,
        "Total Trades": total_trades,
        "Win Rate %": round(win_rate, 2),
        "Profit Factor": round(profit_factor, 2),
        "Net Profit": round(trades["pnl"].sum(), 2),
        "Max Drawdown": round(max_drawdown, 2),
        "Max Drawdown %": round(max_dd_pct, 2),
        "Avg Win": round(avg_win, 2),
        "Avg Loss": round(avg_loss, 2),
        "Expectancy": round(expectancy, 2),
        "Sharpe Ratio": round(sharpe, 4),
    }


def trades_with_equity_and_drawdown(
    trades: pd.DataFrame,
    initial_capital: float = 100_000,
) -> pd.DataFrame:
    """
    Return a copy of the trades DataFrame with equity curve and drawdown columns added.
    Useful for plotting or further analysis. initial_capital must be > 0.
    """
    out = trades.copy()
    if out.empty:
        return out
    cap = float(initial_capital) if initial_capital and initial_capital > 0 else 100_000.0
    if "pnl" not in out.columns or out["pnl"].isna().all():
        out["pnl"] = out.apply(calculate_pnl, axis=1)
    out["equity"] = out["pnl"].cumsum()
    out["running_max"] = out["equity"].cummax()
    out["drawdown"] = out["equity"] - out["running_max"]
    out["equity_pct"] = (cap + out["equity"]) / cap
    out["running_max_pct"] = out["equity_pct"].cummax()
    out["drawdown_pct"] = out["equity_pct"] - out["running_max_pct"]
    return out


def print_performance_summary(summary: dict) -> None:
    """Print performance summary in a readable format."""
    print("=" * 50)
    print("PERFORMANCE SUMMARY")
    print("=" * 50)
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print("=" * 50)
    pf = summary.get("Profit Factor")
    if pf != 0 and pf != float("inf"):
        if pf < 1:
            print("  Profit Factor interpretation: Losing strategy")
        elif pf < 1.2:
            print("  Profit Factor interpretation: Weak")
        elif pf < 1.5:
            print("  Profit Factor interpretation: Tradable")
        elif pf < 2:
            print("  Profit Factor interpretation: Good")
        else:
            print("  Profit Factor interpretation: Strong")
    if summary.get("Expectancy", 0) > 0:
        print("  Expectancy > 0 → strategy has edge")
    else:
        print("  Expectancy ≤ 0 → no edge")
    print("=" * 50)


if __name__ == "__main__":
    import sys
    import warnings

    # Avoid RuntimeWarning when run as python -m core.analytics.performance (prefer: python -m run.run_analytics)
    warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*sys.modules.*")
    path = sys.argv[1] if len(sys.argv) > 1 else "logs/trade_log.csv"
    strategy = sys.argv[2] if len(sys.argv) > 2 else None
    trades = load_trade_log(path, strategy=strategy)
    if trades.empty:
        print("No trades found in", path)
    else:
        summary = performance_summary(trades)
        print_performance_summary(summary)
