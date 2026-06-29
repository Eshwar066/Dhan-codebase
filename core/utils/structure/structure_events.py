"""Break of structure (BOS) and change of character (CHoCH)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def add_bos_choch(
    df: Any,
    *,
    close_col: str = "close",
    last_swing_high_col: str = "last_swing_high",
    last_swing_low_col: str = "last_swing_low",
    swing_high_col: str = "swing_high",
    swing_low_col: str = "swing_low",
) -> Any:
    """
    Event flags on structure breaks vs last confirmed swing levels.

    ``bos`` / ``choch``: ``1`` bullish, ``-1`` bearish, ``0`` none.
    Trend context: ``1`` up, ``-1`` down, ``0`` undecided.
    """
    if df is None or len(df) == 0 or close_col not in df.columns:
        return df

    required = (last_swing_high_col, last_swing_low_col)
    for c in required:
        if c not in df.columns:
            return df

    n = len(df)
    closes = pd.to_numeric(df[close_col], errors="coerce").to_numpy(dtype=float)
    lsh = pd.to_numeric(df[last_swing_high_col], errors="coerce").to_numpy(dtype=float)
    lsl = pd.to_numeric(df[last_swing_low_col], errors="coerce").to_numpy(dtype=float)

    bos = np.zeros(n, dtype=int)
    choch = np.zeros(n, dtype=int)
    trend = np.zeros(n, dtype=int)

    state = 0  # -1 down, 1 up
    prev_sh = np.nan
    prev_sl = np.nan

    for i in range(n):
        cl = closes[i]
        sh = lsh[i]
        sl = lsl[i]

        if swing_high_col in df.columns and bool(df[swing_high_col].iloc[i]):
            prev_sh = sh
        if swing_low_col in df.columns and bool(df[swing_low_col].iloc[i]):
            prev_sl = sl

        ref_h = prev_sh if not np.isnan(prev_sh) else sh
        ref_l = prev_sl if not np.isnan(prev_sl) else sl

        if np.isnan(cl):
            trend[i] = state
            continue

        if not np.isnan(ref_h) and cl > ref_h:
            if state <= 0:
                choch[i] = 1
            else:
                bos[i] = 1
            state = 1
        elif not np.isnan(ref_l) and cl < ref_l:
            if state >= 0:
                choch[i] = -1
            else:
                bos[i] = -1
            state = -1

        trend[i] = state

    out = df.copy()
    out["bos"] = bos
    out["choch"] = choch
    out["structure_trend"] = trend
    return out
