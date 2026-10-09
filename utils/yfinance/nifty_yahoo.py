#!/usr/bin/env python3
"""Yahoo Finance helpers for NIFTY (^NSEI) OHLC + common indicators.

Shared by LEAPS RSI (60m), NiftySMA9Weekly (120m), Bollinger (15m), and future
strategies that seed ``logs/indicators/NIFTY/{tf}/``.

Run (use ``python3`` on Debian/Ubuntu; use a venv — system Python is PEP 668 "externally managed")::

    cd /path/to/Dhan-codebase
    python3 -m venv .venv
    source .venv/bin/activate
    pip install yfinance pandas numpy TA-Lib
    python3 utils/yfinance/nifty_yahoo.py

To refresh shared indicator history (keeps ``live_append`` rows)::

    python3 utils/yfinance/refresh_nifty_indicator_history.py
    # -> logs/indicators/NIFTY/60/indicator_history.jsonl (RSI)
    # -> logs/indicators/NIFTY/15/indicator_history.jsonl (Bollinger)
    python3 utils/yfinance/refresh_nifty_indicator_history.py --only 120
    # -> logs/indicators/NIFTY/120/indicator_history.jsonl (SMA9)

If a project ``.venv`` already exists, only ``activate`` + ``pip install yfinance`` (and deps) is needed.
"""

from __future__ import annotations

import sys
from typing import Any

import pandas as pd
import yfinance as yf

# Yahoo Finance symbol for NIFTY 50
SYMBOL = "^NSEI"


def _require_talib():
    try:
        import talib
    except ImportError as e:  # pragma: no cover
        print("TA-Lib is required for RSI helpers: pip install TA-Lib", file=sys.stderr)
        raise e
    return talib


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

    talib = _require_talib()
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


# NSE cash 2h bar opens (IST) after 60→120 resample with origin 09:15.
_NSE_120_BAR_MINUTES = frozenset(
    {(9, 15), (11, 15), (13, 15), (15, 15)}
)

# NSE 30m bar opens (IST) with origin 09:15.
_NSE_30_BAR_MINUTES = frozenset(
    {(9, 15), (9, 45), (10, 15), (10, 45), (11, 15), (11, 45),
     (12, 15), (12, 45), (13, 15), (13, 45), (14, 15), (14, 45),
     (15, 15)}
)


