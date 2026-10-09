#!/usr/bin/env python3
"""
Nifty 500 Equity Momentum — weekly equal-weight backtest.

Production rules (aligned with ETF etfOne Phase 1 + always-invested spirit):
  Universe      : Nifty 500
  Rebalance     : Every Friday
  Trend         : Close > EMA200
  Confirmation  : EMA50 > EMA200
  Momentum      : Composite mean of RET252, RET126, RET63
  RSI           : RSI(14) > 55
  Liquidity     : 20d average traded value (Close*Volume) >= MIN_ADV_INR
  Portfolio     : Top TOP_N stocks, equal weight
  Switch rule   : Replace a holding only if challenger composite momentum
                  exceeds that holding by >= SWITCH_THRESHOLD_PCT (default 7%)

Run:
  cd /root/Dhan-codebase
  source .venv/bin/activate
  MPLBACKEND=Agg python3 core/strategies/Equity/MomentumStocks/momentum_stocks.py

Optional env / config knobs at top of file:
  MAX_SYMBOLS   — limit universe for smoke tests (None = full Nifty 500)
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

plt.style.use("ggplot")

###############################################
# CONFIG — production defaults
###############################################

START = "2020-01-01"
END = None

INITIAL_CAPITAL = 1_000_000
TOP_N = 10
SWITCH_THRESHOLD_PCT = 7.0
RSI_MIN = 55.0
MIN_ADV_INR = 50_000_000  # ₹5 crore average daily value
MIN_PRICE = 20.0
COMPOSITE_WEIGHTS = {"RET252": 1.0, "RET126": 1.0, "RET63": 1.0}

# Smoke-test: set to e.g. 80 to download faster; None = full Nifty 500
MAX_SYMBOLS: Optional[int] = None

REPO_ROOT = Path(__file__).resolve().parents[4]
UNIVERSE_CSV = REPO_ROOT / "Dependencies" / "universe" / "ind_nifty500list.csv"
PRICE_CACHE = REPO_ROOT / "Dependencies" / "universe" / "nifty500_ohlcv_cache.pkl"
LOG_DIR = REPO_ROOT / "logs" / "MomentumStocks"

###############################################
# Universe
###############################################


def load_nifty500_symbols(
    csv_path: Path = UNIVERSE_CSV,
    max_symbols: Optional[int] = MAX_SYMBOLS,
) -> List[str]:
    if not csv_path.is_file():
        raise FileNotFoundError(
            f"Nifty 500 list missing: {csv_path}. "
            "Download from NSE archives ind_nifty500list.csv"
        )
    df = pd.read_csv(csv_path)
    col = "Symbol" if "Symbol" in df.columns else df.columns[2]
    symbols = (
        df[col]
        .astype(str)
        .str.strip()
        .tolist()
    )
    # yfinance NSE suffix — keep NSE ticker text as-is (e.g. M&M.NS)
    tickers = [f"{s}.NS" for s in symbols if s and s.lower() != "nan"]
    if max_symbols:
        tickers = tickers[: int(max_symbols)]
    return tickers


###############################################
# Download + indicators
###############################################


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        # yfinance multi-ticker: level0=field, level1=ticker OR reverse depending on version
        # Prefer Wide OHLCV with MultiIndex (Field, Ticker)
        return df
    return df


def download_universe(
    tickers: List[str],
    start: str = START,
    end: Optional[str] = END,
    cache_path: Path = PRICE_CACHE,
    force: bool = False,
) -> pd.DataFrame:
    """
    Returns MultiIndex columns DataFrame: (field, ticker) for Open/High/Low/Close/Volume.
    Cached to parquet for reruns.
    """
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.is_file() and not force:
        cached = pd.read_pickle(cache_path)
        have = set(cached.columns.get_level_values(1).unique())
        need = set(tickers)
        if need.issubset(have):
            print(f"Loaded price cache: {cache_path} ({len(need)} symbols)")
            return cached.loc[:, pd.IndexSlice[:, list(need)]]

    print(f"Downloading {len(tickers)} symbols from Yahoo ({start} → {end or 'today'}) …")
    t0 = time.time()
    raw = yf.download(
        tickers=tickers,
        start=start,
        end=end,
        auto_adjust=True,
        progress=True,
        group_by="ticker",
        threads=True,
    )
    print(f"Download done in {time.time() - t0:.1f}s")

    # Normalize to (Field, Ticker) MultiIndex
    if isinstance(raw.columns, pd.MultiIndex):
        # group_by=ticker → (Ticker, Field)
        lvl0 = raw.columns.get_level_values(0)
        if any(str(x).endswith(".NS") for x in lvl0[: min(5, len(lvl0))]):
            raw = raw.swaplevel(0, 1, axis=1).sort_index(axis=1)
    else:
        # Single ticker edge case
        raw.columns = pd.MultiIndex.from_product([raw.columns, [tickers[0]]])

    # Keep OHLCV only
    fields = [
        c
        for c in ["Open", "High", "Low", "Close", "Volume"]
        if c in raw.columns.get_level_values(0)
    ]
    raw = raw[fields].copy()
    raw.to_pickle(cache_path)
    print(f"Cached → {cache_path}")
    available = [t for t in tickers if t in raw.columns.get_level_values(1)]
    return raw.loc[:, pd.IndexSlice[:, available]]


def rsi_series(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def build_panel(ohlcv: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Per-symbol DataFrame with Close, Volume, EMAs, RSI, returns, ADV, composite."""
    tickers = sorted(set(ohlcv.columns.get_level_values(1)))
    panel: Dict[str, pd.DataFrame] = {}
    w = COMPOSITE_WEIGHTS
    wsum = sum(w.values()) or 1.0

    for t in tickers:
        try:
            close = ohlcv[("Close", t)].dropna()
            vol = ohlcv[("Volume", t)].reindex(close.index).fillna(0.0)
        except KeyError:
            continue
        if len(close) < 260:
            continue

        df = pd.DataFrame({"Close": close, "Volume": vol})
        df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
        df["EMA200"] = df["Close"].ewm(span=200, adjust=False).mean()
        df["RSI"] = rsi_series(df["Close"], 14)
        df["RET252"] = df["Close"].pct_change(252)
        df["RET126"] = df["Close"].pct_change(126)
        df["RET63"] = df["Close"].pct_change(63)
        df["ADV"] = (df["Close"] * df["Volume"]).rolling(20).mean()
        df["COMPOSITE"] = (
            w["RET252"] * df["RET252"]
            + w["RET126"] * df["RET126"]
            + w["RET63"] * df["RET63"]
        ) / wsum
        panel[t] = df

    print(f"Indicators ready for {len(panel)} symbols")
    return panel


