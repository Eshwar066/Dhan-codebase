"""ADX (Average Directional Index) with DI+ and DI- columns."""

from __future__ import annotations

from typing import Any, List

import pandas as pd


def adx_column_names(*, period: int, prefix: str = "adx") -> List[str]:
    """Columns produced by :func:`add_adx`."""
    p = int(period)
    if p < 1:
        raise ValueError("ADX period must be >= 1")
    base = str(prefix or "adx").strip() or "adx"
    return [
        f"{base}_{p}",
        f"{base}_di_plus_{p}",
        f"{base}_di_minus_{p}",
    ]


def add_adx(
    df: Any,
    period: int = 14,
    *,
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    prefix: str = "adx",
) -> Any:
    """
    Add ADX, DI+, DI- columns to dataframe using Wilder's smoothing.

    A strategy declares the parameter as a class/instance attribute::

        adx_period = 14

    ``IndicatorManager`` detects this attribute and calls this function.
    Warmup rows are null until enough data is available.
    """
    if df is None or len(df) == 0:
        return df

    required = (high_col, low_col, close_col)
    if any(column not in df.columns for column in required):
        return df

    p = int(period)
    if p < 1:
        raise ValueError("ADX period must be >= 1")

    high = pd.to_numeric(df[high_col], errors="coerce")
    low = pd.to_numeric(df[low_col], errors="coerce")
    close = pd.to_numeric(df[close_col], errors="coerce")
    prev_close = close.shift(1)

    # True Range
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Directional Movement
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = ((up_move > down_move) & (up_move > 0)) * up_move
    minus_dm = ((down_move > up_move) & (down_move > 0)) * down_move

    # Wilder's smoothing (alpha = 1/period)
    alpha = 1.0 / p
    atr = tr.ewm(alpha=alpha, adjust=False, min_periods=p).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=alpha, adjust=False, min_periods=p).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=alpha, adjust=False, min_periods=p).mean() / atr)

    # ADX
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di))
    adx = dx.ewm(alpha=alpha, adjust=False, min_periods=p).mean()

    names = adx_column_names(period=p, prefix=prefix)
    df[names[0]] = adx
    df[names[1]] = plus_di
    df[names[2]] = minus_di
    return df


def default_persisted_keys_for_adx(period: int = 14, *, prefix: str = "adx") -> List[str]:
    """Persisted keys matching :func:`add_adx`."""
    return adx_column_names(period=period, prefix=prefix)