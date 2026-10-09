import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

plt.style.use("ggplot")

###############################################
# CONFIG
###############################################

START = "2020-01-01"
END = None

INITIAL_CAPITAL = 1_000_000
# Production: 7% switch threshold + Always Invested fallback
SWITCH_THRESHOLD_PCTS = [7]
DEFAULT_THRESHOLD_PCT = 7
LOG_DIR = Path("logs/ETF")

# Phase 7 — Defensive regime when no risk-on ETF qualifies (Close < EMA200 / filters fail)
# always = stay invested in top RET126 ETF (ignore trend filters)  ← production
# cash   = sit in cash
# gold   = 100% GOLDBEES (or LIQUIDBEES if set below)
DEFENSIVE_MODES = ["always"]
DEFAULT_DEFENSIVE_MODE = "always"
DEFENSIVE_ETF = "GOLDBEES"  # used only when defensive_mode == "gold"

ETFS = {
    "NIFTYBEES": "NIFTYBEES.NS",
    "BANKBEES": "BANKBEES.NS",
    "MID150BEES": "MID150BEES.NS",
    "GOLDBEES": "GOLDBEES.NS",
    # Optional liquid sleeve — uncomment and set DEFENSIVE_ETF="LIQUIDBEES" to use
    # "LIQUIDBEES": "LIQUIDBEES.NS",
}

###############################################
# Download
###############################################

prices = {}

for name, ticker in ETFS.items():

    df = yf.download(
        ticker,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
    )

    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)

    df = df[["Close"]]
    prices[name] = df

###############################################
# Indicators
###############################################

def rsi(close, period=14):

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


for name in prices:

    df = prices[name]
    df["EMA50"] = df.Close.ewm(span=50).mean()
    df["EMA100"] = df.Close.ewm(span=100).mean()
    df["EMA200"] = df.Close.ewm(span=200).mean()
    df["RSI"] = rsi(df.Close)
    df["RET126"] = df.Close.pct_change(126)

###############################################
# Calendar
###############################################

calendar = prices["NIFTYBEES"].index

###############################################
# Helpers
###############################################

def row_on_or_before(etf, date):

    df = prices[etf]
    if date in df.index:
        return df.loc[date]

    hist = df.loc[:date]
    if hist.empty:
        return None
    return hist.iloc[-1]


def _metrics_from_equity(equity, trade_log, extra=None):

    returns = equity.pct_change().fillna(0)
    years = (calendar[-1] - calendar[0]).days / 365
    cagr = (equity.iloc[-1] / INITIAL_CAPITAL) ** (1 / years) - 1
    total_return = (equity.iloc[-1] / INITIAL_CAPITAL) - 1
    vol = returns.std() * np.sqrt(252)
    sharpe = returns.mean() / returns.std() * np.sqrt(252)
    downside = returns.copy()
    downside[downside > 0] = 0
    sortino = returns.mean() / downside.std() * np.sqrt(252)
    rolling_max = equity.cummax()
    drawdown = (equity - rolling_max) / rolling_max
    maxdd = drawdown.min()
    wins = sum(t["Return %"] > 0 for t in trade_log)
    trades = len(trade_log)
    winrate = wins / max(1, trades)
    avg_hold = np.mean([t["Days"] for t in trade_log]) if trades else 0

    metrics = {
        "final_equity": float(equity.iloc[-1]),
        "total_return_pct": float(total_return * 100),
        "cagr_pct": float(cagr * 100),
        "volatility_pct": float(vol * 100),
        "sharpe": float(sharpe),
        "sortino": float(sortino),
        "max_drawdown_pct": float(maxdd * 100),
        "trades": int(trades),
        "win_rate_pct": float(winrate * 100),
        "avg_hold_days": float(avg_hold),
    }
    if extra:
        metrics.update(extra)
    return metrics, drawdown


