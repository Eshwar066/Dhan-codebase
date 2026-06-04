#!/usr/bin/env python3
"""Download NIFTY 50 (^NSEI) hourly candles from Yahoo Finance and compute RSI (14).

Run (use ``python3`` on Debian/Ubuntu; use a venv — system Python is PEP 668 "externally managed")::

    cd /path/to/Dhan-codebase
    python3 -m venv .venv
    source .venv/bin/activate
    pip install yfinance pandas numpy TA-Lib
    python3 utils/yfinance/yfinance_nifty_rsi.py

To refresh shared indicator history (keeps ``live_append`` rows)::

    python3 utils/yfinance/refresh_leaps_rsi_from_yahoo.py
    # -> logs/indicators/NIFTY/60/indicator_history.jsonl (RSI)
    # -> logs/indicators/NIFTY/15/indicator_history.jsonl (Bollinger)

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
        df = out
    rename = {c: c.title() for c in df.columns if isinstance(c, str)}
    if rename:
        df = df.rename(columns=rename)
    return df


def _fetch_interval_ohlc(symbol: str, period: str, interval: str = "60m") -> pd.DataFrame:
    """
    Fetch OHLC from Yahoo at ``interval`` (e.g. ``60m``, ``15m``).
    Prefer ``Ticker.history`` — recent yfinance builds often return empty from
    ``yf.download`` for ``^NSEI`` ("possibly delisted").
    """
    raw = pd.DataFrame()
    try:
        hist = yf.Ticker(symbol).history(
            period=period, interval=interval, auto_adjust=False
        )
        if hist is not None and not hist.empty:
            raw = hist
    except Exception:
        pass
    if raw.empty:
        try:
            dl = yf.download(
                tickers=symbol,
                period=period,
                interval=interval,
                auto_adjust=False,
                progress=False,
            )
            if dl is not None and not dl.empty:
                raw = dl
        except Exception:
            pass
    if raw is None or raw.empty:
        return pd.DataFrame()
    return _flatten_yfinance_columns(raw)


def _fetch_hourly_ohlc(symbol: str, period: str) -> pd.DataFrame:
    """Backward-compatible alias for 60m OHLC."""
    return _fetch_interval_ohlc(symbol, period, interval="60m")


def _prepare_yahoo_frame(raw: pd.DataFrame, tail: int | None) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame()
    df = raw.copy()
    if tail is not None:
        df = df.tail(int(tail)).copy()
    if isinstance(df.index, pd.DatetimeIndex) or df.index.name in ("Datetime", "Date"):
        df = df.reset_index()
    else:
        df = df.reset_index(drop=True)
    time_candidates = ("Datetime", "Date", "Index")
    time_col = next((n for n in time_candidates if n in df.columns), None)
    if time_col is None:
        for c in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[c]):
                time_col = c
                break
    if time_col is None:
        raise ValueError(f"No datetime column in Yahoo OHLC frame: {list(df.columns)}")
    df = df.rename(columns={time_col: "Datetime"})
    dt = pd.to_datetime(df["Datetime"], errors="coerce")
    if getattr(dt.dt, "tz", None) is None:
        df["Datetime_IST"] = dt.dt.tz_localize("Asia/Kolkata")
    else:
        df["Datetime_IST"] = dt.dt.tz_convert("Asia/Kolkata")
    return df


def fetch_nifty_hourly_with_rsi(
    *,
    symbol: str = SYMBOL,
    period: str = "60d",
    tail: int | None = 50,
    rsi_period: int = 14,
) -> pd.DataFrame:
    """
    Download recent 1-hour candles, optionally keep last ``tail`` rows, add RSI and prior RSI.
    Pass ``tail=None`` to keep every bar returned for the period.
    ``Datetime`` column is converted to Asia/Kolkata as ``Datetime_IST``.
    """
    raw = _fetch_interval_ohlc(symbol, period, interval="60m")
    df = _prepare_yahoo_frame(raw, tail)
    if df.empty:
        return df

    close = pd.to_numeric(df["Close"], errors="coerce").astype(float)
    df["RSI_14"] = talib.RSI(close.values, timeperiod=int(rsi_period))
    df["PREV_RSI"] = df["RSI_14"].shift(1)
    return df


def fetch_nifty_15m_with_bollinger(
    *,
    symbol: str = SYMBOL,
    period: str = "60d",
    tail: int | None = None,
    bb_period: int = 20,
    bb_std: float = 2.0,
) -> pd.DataFrame:
    """Download 15m NIFTY bars and add Bollinger columns (bb_upper, bb_mid, bb_lower)."""
    from core.strategies.indicator_helpers import add_bollinger_bands

    raw = _fetch_interval_ohlc(symbol, period, interval="15m")
    df = _prepare_yahoo_frame(raw, tail)
    if df.empty:
        return df
    work = df.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
        }
    )
    work = add_bollinger_bands(work, period=bb_period, std_dev=bb_std)
    df["bb_upper"] = work["bb_upper"]
    df["bb_mid"] = work["bb_mid"]
    df["bb_lower"] = work["bb_lower"]
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