###############################################
# Ranking helpers
###############################################


def row_on_or_before(df: pd.DataFrame, date: pd.Timestamp) -> Optional[pd.Series]:
    if date in df.index:
        return df.loc[date]
    hist = df.loc[:date]
    if hist.empty:
        return None
    return hist.iloc[-1]


def passes_filters(row: pd.Series) -> bool:
    try:
        if pd.isna(row["COMPOSITE"]) or pd.isna(row["RSI"]) or pd.isna(row["EMA200"]):
            return False
        if float(row["Close"]) < MIN_PRICE:
            return False
        if float(row["Close"]) <= float(row["EMA200"]):
            return False
        if float(row["EMA50"]) <= float(row["EMA200"]):
            return False
        if float(row["RSI"]) <= RSI_MIN:
            return False
        if float(row["ADV"]) < MIN_ADV_INR:
            return False
        return True
    except (TypeError, ValueError, KeyError):
        return False


def rank_candidates(
    panel: Dict[str, pd.DataFrame], date: pd.Timestamp
) -> List[Tuple[str, float]]:
    """Return [(ticker, composite)] sorted desc among filter passers."""
    out: List[Tuple[str, float]] = []
    for t, df in panel.items():
        row = row_on_or_before(df, date)
        if row is None or not passes_filters(row):
            continue
        out.append((t, float(row["COMPOSITE"])))
    out.sort(key=lambda x: x[1], reverse=True)
    return out