def run_backtest(switch_threshold_pct, defensive_mode="cash"):
    """
    Phase 1: momentum switch only if winner_ret - current_ret >= threshold.
    Phase 7: when no risk-on candidate (all fail Close>EMA200 / RSI / EMA50 filters):
      always → invest in highest RET126 ETF (ignore filters)
      cash   → hold cash
      gold   → 100% DEFENSIVE_ETF (GOLDBEES by default)
    """

    cash = INITIAL_CAPITAL
    shares = 0
    current = None
    equity = []
    trade_log = []
    entry_date = None
    entry_price = None
    entry_reason = None

    def portfolio_value(date):
        if current is None:
            return cash
        row = row_on_or_before(current, date)
        if row is None:
            return cash
        return shares * row.Close

    def close_position(date, row, exit_reason, winner=None, winner_ret=None):
        nonlocal cash, shares, current, entry_date, entry_price, entry_reason
        exit_price = float(row.Close)
        cash = shares * exit_price
        current_ret = float(row.RET126) if pd.notna(row.RET126) else None
        trade_log.append(
            {
                "ETF": current,
                "Entry": entry_date,
                "Exit": date,
                "EntryPrice": entry_price,
                "ExitPrice": exit_price,
                "Return %": (exit_price - entry_price) / entry_price * 100,
                "Days": (date - entry_date).days,
                "switch_threshold_pct": switch_threshold_pct,
                "defensive_mode": defensive_mode,
                "entry_reason": entry_reason,
                "winner_at_exit": winner,
                "current_ret126_at_exit": current_ret,
                "winner_ret126_at_exit": winner_ret,
                "exit_reason": exit_reason,
            }
        )
        current = None
        shares = 0
        entry_date = None
        entry_price = None
        entry_reason = None

    def open_position(date, etf, reason):
        nonlocal cash, shares, current, entry_date, entry_price, entry_reason
        row = row_on_or_before(etf, date)
        if row is None:
            return
        px = float(row.Close)
        shares = cash / px
        current = etf
        entry_date = date
        entry_price = px
        entry_reason = reason
        cash = 0

    for date in calendar:

        if date.weekday() != 4:
            equity.append(portfolio_value(date))
            continue

        # Risk-on candidates: Close > EMA200, RSI > 55, EMA50 > EMA200
        candidates = []
        # Always-invested ranking: any ETF with valid RET126
        all_ranked = []

        for etf in prices:
            df = prices[etf]
            if date not in df.index:
                continue
            row = df.loc[date]
            if pd.isna(row.RET126):
                continue

            ret = float(row.RET126)
            all_ranked.append((etf, ret, float(row.Close), float(row.EMA200)))

            cond = (
                row.Close > row.EMA200
                and row.RSI > 55
                and row.EMA50 > row.EMA200
            )
            if cond:
                candidates.append((etf, ret))

        candidates = sorted(candidates, key=lambda x: x[1], reverse=True)
        all_ranked = sorted(all_ranked, key=lambda x: x[1], reverse=True)

        winner = candidates[0][0] if candidates else None
        winner_ret = candidates[0][1] if candidates else None

        # Phase 7: no risk-on ETF above EMA200 (filters fail) → defensive
        defensive = winner is None
        best_any = all_ranked[0] if all_ranked else None
        best_below_ema200 = (
            best_any is not None and best_any[2] < best_any[3]
        )

        target = None
        target_reason = None

        if not defensive:
            target = winner
            target_reason = "risk_on_top_momentum"
        else:
            # Defensive regime
            if defensive_mode == "cash":
                target = None
                target_reason = "defensive_cash"
            elif defensive_mode == "gold":
                if DEFENSIVE_ETF in prices:
                    target = DEFENSIVE_ETF
                    target_reason = (
                        "defensive_gold"
                        if best_below_ema200 or defensive
                        else "defensive_gold"
                    )
                else:
                    target = None
                    target_reason = "defensive_cash_fallback"
            elif defensive_mode == "always":
                # Stay invested: pick highest RET126 ignoring trend filters
                if best_any is not None:
                    target = best_any[0]
                    target_reason = "always_invested_top_ret126"
                else:
                    target = None
                    target_reason = "always_no_data"
            else:
                raise ValueError(f"Unknown defensive_mode={defensive_mode}")

        #######################################
        # EXIT
        #######################################
        if current is not None:
            row = row_on_or_before(current, date)
            if row is None:
                equity.append(portfolio_value(date))
                continue

            current_ret = float(row.RET126) if pd.notna(row.RET126) else None
            holding_defensive_gold = (
                defensive_mode == "gold"
                and current == DEFENSIVE_ETF
                and entry_reason == "defensive_gold"
            )
            # While parked in gold sleeve, ignore EMA100 trend exits — leave only
            # when a risk-on winner reappears (or always/cash rules below).
            trend_break = bool(row.Close < row.EMA100) and not holding_defensive_gold

            # Risk-on rotation (only when we have a risk-on winner different from current)
            winner_changed = bool(winner is not None and winner != current)
            momentum_switch_ok = False
            if (
                winner_changed
                and winner_ret is not None
                and current_ret is not None
                and not holding_defensive_gold
            ):
                momentum_switch_ok = (winner_ret - current_ret) >= (
                    switch_threshold_pct / 100.0
                )

            # From risk-on → defensive gold/cash, or gold → risk-on, or always rebalance
            defensive_rotate = False
            if defensive and defensive_mode == "gold" and current != DEFENSIVE_ETF:
                defensive_rotate = True
            if defensive and defensive_mode == "cash":
                defensive_rotate = True  # exit to cash
            if (
                defensive
                and defensive_mode == "always"
                and target is not None
                and target != current
            ):
                # For always mode, still require momentum gap to reduce churn
                if current_ret is not None and best_any is not None:
                    gap = best_any[1] - current_ret
                    defensive_rotate = gap >= (switch_threshold_pct / 100.0)
                else:
                    defensive_rotate = True
            # Leave gold only when a *different* risk-on ETF qualifies
            if (
                (not defensive)
                and holding_defensive_gold
                and winner is not None
                and winner != current
            ):
                defensive_rotate = True

            should_exit = (
                trend_break
                or (winner_changed and momentum_switch_ok)
                or defensive_rotate
            )

            if should_exit:
                reasons = []
                if trend_break:
                    reasons.append("trend_failed_close_below_ema100")
                if winner_changed and momentum_switch_ok:
                    reasons.append(
                        f"winner_changed_momentum_gap_ge_{switch_threshold_pct:.1f}pct"
                    )
                if defensive and defensive_mode == "cash":
                    reasons.append("defensive_regime_to_cash")
                if defensive and defensive_mode == "gold" and current != DEFENSIVE_ETF:
                    reasons.append(f"defensive_regime_to_{DEFENSIVE_ETF}")
                if (
                    (not defensive)
                    and holding_defensive_gold
                    and winner is not None
                    and winner != current
                ):
                    reasons.append("leave_defensive_gold_risk_on")
                if (
                    defensive
                    and defensive_mode == "always"
                    and target is not None
                    and target != current
                ):
                    reasons.append("always_invested_rebalance")
                if not reasons:
                    reasons.append("rebalance")

                close_position(
                    date,
                    row,
                    "|".join(reasons),
                    winner=winner if winner is not None else target,
                    winner_ret=winner_ret
                    if winner_ret is not None
                    else (best_any[1] if best_any else None),
                )

        #######################################
        # ENTRY
        #######################################
        if current is None and target is not None:
            open_position(date, target, target_reason)

        equity.append(portfolio_value(date))

    equity = pd.Series(equity, index=calendar)
    metrics, drawdown = _metrics_from_equity(
        equity,
        trade_log,
        extra={
            "switch_threshold_pct": switch_threshold_pct,
            "defensive_mode": defensive_mode,
            "defensive_etf": DEFENSIVE_ETF if defensive_mode == "gold" else "",
        },
    )
    return metrics, trade_log, equity, drawdown