def _resample_60m_to_120m_nse(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build NSE 120m OHLC from Yahoo 60m bars (session origin 09:15 IST).

    Same idea as ``DhanSource._resample_ohlc_minutes`` for timeframe 120.
    """
    if df is None or df.empty or "Datetime_IST" not in df.columns:
        return pd.DataFrame()

    work = df.copy()
    work["Datetime_IST"] = pd.to_datetime(work["Datetime_IST"], errors="coerce")
    work = work.dropna(subset=["Datetime_IST"])
    if work.empty:
        return pd.DataFrame()

    # Keep only NSE 60m session opens (:15) so resample buckets match live aggregator.
    from core.utils.indicator_history import is_nse_60m_bar_ist

    keep = []
    for ts in work["Datetime_IST"]:
        dt = pd.Timestamp(ts)
        if dt.tzinfo is None:
            dt = dt.tz_localize("Asia/Kolkata")
        else:
            dt = dt.tz_convert("Asia/Kolkata")
        keep.append(is_nse_60m_bar_ist(dt.to_pydatetime()))
    work = work.loc[keep].copy()
    if work.empty:
        return pd.DataFrame()

    work = work.set_index("Datetime_IST").sort_index()
    market_start = pd.Timestamp("09:15:00").time()
    market_end = pd.Timestamp("15:30:00").time()
    chunks: list[pd.DataFrame] = []
    for day, group in work.groupby(work.index.date):
        origin = pd.Timestamp(f"{day} 09:15:00", tz="Asia/Kolkata")
        daily = group.between_time(market_start, market_end)
        if daily.empty:
            continue
        cols = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in daily.columns]
        daily = daily[cols]
        agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
        if "Volume" in daily.columns:
            agg["Volume"] = "sum"
        resampled = (
            daily.resample("120min", origin=origin, label="left", closed="left")
            .agg(agg)
            .dropna(subset=["Open", "High", "Low", "Close"], how="any")
        )
        if not resampled.empty:
            chunks.append(resampled)
    if not chunks:
        return pd.DataFrame()
    out = pd.concat(chunks).sort_index()
    out = out.reset_index()
    if "Datetime_IST" not in out.columns:
        out = out.rename(columns={out.columns[0]: "Datetime_IST"})
    # Drop incomplete / off-grid buckets.
    def _ok_120(ts: Any) -> bool:
        dt = pd.Timestamp(ts)
        if dt.tzinfo is None:
            dt = dt.tz_localize("Asia/Kolkata")
        else:
            dt = dt.tz_convert("Asia/Kolkata")
        return (int(dt.hour), int(dt.minute)) in _NSE_120_BAR_MINUTES

    out = out.loc[out["Datetime_IST"].map(_ok_120)].reset_index(drop=True)
    return out


def _resample_15m_to_30m_nse(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build NSE 30m OHLC from Yahoo 15m bars (session origin 09:15 IST).

    Same idea as ``_resample_60m_to_120m_nse`` for timeframe 30.
    """
    if df is None or df.empty or "Datetime_IST" not in df.columns:
        return pd.DataFrame()

    work = df.copy()
    work["Datetime_IST"] = pd.to_datetime(work["Datetime_IST"], errors="coerce")
    work = work.dropna(subset=["Datetime_IST"])
    if work.empty:
        return pd.DataFrame()

    # Keep only NSE 15m session opens so resample buckets match live aggregator.
    from core.utils.indicator_history import is_nse_60m_bar_ist

    keep = []
    for ts in work["Datetime_IST"]:
        dt = pd.Timestamp(ts)
        if dt.tzinfo is None:
            dt = dt.tz_localize("Asia/Kolkata")
        else:
            dt = dt.tz_convert("Asia/Kolkata")
        # 15m NSE bars are at :00, :15, :30, :45 past the hour during market hours
        h, m = int(dt.hour), int(dt.minute)
        if 9 <= h <= 15 and m in (0, 15, 30, 45):
            if h == 9 and m == 0:
                continue  # before market open
            if h == 15 and m > 30:
                continue  # after market close
            keep.append(True)
        else:
            keep.append(False)
    work = work.loc[keep].copy()
    if work.empty:
        return pd.DataFrame()

    work = work.set_index("Datetime_IST").sort_index()
    market_start = pd.Timestamp("09:15:00").time()
    market_end = pd.Timestamp("15:30:00").time()
    chunks: list[pd.DataFrame] = []
    for day, group in work.groupby(work.index.date):
        origin = pd.Timestamp(f"{day} 09:15:00", tz="Asia/Kolkata")
        daily = group.between_time(market_start, market_end)
        if daily.empty:
            continue
        cols = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in daily.columns]
        daily = daily[cols]
        agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
        if "Volume" in daily.columns:
            agg["Volume"] = "sum"
        resampled = (
            daily.resample("30min", origin=origin, label="left", closed="left")
            .agg(agg)
            .dropna(subset=["Open", "High", "Low", "Close"], how="any")
        )
        if not resampled.empty:
            chunks.append(resampled)
    if not chunks:
        return pd.DataFrame()
    out = pd.concat(chunks).sort_index()
    out = out.reset_index()
    if "Datetime_IST" not in out.columns:
        out = out.rename(columns={out.columns[0]: "Datetime_IST"})
    # Drop incomplete / off-grid buckets.
    def _ok_30(ts: Any) -> bool:
        dt = pd.Timestamp(ts)
        if dt.tzinfo is None:
            dt = dt.tz_localize("Asia/Kolkata")
        else:
            dt = dt.tz_convert("Asia/Kolkata")
        return (int(dt.hour), int(dt.minute)) in _NSE_30_BAR_MINUTES

    out = out.loc[out["Datetime_IST"].map(_ok_30)].reset_index(drop=True)
    return out


