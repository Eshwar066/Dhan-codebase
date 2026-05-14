#!/usr/bin/env python3
"""Download NIFTY 50 (^NSEI) hourly candles from Yahoo Finance and compute RSI (14).

Run (use ``python3`` on Debian/Ubuntu; use a venv — system Python is PEP 668 "externally managed")::

    cd /path/to/Dhan-codebase
    python3 -m venv .venv
    source .venv/bin/activate
    pip install yfinance pandas numpy TA-Lib
    python3 utils/yfinance_nifty_rsi.py

If a project ``.venv`` already exists, only ``activate`` + ``pip install yfinance`` (and deps) is needed.
"""

from __future__ import annotations

import sys

import pandas as pd
import yfinance as yf

try:
    import talib
except ImportError as e:  # pragma: no cover
    print("TA-Lib is required: pip install TA-Lib", file=sys.stderr)
    raise e

# Yahoo Finance symbol for NIFTY 50
SYMBOL = "^NSEI"


def _flatten_yfinance_columns(df: pd.DataFrame) -> pd.DataFrame:
    """yfinance returns a MultiIndex column when downloading a single ticker."""
    if isinstance(df.columns, pd.MultiIndex):
        out = df.copy()
        out.columns = out.columns.get_level_values(0)
        return out
    return df


def fetch_nifty_hourly_with_rsi(
    *,
    symbol: str = SYMBOL,
    period: str = "30d",
    tail: int = 50,
    rsi_period: int = 14,
) -> pd.DataFrame:
    """
    Download recent 1-hour candles, keep last ``tail`` rows, add RSI and prior RSI.
    ``Datetime`` column is converted to Asia/Kolkata as ``Datetime_IST``.
    """
    raw = yf.download(
        tickers=symbol,
        period=period,
        interval="60m",
        auto_adjust=False,
        progress=False,
    )
    if raw is None or raw.empty:
        return pd.DataFrame()

    df = _flatten_yfinance_columns(raw)
    df = df.tail(int(tail)).copy().reset_index()

    # Index becomes a column: often 'Datetime' or 'Date' depending on yfinance version
    time_candidates = ("Datetime", "datetime", "Date", "date", "index")
    time_col = None
    for name in time_candidates:
        if name in df.columns:
            time_col = name
            break
    if time_col is None:
        for c in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[c]):
                time_col = c
                break
    if time_col is None:
        time_col = df.columns[0]
    df = df.rename(columns={time_col: "Datetime"})

    close = pd.to_numeric(df["Close"], errors="coerce").astype(float)
    df["RSI_14"] = talib.RSI(close.values, timeperiod=int(rsi_period))
    df["PREV_RSI"] = df["RSI_14"].shift(1)

    df["Datetime"] = pd.to_datetime(df["Datetime"], utc=True, errors="coerce")
    df["Datetime_IST"] = df["Datetime"].dt.tz_convert("Asia/Kolkata")

    return df


def main() -> None:
    df = fetch_nifty_hourly_with_rsi()
    if df.empty:
        print("No data returned from Yahoo Finance.", file=sys.stderr)
        sys.exit(1)

    out = df[
        [
            "Datetime_IST",
            "Open",
            "High",
            "Low",
            "Close",
            "RSI_14",
            "PREV_RSI",
        ]
    ]
    print(out.tail(20).to_string(index=False))


if __name__ == "__main__":
    main()