###############################################
# Phase 1 — threshold sweep (cash defensive, baseline)
###############################################

LOG_DIR.mkdir(parents=True, exist_ok=True)
all_metrics = []
default_metrics = None
default_trades = None
default_equity = None
default_drawdown = None

for th in SWITCH_THRESHOLD_PCTS:
    metrics, trades_out, equity_out, drawdown_out = run_backtest(
        th, defensive_mode="cash"
    )
    all_metrics.append(metrics)
    pd.DataFrame(trades_out).to_csv(
        LOG_DIR / f"trade_log_threshold_{int(th)}.csv",
        index=False,
    )
    if int(th) == int(DEFAULT_THRESHOLD_PCT):
        default_metrics = metrics
        default_trades = trades_out
        default_equity = equity_out
        default_drawdown = drawdown_out

summary_df = pd.DataFrame(all_metrics).sort_values("switch_threshold_pct")
summary_df.to_csv(LOG_DIR / "threshold_summary.csv", index=False)

###############################################
# Phase 7 — Always invested vs Cash vs Gold
###############################################

phase7_metrics = []
phase7_equities = {}

for mode in DEFENSIVE_MODES:
    metrics, trades_out, equity_out, drawdown_out = run_backtest(
        DEFAULT_THRESHOLD_PCT, defensive_mode=mode
    )
    phase7_metrics.append(metrics)
    phase7_equities[mode] = equity_out
    pd.DataFrame(trades_out).to_csv(
        LOG_DIR / f"trade_log_defensive_{mode}.csv",
        index=False,
    )
    pd.DataFrame({"Equity": equity_out, "Drawdown": drawdown_out}).to_csv(
        LOG_DIR / f"portfolio_defensive_{mode}.csv"
    )

