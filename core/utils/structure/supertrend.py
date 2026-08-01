"""Supertrend columns with strategy-defined ATR length and factor."""

from __future__ import annotations

from typing import Any, List

import pandas as pd


def supertrend_column_names(*, prefix: str = "supertrend") -> List[str]:
    """Columns produced by :func:`add_supertrend`."""
    p = str(prefix or "supertrend").strip() or "supertrend"
    return [
        p,
        f"{p}_direction",
        f"{p}_is_bullish",
        f"{p}_upper",
        f"{p}_lower",
        f"{p}_atr",
    ]


def add_supertrend(
    df: Any,
    length: int,
    factor: float,
    *,
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    prefix: str = "supertrend",
) -> Any:
    """
    Add Supertrend, direction, active bands, and Wilder ATR columns.

    A strategy declares the parameters as class/instance attributes::

        supertrend_length = 10
        supertrend_factor = 3.0

    ``IndicatorManager`` detects those attributes and calls this function.
    Direction is ``1`` for bullish and ``-1`` for bearish; warmup rows are null.
    """
    if df is None or len(df) == 0:
        return df
    required = (high_col, low_col, close_col)
    if any(column not in df.columns for column in required):
        return df

    period = int(length)
    multiplier = float(factor)
    if period < 1:
        raise ValueError("Supertrend length must be >= 1")
    if multiplier <= 0:
        raise ValueError("Supertrend factor must be > 0")

    high = pd.to_numeric(df[high_col], errors="coerce")
    low = pd.to_numeric(df[low_col], errors="coerce")
    close = pd.to_numeric(df[close_col], errors="coerce")
    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    # Wilder's RMA uses alpha=1/length.
    atr = true_range.ewm(
        alpha=1.0 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    midpoint = (high + low) / 2.0
    basic_upper = midpoint + multiplier * atr
    basic_lower = midpoint - multiplier * atr

    size = len(df)
    final_upper = pd.Series(float("nan"), index=df.index, dtype="float64")
    final_lower = pd.Series(float("nan"), index=df.index, dtype="float64")
    trend = pd.Series(float("nan"), index=df.index, dtype="float64")
    direction = pd.Series(float("nan"), index=df.index, dtype="float64")

    valid_positions = [i for i in range(size) if pd.notna(atr.iloc[i])]
    if valid_positions:
        first = valid_positions[0]
        final_upper.iloc[first] = basic_upper.iloc[first]
        final_lower.iloc[first] = basic_lower.iloc[first]
        direction.iloc[first] = 1.0
        trend.iloc[first] = final_lower.iloc[first]

        for i in range(first + 1, size):
            if pd.isna(atr.iloc[i]) or pd.isna(close.iloc[i]):
                continue

            previous_upper = final_upper.iloc[i - 1]
            previous_lower = final_lower.iloc[i - 1]
            previous_price = close.iloc[i - 1]

            final_upper.iloc[i] = (
                basic_upper.iloc[i]
                if (
                    pd.isna(previous_upper)
                    or basic_upper.iloc[i] < previous_upper
                    or previous_price > previous_upper
                )
                else previous_upper
            )
            final_lower.iloc[i] = (
                basic_lower.iloc[i]
                if (
                    pd.isna(previous_lower)
                    or basic_lower.iloc[i] > previous_lower
                    or previous_price < previous_lower
                )
                else previous_lower
            )

            previous_direction = direction.iloc[i - 1]
            if previous_direction < 0:
                direction.iloc[i] = (
                    1.0 if close.iloc[i] > final_upper.iloc[i] else -1.0
                )
            else:
                direction.iloc[i] = (
                    -1.0 if close.iloc[i] < final_lower.iloc[i] else 1.0
                )
            trend.iloc[i] = (
                final_lower.iloc[i]
                if direction.iloc[i] > 0
                else final_upper.iloc[i]
            )

    names = supertrend_column_names(prefix=prefix)
    df[names[0]] = trend
    df[names[1]] = direction
    bullish = pd.Series(pd.NA, index=df.index, dtype="boolean")
    valid_direction = direction.notna()
    bullish.loc[valid_direction] = direction.loc[valid_direction] > 0
    df[names[2]] = bullish
    df[names[3]] = final_upper.where(direction < 0)
    df[names[4]] = final_lower.where(direction > 0)
    df[names[5]] = atr
    return df