def fetch_nifty_120m_with_sma(
    *,
    symbol: str = SYMBOL,
    period: str = "60d",
    tail: int | None = None,
    sma_period: int = 9,
) -> pd.DataFrame:
    """
    Download Yahoo 60m ^NSEI, resample to NSE 120m, add SMA (default 9).

    Columns match NiftySMA9Weekly persisted keys: ``sma9``, ``prev_sma9``, ``prev_close``.
    """
    from core.strategies.indicator_helpers import add_sma

    raw = _fetch_interval_ohlc(symbol, period, interval="60m")
    hourly = _prepare_yahoo_frame(raw, tail=None)
    if hourly.empty:
        return hourly
    df = _resample_60m_to_120m_nse(hourly)
    if df.empty:
        return df
    if tail is not None:
        df = df.tail(int(tail)).copy()

    work = df.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
        }
    )
    period_n = int(sma_period)
    sma_col = f"sma{period_n}"
    prev_sma_col = f"prev_sma{period_n}"
    work = add_sma(work, period=period_n, column=sma_col)
    if sma_col in work.columns:
        work[prev_sma_col] = work[sma_col].shift(1)
    if "close" in work.columns:
        work["prev_close"] = work["close"].shift(1)

    df[sma_col] = work[sma_col]
    df[prev_sma_col] = work[prev_sma_col]
    df["prev_close"] = work["prev_close"]
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




def fetch_nifty_30m_with_adx_supertrend_ma9(
    *,
    symbol: str = SYMBOL,
    period: str = "60d",
    tail: int | None = None,
    adx_period: int = 14,
    supertrend_length: int = 10,
    supertrend_factor: float = 3.0,
    ma_period: int = 9,
) -> pd.DataFrame:
    """
    Download 15m NIFTY bars, resample to NSE 30m, add ADX, Supertrend, and MA9 columns.

    Columns returned:
    - Datetime_IST, Open, High, Low, Close, Volume
    - adx_{period}, adx_di_plus_{period}, adx_di_minus_{period}
    - supertrend, supertrend_direction, supertrend_is_bullish, supertrend_upper, supertrend_lower, supertrend_atr
    - sma9, prev_sma9
    """
    from core.utils.structure import add_adx, add_supertrend
    from core.strategies.indicator_helpers import add_sma

    raw = _fetch_interval_ohlc(symbol, period, interval="15m")
    df_15m = _prepare_yahoo_frame(raw, tail=None)
    if df_15m.empty:
        return df_15m

    # Resample 15m to NSE 30m (origin 09:15)
    df = _resample_15m_to_30m_nse(df_15m)
    if df.empty:
        return df
    if tail is not None:
        df = df.tail(int(tail)).copy()

    work = df.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
        }
    )

    # Add ADX
    work = add_adx(work, period=adx_period, prefix="adx")

    # Add Supertrend
    work = add_supertrend(
        work,
        length=supertrend_length,
        factor=supertrend_factor,
        prefix="supertrend",
    )

    # Add MA9 (SMA)
    ma_col = f"sma{ma_period}"
    prev_ma_col = f"prev_sma{ma_period}"
    work = add_sma(work, period=ma_period, column=ma_col)
    if ma_col in work.columns:
        work[prev_ma_col] = work[ma_col].shift(1)

    # Copy computed columns back to original df
    indicator_cols = [
        f"adx_{adx_period}", f"adx_di_plus_{adx_period}", f"adx_di_minus_{adx_period}",
        "supertrend", "supertrend_direction", "supertrend_is_bullish",
        "supertrend_upper", "supertrend_lower", "supertrend_atr",
        ma_col, prev_ma_col,
    ]
    for col in indicator_cols:
        if col in work.columns:
            df[col] = work[col]

    return df


def main_30m_adx_supertrend_ma9() -> None:
    """CLI entry for 30m NIFTY with ADX, Supertrend, MA9."""
    df = fetch_nifty_30m_with_adx_supertrend_ma9(tail=50)
    if df.empty:
        print("No data returned from Yahoo Finance.", file=sys.stderr)
        sys.exit(1)

    cols = [
        "Datetime_IST",
        "Close",
        "adx_14",
        "adx_di_plus_14",
        "adx_di_minus_14",
        "supertrend",
        "supertrend_direction",
        "supertrend_is_bullish",
        "sma9",
        "prev_sma9",
    ]
    # Filter to only existing columns
    cols = [c for c in cols if c in df.columns]
    print(df[cols].tail(20).to_string(index=False))


