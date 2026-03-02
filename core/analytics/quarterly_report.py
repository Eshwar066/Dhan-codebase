"""
Quarterly performance report from strategy trades CSV.

Reads logs/{strategy}_trades.csv (candle_timestamp, trade_type, pnl), aggregates by quarter,
outputs: QTR, Points Ach, Margin Utilized, Lot Size, PRF in RS, % Ach., M on M.
"""

import csv
import os
from typing import Optional

import pandas as pd


# Quarter label format: "Jan - Mar 25"
QUARTER_LABELS = {
    1: "Jan - Mar",
    2: "Apr - Jun",
    3: "Jul - Sep",
    4: "Oct - Dec",
}


def _quarter_label(year: int, quarter: int) -> str:
    yy = year % 100
    return f"{QUARTER_LABELS[quarter]} {yy:02d}"


def load_strategy_trades_csv(
    csv_path: str,
) -> pd.DataFrame:
    """
    Load strategy-specific trades CSV (e.g. logs/FuturesEMAHighLow_trades.csv).
    Expects: candle_timestamp, trade_type, pnl (and optionally tag, symbol, side, qty, price).
    Tolerates rows with extra columns (e.g. EXIT rows with additional fields) by using only
    the first N columns where N = len(header).
    """
    if not os.path.exists(csv_path):
        return pd.DataFrame()
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return pd.DataFrame()
        ncols = len(header)
        rows = []
        for row in reader:
            if len(row) > ncols:
                row = row[:ncols]
            elif len(row) < ncols:
                row = row + [""] * (ncols - len(row))
            rows.append(row)
    df = pd.DataFrame(rows, columns=header)
    if df.empty:
        return df
    # Normalize column names
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    if "candle_timestamp" not in df.columns:
        return pd.DataFrame()
    df["candle_timestamp"] = pd.to_datetime(df["candle_timestamp"], errors="coerce")
    df = df.dropna(subset=["candle_timestamp"])
    if "pnl" in df.columns:
        df["pnl"] = pd.to_numeric(df["pnl"], errors="coerce").fillna(0)
    else:
        df["pnl"] = 0.0
    if "trade_type" in df.columns:
        df["trade_type"] = df["trade_type"].astype(str).str.strip().str.upper()
    return df


def quarterly_summary(
    df: pd.DataFrame,
    *,
    margin_utilized,
    lot_size,
    pnl_is_currency: bool = True,
) -> pd.DataFrame:
    """
    Aggregate trades by quarter and compute quarterly report.

    Args:
        df: DataFrame with candle_timestamp, trade_type, pnl (from load_strategy_trades_csv).
        margin_utilized: Margin utilized (Rs) for % Ach calculation.
        lot_size: Lot size for Points Ach (Points = PRF in RS / lot_size if pnl is currency).
        pnl_is_currency: If True, pnl column is in currency (Rs); PRF in RS = sum(pnl), Points = PRF/lot_size.
                         If False, pnl is in points; Points = sum(pnl), PRF in RS = Points * lot_size.

    Returns:
        DataFrame with columns: QTR, Points Ach, Margin Utilized, Lot Size, PRF in RS, % Ach., M on M
    """
    if df.empty or "candle_timestamp" not in df.columns or "pnl" not in df.columns:
        return pd.DataFrame(
            columns=[
                "QTR",
                "Points Ach",
                "Margin Utilized",
                "Lot Size",
                "PRF in RS",
                "% Ach.",
                "M on M",
            ]
        )

    # Only EXIT rows have realized pnl
    if "trade_type" in df.columns:
        work = df[df["trade_type"] == "EXIT"].copy()
    else:
        work = df.copy()

    if work.empty:
        return pd.DataFrame(
            columns=[
                "QTR",
                "Points Ach",
                "Margin Utilized",
                "Lot Size",
                "PRF in RS",
                "% Ach.",
                "M on M",
            ]
        )

    work["year"] = work["candle_timestamp"].dt.year
    work["quarter"] = work["candle_timestamp"].dt.quarter
    agg = work.groupby(["year", "quarter"], as_index=False)["pnl"].sum()

    rows = []
    for _, r in agg.iterrows():
        year, q, prf_raw = int(r["year"]), int(r["quarter"]), float(r["pnl"])
        if pnl_is_currency:
            prf_rs = prf_raw
            points_ach = prf_rs / lot_size if lot_size else 0
        else:
            points_ach = prf_raw
            prf_rs = points_ach * lot_size
        pct_ach = (prf_rs / margin_utilized * 100) if margin_utilized else 0
        m_on_m = prf_rs / 3.0  # per month in quarter
        rows.append(
            {
                "QTR": _quarter_label(year, q),
                "Points Ach": round(points_ach, 2),
                "Margin Utilized": margin_utilized,
                "Lot Size": lot_size,
                "PRF in RS": round(prf_rs, 2),
                "% Ach.": round(pct_ach, 2),
                "M on M": round(m_on_m, 2),
            }
        )

    return pd.DataFrame(rows)


def print_quarterly_report(
    csv_path: str,
    margin_utilized,
    lot_size,
    pnl_is_currency: bool = True,
) -> Optional[pd.DataFrame]:
    """
    Load strategy trades CSV, compute quarterly summary, and print table.
    Returns the summary DataFrame or None if no data.
    """
    df = load_strategy_trades_csv(csv_path)
    summary = quarterly_summary(
        df,
        margin_utilized=margin_utilized,
        lot_size=lot_size,
        pnl_is_currency=pnl_is_currency,
    )
    if summary.empty:
        print(f"No quarterly data from {csv_path}")
        return None
    print(summary.to_string(index=False))
    return summary


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "logs/FuturesEMAHighLow_trades.csv"
    margin = float(sys.argv[2])
    lot = float(sys.argv[3])
    # For BTCUSD/crypto, pnl is typically in USD and lot_size=1; for index futures, pnl in RS, lot_size=150
    pnl_currency = len(sys.argv) <= 4 or sys.argv[4].lower() not in (
        "0",
        "false",
        "points",
    )
    print_quarterly_report(
        path, margin_utilized=margin, lot_size=lot, pnl_is_currency=pnl_currency
    )
