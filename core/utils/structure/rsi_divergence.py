"""RSI divergence at swing pivots."""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd


def _wilder_rsi(close: np.ndarray, period: int) -> np.ndarray:
    n = len(close)
    out = np.full(n, np.nan)
    if n < period + 1:
        return out
    delta = np.diff(close)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = np.mean(gain[:period])
    avg_loss = np.mean(loss[:period])
    if avg_loss == 0:
        out[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        out[period] = 100.0 - (100.0 / (1.0 + rs))
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gain[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + loss[i - 1]) / period
        if avg_loss == 0:
            out[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            out[i] = 100.0 - (100.0 / (1.0 + rs))
    return out


def add_rsi_divergence(
    df: Any,
    *,
    close_col: str = "close",
    rsi_col: str = "rsi",
    swing_high_col: str = "swing_high",
    swing_low_col: str = "swing_low",
    swing_high_price_col: str = "swing_high_price",
    swing_low_price_col: str = "swing_low_price",
    rsi_period: int = 14,
    lookback_swings: int = 5,
) -> Any:
    """
    Regular divergence flags at consecutive swing pivots.

    - ``rsi_div_bull``: price lower low, RSI higher low
    - ``rsi_div_bear``: price higher high, RSI lower high
  """
    if df is None or len(df) == 0 or close_col not in df.columns:
        return df

    out = df.copy()
    if rsi_col not in out.columns:
        close = pd.to_numeric(out[close_col], errors="coerce").to_numpy(dtype=float)
        out[rsi_col] = _wilder_rsi(close, max(1, int(rsi_period)))

    n = len(out)
    bull_div = np.zeros(n, dtype=bool)
    bear_div = np.zeros(n, dtype=bool)

    if swing_high_col not in out.columns or swing_low_col not in out.columns:
        out["rsi_div_bull"] = bull_div
        out["rsi_div_bear"] = bear_div
        return out

    rsi = pd.to_numeric(out[rsi_col], errors="coerce").to_numpy(dtype=float)
    sh_px = (
        pd.to_numeric(out[swing_high_price_col], errors="coerce").to_numpy(dtype=float)
        if swing_high_price_col in out.columns
        else np.full(n, np.nan)
    )
    sl_px = (
        pd.to_numeric(out[swing_low_price_col], errors="coerce").to_numpy(dtype=float)
        if swing_low_price_col in out.columns
        else np.full(n, np.nan)
    )

    high_idx: list[int] = []
    low_idx: list[int] = []

    for i in range(n):
        if bool(out[swing_high_col].iloc[i]):
            high_idx.append(i)
            if len(high_idx) >= 2:
                i0, i1 = high_idx[-2], high_idx[-1]
                if (i1 - i0) <= lookback_swings * 10:
                    p0, p1 = sh_px[i0], sh_px[i1]
                    r0, r1 = rsi[i0], rsi[i1]
                    if not np.isnan(p0) and not np.isnan(p1) and p1 > p0 and not np.isnan(r0) and not np.isnan(r1) and r1 < r0:
                        bear_div[i1] = True
            high_idx = high_idx[-max(lookback_swings, 2) :]

        if bool(out[swing_low_col].iloc[i]):
            low_idx.append(i)
            if len(low_idx) >= 2:
                i0, i1 = low_idx[-2], low_idx[-1]
                if (i1 - i0) <= lookback_swings * 10:
                    p0, p1 = sl_px[i0], sl_px[i1]
                    r0, r1 = rsi[i0], rsi[i1]
                    if not np.isnan(p0) and not np.isnan(p1) and p1 < p0 and not np.isnan(r0) and not np.isnan(r1) and r1 > r0:
                        bull_div[i1] = True
            low_idx = low_idx[-max(lookback_swings, 2) :]

    out["rsi_div_bull"] = bull_div
    out["rsi_div_bear"] = bear_div
    return out
