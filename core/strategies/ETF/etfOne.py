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
SWITCH_THRESHOLD_PCTS = [0, 3, 5, 7, 10]
DEFAULT_THRESHOLD_PCT = 5
LOG_DIR = Path("logs/ETF")

ETFS = {
    "NIFTYBEES":"NIFTYBEES.NS",
    "BANKBEES":"BANKBEES.NS",
    "MID150BEES":"MID150BEES.NS",
    "GOLDBEES":"GOLDBEES.NS"
}

###############################################
# Download
###############################################

prices = {}

for name,ticker in ETFS.items():

    df = yf.download(
        ticker,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False
    )

    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)

    df=df[['Close']]

    prices[name]=df

###############################################
# Indicators
###############################################

def rsi(close,period=14):

    delta=close.diff()

    gain=delta.clip(lower=0)

    loss=-delta.clip(upper=0)

    avg_gain=gain.rolling(period).mean()

    avg_loss=loss.rolling(period).mean()

    rs=avg_gain/avg_loss

    return 100-(100/(1+rs))


for name in prices:

    df=prices[name]

    df["EMA50"]=df.Close.ewm(span=50).mean()

    df["EMA100"]=df.Close.ewm(span=100).mean()

    df["EMA200"]=df.Close.ewm(span=200).mean()

    df["RSI"]=rsi(df.Close)

    df["RET126"]=df.Close.pct_change(126)

###############################################
# Calendar
###############################################

calendar=prices["NIFTYBEES"].copy()

calendar=calendar.index

###############################################
# Portfolio
###############################################

def row_on_or_before(etf, date):

    df = prices[etf]
    if date in df.index:
        return df.loc[date]

    hist = df.loc[:date]
    if hist.empty:
        return None
    return hist.iloc[-1]

def run_backtest(switch_threshold_pct):

    cash=INITIAL_CAPITAL
    shares=0
    current=None
    equity=[]
    trade_log=[]
    entry_date=None
    entry_price=None

    def portfolio_value(date):
        if current is None:
            return cash
        row = row_on_or_before(current, date)
        if row is None:
            return cash
        return shares*row.Close

    for date in calendar:

        if date.weekday()!=4:
            equity.append(portfolio_value(date))
            continue

        candidates=[]

        for etf in prices:
            df=prices[etf]
            if date not in df.index:
                continue

            row=df.loc[date]
            if pd.isna(row.RET126):
                continue

            cond=(
                row.Close>row.EMA200 and
                row.RSI>55 and
                row.EMA50>row.EMA200
            )

            if cond:
                candidates.append(
                    (etf,float(row.RET126))
                )

        candidates=sorted(
            candidates,
            key=lambda x:x[1],
            reverse=True
        )

        winner=None
        winner_ret=None
        if len(candidates):
            winner=candidates[0][0]
            winner_ret=candidates[0][1]

        #######################################
        # EXIT
        #######################################
        if current is not None:
            row=row_on_or_before(current, date)
            if row is None:
                equity.append(portfolio_value(date))
                continue

            current_ret = float(row.RET126) if pd.notna(row.RET126) else None
            trend_break = bool(row.Close<row.EMA100)
            winner_changed = bool(winner is not None and winner!=current)

            momentum_switch_ok = False
            if winner_changed and winner_ret is not None and current_ret is not None:
                momentum_switch_ok = (winner_ret-current_ret) >= (switch_threshold_pct/100.0)

            should_exit = trend_break or (winner_changed and momentum_switch_ok)

            if should_exit:
                exit_price=row.Close
                cash=shares*exit_price

                exit_reason=[]
                if trend_break:
                    exit_reason.append("trend_failed_close_below_ema100")
                if winner_changed and momentum_switch_ok:
                    exit_reason.append(
                        f"winner_changed_momentum_gap_ge_{switch_threshold_pct:.1f}pct"
                    )

                trade_log.append({
                    "ETF":current,
                    "Entry":entry_date,
                    "Exit":date,
                    "EntryPrice":entry_price,
                    "ExitPrice":exit_price,
                    "Return %":(exit_price-entry_price)/entry_price*100,
                    "Days":(date-entry_date).days,
                    "switch_threshold_pct":switch_threshold_pct,
                    "winner_at_exit":winner,
                    "current_ret126_at_exit":current_ret,
                    "winner_ret126_at_exit":winner_ret,
                    "exit_reason":"|".join(exit_reason) if exit_reason else "unknown",
                })

                current=None
                shares=0

        #######################################
        # ENTRY
        #######################################
        if current is None and winner is not None:
            row = row_on_or_before(winner, date)
            if row is not None:
                px=row.Close
                shares=cash/px
                current=winner
                entry_date=date
                entry_price=px
                cash=0

        equity.append(portfolio_value(date))

    equity=pd.Series(equity,index=calendar)
    returns=equity.pct_change().fillna(0)
    years=(calendar[-1]-calendar[0]).days/365
    cagr=(equity.iloc[-1]/INITIAL_CAPITAL)**(1/years)-1
    total_return=(equity.iloc[-1]/INITIAL_CAPITAL)-1
    vol=returns.std()*np.sqrt(252)
    sharpe=returns.mean()/returns.std()*np.sqrt(252)
    downside=returns.copy()
    downside[downside>0]=0
    sortino=returns.mean()/downside.std()*np.sqrt(252)
    rolling_max=equity.cummax()
    drawdown=(equity-rolling_max)/rolling_max
    maxdd=drawdown.min()
    wins=sum(t["Return %"]>0 for t in trade_log)
    trades=len(trade_log)
    winrate=wins/max(1,trades)
    avg_hold=np.mean([t["Days"] for t in trade_log]) if trades else 0

    metrics = {
        "switch_threshold_pct": switch_threshold_pct,
        "final_equity": float(equity.iloc[-1]),
        "total_return_pct": float(total_return*100),
        "cagr_pct": float(cagr*100),
        "volatility_pct": float(vol*100),
        "sharpe": float(sharpe),
        "sortino": float(sortino),
        "max_drawdown_pct": float(maxdd*100),
        "trades": int(trades),
        "win_rate_pct": float(winrate*100),
        "avg_hold_days": float(avg_hold),
    }
    return metrics, trade_log, equity, drawdown