def save_nifty_30m_indicator_history(
    df: pd.DataFrame,
    *,
    log_root: str = None,
    symbol: str = "NIFTY",
    timeframe: str = "30",
    dry_run: bool = False,
) -> dict:
    """
    Save 30m NIFTY indicator history (ADX, Supertrend, MA9) to JSONL file.

    Matches the schema v2 format used by refresh_nifty_indicator_history.py.
    File: logs/indicators/{symbol}/{timeframe}/indicator_history.jsonl
    """
    import json
    import math
    import os
    from typing import Any, Dict, List, Optional

    from core.utils.indicator_history import SCHEMA_VERSION, indicator_history_path

    if log_root is None:
        _REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        log_root = os.path.join(_REPO_ROOT, "logs")

    hist_path = indicator_history_path(symbol, timeframe, log_root=log_root)

    def _normalize_ist_key(ts: str) -> str:
        s = str(ts or "").strip()
        if "T" in s:
            s = s.replace("T", " ")[:16]
        return s[:16] if len(s) >= 16 else s

    def _float_or_none(val: Any) -> Optional[float]:
        if val is None:
            return None
        try:
            f = float(val)
        except (TypeError, ValueError):
            return None
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, 2)

    def _build_schema_row(
        *,
        symbol: str,
        timeframe: str,
        ist_key: str,
        o: Optional[float],
        h: Optional[float],
        l: Optional[float],
        c: Optional[float],
        indicators: Dict[str, Any],
        source: str = "yahoo_refresh_30m",
    ) -> dict:
        close = c if c is not None else o
        return {
            "schema": SCHEMA_VERSION,
            "symbol": str(symbol or "NIFTY").upper(),
            "timeframe": timeframe,
            "source": source,
            "candle_timestamp_ist": ist_key,
            "ohlc": {
                "open": o if o is not None else close,
                "high": h if h is not None else close,
                "low": l if l is not None else close,
                "close": close,
            },
            "indicators": {k: v for k, v in indicators.items() if v is not None},
        }

    # Convert df to schema rows
    rows: List[dict] = []
    for _, row in df.iterrows():
        dt = row.get("Datetime_IST")
        if dt is None or (isinstance(dt, float) and pd.isna(dt)):
            continue
        dt_ist = pd.Timestamp(dt)
        if dt_ist.tzinfo is None:
            dt_ist = dt_ist.tz_localize("Asia/Kolkata")
        else:
            dt_ist = dt_ist.tz_convert("Asia/Kolkata")
        key = dt_ist.strftime("%Y-%m-%d %H:%M")

        close = _float_or_none(row.get("Close"))
        if close is None:
            continue

        # Build indicators dict
        indicators: Dict[str, Any] = {}
        for ind_key, df_col in [
            ("adx", f"adx_{14}"),
            ("di_plus", f"adx_di_plus_{14}"),
            ("di_minus", f"adx_di_minus_{14}"),
            ("supertrend", "supertrend"),
            ("supertrend_direction", "supertrend_direction"),
            ("supertrend_is_bullish", "supertrend_is_bullish"),
            ("supertrend_upper", "supertrend_upper"),
            ("supertrend_lower", "supertrend_lower"),
            ("supertrend_atr", "supertrend_atr"),
            ("sma9", "sma9"),
            ("prev_sma9", "prev_sma9"),
        ]:
            val = _float_or_none(row.get(df_col))
            if val is not None:
                indicators[ind_key] = val

        rows.append(_build_schema_row(
            symbol=symbol,
            timeframe=timeframe,
            ist_key=key,
            o=_float_or_none(row.get("Open")),
            h=_float_or_none(row.get("High")),
            l=_float_or_none(row.get("Low")),
            c=close,
            indicators=indicators,
        ))

    if not dry_run:
        os.makedirs(os.path.dirname(hist_path), exist_ok=True)
        with open(hist_path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, default=str) + "\n")

    return {
        "path": hist_path,
        "rows_written": len(rows),
        "dry_run": dry_run,
        "from": rows[0]["candle_timestamp_ist"] if rows else None,
        "to": rows[-1]["candle_timestamp_ist"] if rows else None,
    }


def main_30m_save() -> None:
    """CLI: Fetch 30m NIFTY with ADX/Supertrend/MA9 and save to indicator_history.jsonl."""
    df = fetch_nifty_30m_with_adx_supertrend_ma9(tail=None)
    if df.empty:
        print("No data returned from Yahoo Finance.", file=sys.stderr)
        sys.exit(1)

    stats = save_nifty_30m_indicator_history(df, dry_run=False)
    print(f"Saved {stats['rows_written']} rows to {stats['path']}")
    print(f"Range: {stats['from']} .. {stats['to']}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        if sys.argv[1] == "30m":
            main_30m_adx_supertrend_ma9()
        elif sys.argv[1] == "30m-save":
            main_30m_save()
        else:
            main()
    else:
        main()