def select_portfolio(
    current: List[str],
    ranked: List[Tuple[str, float]],
    threshold_pct: float = SWITCH_THRESHOLD_PCT,
    top_n: int = TOP_N,
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """
    Build next holdings from ranked candidates with hysteresis:
    - Keep current names that still qualify
    - Fill empty slots with best not-held candidates
    - Swap worst holding for a challenger only if
      challenger_score - holding_score >= threshold_pct/100
    """
    events: List[Dict[str, Any]] = []
    score = {t: s for t, s in ranked}
    eligible = [t for t, _ in ranked]
    eligible_set = set(eligible)

    # Drop names that failed filters
    kept = [t for t in current if t in eligible_set]
    for t in current:
        if t not in eligible_set:
            events.append({"action": "DROP_FILTER", "symbol": t, "reason": "failed_filters"})

    thr = threshold_pct / 100.0

    # Fill up to top_n with best outsiders
    for t, s in ranked:
        if len(kept) >= top_n:
            break
        if t not in kept:
            kept.append(t)
            events.append(
                {
                    "action": "ADD",
                    "symbol": t,
                    "score": s,
                    "reason": "fill_slot",
                }
            )

    # Replacement with hysteresis: challengers vs worst holdings
    # Repeat until no beneficial swap under threshold rule
    changed = True
    while changed and kept:
        changed = False
        held_scores = sorted(
            [(t, score[t]) for t in kept if t in score],
            key=lambda x: x[1],
        )
        if not held_scores:
            break
        worst_t, worst_s = held_scores[0]
        for t, s in ranked:
            if t in kept:
                continue
            if (s - worst_s) >= thr:
                kept.remove(worst_t)
                kept.append(t)
                events.append(
                    {
                        "action": "REPLACE",
                        "symbol": t,
                        "score": s,
                        "replaced": worst_t,
                        "replaced_score": worst_s,
                        "gap_pct": (s - worst_s) * 100,
                        "reason": f"momentum_gap_ge_{threshold_pct:.1f}pct",
                    }
                )
                changed = True
                break
            # ranked desc — once gap too small vs worst, stop
            if s <= worst_s:
                break

    # Cap / prefer highest scores among kept if somehow > top_n
    if len(kept) > top_n:
        kept = [
            t
            for t, _ in sorted(
                [(t, score.get(t, -1e9)) for t in kept],
                key=lambda x: x[1],
                reverse=True,
            )[:top_n]
        ]

    return kept, events


###############################################
# Backtest
###############################################


def run_backtest(
    panel: Dict[str, pd.DataFrame],
    switch_threshold_pct: float = SWITCH_THRESHOLD_PCT,
    top_n: int = TOP_N,
) -> Tuple[
    Dict[str, Any],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    pd.Series,
    pd.Series,
    pd.DataFrame,
]:
    best_t = max(panel.keys(), key=lambda t: len(panel[t]))
    calendar = panel[best_t].index

    cash = float(INITIAL_CAPITAL)
    holdings: Dict[str, float] = {}  # symbol -> shares
    # Open lot cost basis for round-trip MTM
    open_lots: Dict[str, Dict[str, Any]] = {}
    # symbol -> {entry_date, entry_price (avg), shares, cost}
    current_names: List[str] = []
    equity_curve: List[float] = []
    fills: List[Dict[str, Any]] = []
    closed_trades: List[Dict[str, Any]] = []
    weight_log: List[Dict[str, Any]] = []

    def mark_to_market(date: pd.Timestamp) -> float:
        total = cash
        for sym, sh in holdings.items():
            df = panel.get(sym)
            if df is None:
                continue
            row = row_on_or_before(df, date)
            if row is None:
                continue
            total += sh * float(row["Close"])
        return total

    def record_fill(
        date: pd.Timestamp,
        sym: str,
        side: str,
        shares: float,
        px: float,
        reason: str,
    ) -> None:
        fills.append(
            {
                "Date": date,
                "Symbol": sym,
                "Side": side,
                "Shares": shares,
                "Price": px,
                "Notional": shares * px,
                "Reason": reason,
            }
        )

    def buy_lot(date: pd.Timestamp, sym: str, shares: float, px: float) -> None:
        if shares <= 0:
            return
        lot = open_lots.get(sym)
        if lot is None:
            open_lots[sym] = {
                "entry_date": date,
                "entry_price": px,
                "shares": shares,
                "cost": shares * px,
            }
        else:
            new_shares = lot["shares"] + shares
            new_cost = lot["cost"] + shares * px
            lot["shares"] = new_shares
            lot["cost"] = new_cost
            lot["entry_price"] = new_cost / new_shares if new_shares > 0 else px

    def sell_lot(
        date: pd.Timestamp,
        sym: str,
        shares: float,
        px: float,
        reason: str,
        *,
        close_fully: bool,
    ) -> None:
        lot = open_lots.get(sym)
        if lot is None or shares <= 0:
            return
        sell_sh = min(shares, lot["shares"])
        if close_fully or sell_sh >= lot["shares"] - 1e-12:
            entry_px = float(lot["entry_price"])
            entry_dt = lot["entry_date"]
            sh = float(lot["shares"])
            mtm = (px - entry_px) * sh
            ret_pct = (px / entry_px - 1.0) * 100.0 if entry_px else 0.0
            days = (pd.Timestamp(date) - pd.Timestamp(entry_dt)).days
            closed_trades.append(
                {
                    "Symbol": sym,
                    "Shares": sh,
                    "EntryDate": entry_dt,
                    "EntryPrice": entry_px,
                    "ExitDate": date,
                    "ExitPrice": px,
                    "MTM": mtm,
                    "Return_%": ret_pct,
                    "Days": days,
                    "ExitReason": reason,
                }
            )
            open_lots.pop(sym, None)
        else:
            # Partial sell (rebalance trim): reduce cost basis proportionally
            frac = sell_sh / lot["shares"]
            lot["shares"] -= sell_sh
            lot["cost"] *= 1.0 - frac
            if lot["shares"] > 0:
                lot["entry_price"] = lot["cost"] / lot["shares"]

    def liquidate_to_cash(date: pd.Timestamp, reason: str) -> None:
        nonlocal cash, holdings
        for sym, sh in list(holdings.items()):
            df = panel[sym]
            row = row_on_or_before(df, date)
            if row is None:
                continue
            px = float(row["Close"])
            cash += sh * px
            record_fill(date, sym, "SELL", sh, px, reason)
            sell_lot(date, sym, sh, px, reason, close_fully=True)
        holdings = {}

    def rebalance_equal(
        date: pd.Timestamp, names: List[str], events: List[Dict[str, Any]]
    ) -> None:
        nonlocal cash, holdings, current_names
        if not names:
            if holdings:
                liquidate_to_cash(date, "empty_book")
            current_names = []
            return

        # Sell names leaving the book
        leaving = [s for s in list(holdings.keys()) if s not in names]
        for sym in leaving:
            sh = holdings.pop(sym)
            row = row_on_or_before(panel[sym], date)
            if row is None:
                continue
            px = float(row["Close"])
            cash += sh * px
            reason = "exit"
            for ev in events:
                if ev.get("action") == "DROP_FILTER" and ev.get("symbol") == sym:
                    reason = "failed_filters"
                if ev.get("action") == "REPLACE" and ev.get("replaced") == sym:
                    reason = ev.get("reason", "replace")
            record_fill(date, sym, "SELL", sh, px, reason)
            sell_lot(date, sym, sh, px, reason, close_fully=True)

        # Total equity after sells
        equity = mark_to_market(date)
        target_notional = equity / len(names)

        # Adjust each name to equal weight
        for sym in names:
            row = row_on_or_before(panel[sym], date)
            if row is None:
                continue
            px = float(row["Close"])
            if px <= 0:
                continue
            target_shares = target_notional / px
            cur_shares = holdings.get(sym, 0.0)
            delta = target_shares - cur_shares
            if abs(delta) * px < 1.0:
                holdings[sym] = target_shares
                continue
            if delta > 0:
                cost = delta * px
                if cost > cash + 1:
                    delta = cash / px
                    cost = delta * px
                cash -= cost
                holdings[sym] = cur_shares + delta
                reason = "rebalance_equal" if cur_shares > 0 else "entry"
                record_fill(date, sym, "BUY", delta, px, reason)
                buy_lot(date, sym, delta, px)
            else:
                proceeds = (-delta) * px
                cash += proceeds
                holdings[sym] = cur_shares + delta
                record_fill(date, sym, "SELL", -delta, px, "rebalance_equal")
                sell_lot(
                    date, sym, -delta, px, "rebalance_equal", close_fully=False
                )
                if holdings[sym] <= 1e-12:
                    holdings.pop(sym, None)
                    # if lot somehow remains with ~0 shares, drop it
                    if sym in open_lots and open_lots[sym]["shares"] <= 1e-12:
                        open_lots.pop(sym, None)

        current_names = list(names)
        eq = mark_to_market(date)
        snap = {"Date": date, "Equity": eq}
        for sym in names:
            row = row_on_or_before(panel[sym], date)
            sh = holdings.get(sym, 0.0)
            px = float(row["Close"]) if row is not None else 0.0
            snap[sym] = (sh * px / eq) if eq > 0 else 0.0
        weight_log.append(snap)

    for date in calendar:
        if date.weekday() != 4:
            equity_curve.append(mark_to_market(date))
            continue

        ranked = rank_candidates(panel, date)
        next_names, events = select_portfolio(
            current_names,
            ranked,
            threshold_pct=switch_threshold_pct,
            top_n=top_n,
        )
        rebalance_equal(date, next_names, events)
        equity_curve.append(mark_to_market(date))

    # Mark open lots to last close as unrealized MTM rows
    last_date = calendar[-1]
    for sym, lot in list(open_lots.items()):
        row = row_on_or_before(panel[sym], last_date)
        if row is None:
            continue
        px = float(row["Close"])
        entry_px = float(lot["entry_price"])
        sh = float(lot["shares"])
        mtm = (px - entry_px) * sh
        ret_pct = (px / entry_px - 1.0) * 100.0 if entry_px else 0.0
        days = (pd.Timestamp(last_date) - pd.Timestamp(lot["entry_date"])).days
        closed_trades.append(
            {
                "Symbol": sym,
                "Shares": sh,
                "EntryDate": lot["entry_date"],
                "EntryPrice": entry_px,
                "ExitDate": last_date,
                "ExitPrice": px,
                "MTM": mtm,
                "Return_%": ret_pct,
                "Days": days,
                "ExitReason": "open_mtm",
            }
        )

    equity = pd.Series(equity_curve, index=calendar, name="Equity")
    returns = equity.pct_change().fillna(0)
    years = max((calendar[-1] - calendar[0]).days / 365.0, 1e-9)
    cagr = (equity.iloc[-1] / INITIAL_CAPITAL) ** (1 / years) - 1
    total_return = equity.iloc[-1] / INITIAL_CAPITAL - 1
    vol = returns.std() * np.sqrt(252)
    sharpe = (
        returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0.0
    )
    downside = returns.copy()
    downside[downside > 0] = 0
    sortino = (
        returns.mean() / downside.std() * np.sqrt(252) if downside.std() > 0 else 0.0
    )
    drawdown = (equity - equity.cummax()) / equity.cummax()
    maxdd = float(drawdown.min())

    realized = [t for t in closed_trades if t["ExitReason"] != "open_mtm"]
    metrics = {
        "switch_threshold_pct": switch_threshold_pct,
        "top_n": top_n,
        "symbols_in_panel": len(panel),
        "final_equity": float(equity.iloc[-1]),
        "total_return_pct": float(total_return * 100),
        "cagr_pct": float(cagr * 100),
        "volatility_pct": float(vol * 100),
        "sharpe": float(sharpe),
        "sortino": float(sortino),
        "max_drawdown_pct": float(maxdd * 100),
        "closed_trades": len(realized),
        "fill_rows": len(fills),
        "total_mtm": float(sum(t["MTM"] for t in realized)),
    }
    weights_df = (
        pd.DataFrame(weight_log).set_index("Date") if weight_log else pd.DataFrame()
    )
    return metrics, closed_trades, fills, equity, drawdown, weights_df


###############################################
# Main
###############################################


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tickers = load_nifty500_symbols()
    print(f"Universe size: {len(tickers)}")

    ohlcv = download_universe(tickers)
    panel = build_panel(ohlcv)
    if not panel:
        raise RuntimeError("No symbols with enough history — check download/cache")

    metrics, closed_trades, fills, equity, drawdown, weights_df = run_backtest(
        panel,
        switch_threshold_pct=SWITCH_THRESHOLD_PCT,
        top_n=TOP_N,
    )

    print()
    print("=" * 60)
    print("NIFTY 500 MOMENTUM — WEEKLY TOP-10 EQUAL WEIGHT")
    print("=" * 60)
    print(f"Switch threshold : {SWITCH_THRESHOLD_PCT}%")
    print(f"Top N            : {TOP_N}")
    print(f"Panel symbols    : {metrics['symbols_in_panel']}")
    print(f"Initial capital  : {INITIAL_CAPITAL:,.0f}")
    print(f"Final equity     : {metrics['final_equity']:,.0f}")
    print(f"Total return     : {metrics['total_return_pct']:.2f}%")
    print(f"CAGR             : {metrics['cagr_pct']:.2f}%")
    print(f"Volatility       : {metrics['volatility_pct']:.2f}%")
    print(f"Sharpe           : {metrics['sharpe']:.2f}")
    print(f"Sortino          : {metrics['sortino']:.2f}")
    print(f"Max drawdown     : {metrics['max_drawdown_pct']:.2f}%")
    print(f"Closed trades    : {metrics['closed_trades']}")
    print(f"Total realized MTM: {metrics['total_mtm']:,.0f}")
    print("=" * 60)

    trade_cols = [
        "Symbol",
        "Shares",
        "EntryDate",
        "EntryPrice",
        "ExitDate",
        "ExitPrice",
        "MTM",
        "Return_%",
        "Days",
        "ExitReason",
    ]
    pd.DataFrame([metrics]).to_csv(LOG_DIR / "summary.csv", index=False)
    pd.DataFrame(closed_trades).reindex(columns=trade_cols).to_csv(
        LOG_DIR / "trade_log.csv", index=False
    )
    pd.DataFrame(fills).to_csv(LOG_DIR / "trade_fills.csv", index=False)
    pd.DataFrame({"Equity": equity, "Drawdown": drawdown}).to_csv(
        LOG_DIR / "portfolio.csv"
    )
    if not weights_df.empty:
        weights_df.to_csv(LOG_DIR / "weights.csv")

    print(f"Logs → {LOG_DIR}")
    print("  trade_log.csv   = closed trades (shares, entry/exit, MTM)")
    print("  trade_fills.csv = raw BUY/SELL fills")

    plt.figure(figsize=(14, 6))
    plt.plot(equity, label="Momentum Top-10")
    plt.title("Nifty 500 Momentum — Equity Curve")
    plt.legend()
    plt.tight_layout()
    plt.savefig(LOG_DIR / "equity_curve.png", dpi=120)
    plt.close()

    plt.figure(figsize=(14, 4))
    plt.fill_between(drawdown.index, drawdown.values, 0)
    plt.title("Drawdown")
    plt.tight_layout()
    plt.savefig(LOG_DIR / "drawdown.png", dpi=120)
    plt.close()


if __name__ == "__main__":
    main()