###############################################
# Results
###############################################

LOG_DIR.mkdir(parents=True, exist_ok=True)
all_metrics=[]
default_metrics=None
default_trades=None
default_equity=None
default_drawdown=None

for th in SWITCH_THRESHOLD_PCTS:
    metrics, trades_out, equity_out, drawdown_out = run_backtest(th)
    all_metrics.append(metrics)
    pd.DataFrame(trades_out).to_csv(
        LOG_DIR / f"trade_log_threshold_{int(th)}.csv",
        index=False
    )
    if int(th)==int(DEFAULT_THRESHOLD_PCT):
        default_metrics=metrics
        default_trades=trades_out
        default_equity=equity_out
        default_drawdown=drawdown_out

summary_df=pd.DataFrame(all_metrics).sort_values("switch_threshold_pct")
summary_df.to_csv(LOG_DIR / "threshold_summary.csv", index=False)

if default_metrics is None:
    default_metrics, default_trades, default_equity, default_drawdown = run_backtest(DEFAULT_THRESHOLD_PCT)
    pd.DataFrame(default_trades).to_csv(
        LOG_DIR / f"trade_log_threshold_{int(DEFAULT_THRESHOLD_PCT)}.csv",
        index=False
    )

###############################################
# Print
###############################################

print()

print("="*60)

print("ETF ROTATION BACKTEST")

print("="*60)

print(f"Switch Threshold: {DEFAULT_THRESHOLD_PCT}%")
print(f"Initial Capital : {INITIAL_CAPITAL:,.0f}")
print(f"Final Equity    : {default_metrics['final_equity']:,.0f}")
print(f"Total Return    : {default_metrics['total_return_pct']:.2f}%")
print(f"CAGR            : {default_metrics['cagr_pct']:.2f}%")
print(f"Volatility      : {default_metrics['volatility_pct']:.2f}%")
print(f"Sharpe          : {default_metrics['sharpe']:.2f}")
print(f"Sortino         : {default_metrics['sortino']:.2f}")
print(f"Max Drawdown    : {default_metrics['max_drawdown_pct']:.2f}%")
print(f"Trades          : {int(default_metrics['trades'])}")
print(f"Win Rate        : {default_metrics['win_rate_pct']:.2f}%")
print(f"Avg Hold Days   : {default_metrics['avg_hold_days']:.1f}")

print("="*60)

###############################################
# Save CSV
###############################################

pd.DataFrame(default_trades).to_csv(
    LOG_DIR / "trade_log.csv",
    index=False
)

portfolio=pd.DataFrame({

    "Equity":default_equity,

    "Drawdown":default_drawdown

})

portfolio.to_csv(
    LOG_DIR / "portfolio.csv"
)

###############################################
# Charts
###############################################

plt.figure(figsize=(14,6))

plt.plot(
    default_equity,
    label="Portfolio"
)

plt.title("Equity Curve")

plt.legend()

plt.show()

plt.figure(figsize=(14,4))

plt.fill_between(
    default_drawdown.index,
    default_drawdown.values,
    0
)

plt.title("Drawdown")

plt.show()