phase7_df = pd.DataFrame(phase7_metrics).sort_values("defensive_mode")
phase7_df.to_csv(LOG_DIR / "defensive_regime_summary.csv", index=False)

# Prefer production defaults as the published trade log / portfolio
default_metrics, default_trades, default_equity, default_drawdown = run_backtest(
    DEFAULT_THRESHOLD_PCT, defensive_mode=DEFAULT_DEFENSIVE_MODE
)

###############################################
# Print
###############################################

print()
print("=" * 60)
print("ETF ROTATION BACKTEST — Phase 7 Defensive Regime")
print("=" * 60)
print(f"Switch Threshold : {DEFAULT_THRESHOLD_PCT}%")
print(
    f"Default Defensive: {DEFAULT_DEFENSIVE_MODE}"
    + (f" ({DEFENSIVE_ETF})" if DEFAULT_DEFENSIVE_MODE == "gold" else "")
)
print(f"Initial Capital  : {INITIAL_CAPITAL:,.0f}")
print()
print("--- Always invested vs Cash vs Gold ---")
print(
    phase7_df[
        [
            "defensive_mode",
            "final_equity",
            "cagr_pct",
            "sharpe",
            "max_drawdown_pct",
            "trades",
            "avg_hold_days",
        ]
    ].to_string(index=False)
)
print()
print(f"[{DEFAULT_DEFENSIVE_MODE.upper()}] Final Equity : {default_metrics['final_equity']:,.0f}")
print(f"[{DEFAULT_DEFENSIVE_MODE.upper()}] Total Return : {default_metrics['total_return_pct']:.2f}%")
print(f"[{DEFAULT_DEFENSIVE_MODE.upper()}] CAGR         : {default_metrics['cagr_pct']:.2f}%")
print(f"[{DEFAULT_DEFENSIVE_MODE.upper()}] Volatility   : {default_metrics['volatility_pct']:.2f}%")
print(f"[{DEFAULT_DEFENSIVE_MODE.upper()}] Sharpe       : {default_metrics['sharpe']:.2f}")
print(f"[{DEFAULT_DEFENSIVE_MODE.upper()}] Sortino      : {default_metrics['sortino']:.2f}")
print(f"[{DEFAULT_DEFENSIVE_MODE.upper()}] Max Drawdown : {default_metrics['max_drawdown_pct']:.2f}%")
print(f"[{DEFAULT_DEFENSIVE_MODE.upper()}] Trades       : {int(default_metrics['trades'])}")
print(f"[{DEFAULT_DEFENSIVE_MODE.upper()}] Win Rate     : {default_metrics['win_rate_pct']:.2f}%")
print(f"[{DEFAULT_DEFENSIVE_MODE.upper()}] Avg Hold Days: {default_metrics['avg_hold_days']:.1f}")
print("=" * 60)

###############################################
# Save CSV
###############################################

pd.DataFrame(default_trades).to_csv(LOG_DIR / "trade_log.csv", index=False)

portfolio = pd.DataFrame(
    {
        "Equity": default_equity,
        "Drawdown": default_drawdown,
    }
)
portfolio.to_csv(LOG_DIR / "portfolio.csv")

###############################################
# Charts
###############################################

plt.figure(figsize=(14, 6))
for mode, eq in phase7_equities.items():
    plt.plot(eq, label=f"defensive={mode}")
plt.title("Phase 7 — Always vs Cash vs Gold")
plt.legend()
plt.show()

plt.figure(figsize=(14, 4))
plt.fill_between(
    default_drawdown.index,
    default_drawdown.values,
    0,
)
plt.title(f"Drawdown ({DEFAULT_DEFENSIVE_MODE})")
plt.show()
