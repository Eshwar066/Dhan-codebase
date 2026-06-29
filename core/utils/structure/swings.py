"""Fractal swing high / low detection."""

from __future__ import annotations

from typing import Any, Optional, Tuple

import numpy as np
import pandas as pd


def add_swing_points(
    df: Any,
    *,
    left: int = 2,
    right: int = 2,
    high_col: str = "high",
    low_col: str = "low",
    prefix: str = "swing",
) -> Any:
    """
  Mark swing pivots and carry the latest confirmed swing levels forward.

  Adds columns:
  - ``{prefix}_high`` / ``{prefix}_low`` — bool at pivot bar
  - ``{prefix}_high_price`` / ``{prefix}_low_price`` — pivot price at pivot bar
  - ``last_{prefix}_high`` / ``last_{prefix}_low`` — last confirmed level (ffill)
  """
    if df is None or len(df) == 0:
        return df
    if high_col not in df.columns or low_col not in df.columns:
        return df

    n = len(df)
    left = max(0, int(left))
    right = max(0, int(right))
    win = left + right + 1
    if win < 3 or n < win:
        out = df.copy()
        for col in (
            f"{prefix}_high",
            f"{prefix}_low",
            f"{prefix}_high_price",
            f"{prefix}_low_price",
            f"last_{prefix}_high",
            f"last_{prefix}_low",
        ):
            out[col] = np.nan if "price" in col or col.startswith("last_") else False
        return out

    highs = pd.to_numeric(df[high_col], errors="coerce").to_numpy(dtype=float)
    lows = pd.to_numeric(df[low_col], errors="coerce").to_numpy(dtype=float)

    swing_high = np.zeros(n, dtype=bool)
    swing_low = np.zeros(n, dtype=bool)
    swing_high_px = np.full(n, np.nan)
    swing_low_px = np.full(n, np.nan)

    for i in range(left, n - right):
        h_win = highs[i - left : i + right + 1]
        l_win = lows[i - left : i + right + 1]
        if np.isnan(h_win).all() or np.isnan(l_win).all():
            continue
        if highs[i] == np.nanmax(h_win):
            swing_high[i] = True
            swing_high_px[i] = highs[i]
        if lows[i] == np.nanmin(l_win):
            swing_low[i] = True
            swing_low_px[i] = lows[i]

    out = df.copy()
    out[f"{prefix}_high"] = swing_high
    out[f"{prefix}_low"] = swing_low
    out[f"{prefix}_high_price"] = swing_high_px
    out[f"{prefix}_low_price"] = swing_low_px
    out[f"last_{prefix}_high"] = (
        pd.Series(swing_high_px, index=out.index).ffill().to_numpy()
    )
    out[f"last_{prefix}_low"] = (
        pd.Series(swing_low_px, index=out.index).ffill().to_numpy()
    )
    return out


def swing_pivot_indices(
    df: Any,
    *,
    side: str = "high",
    prefix: str = "swing",
) -> Tuple[np.ndarray, np.ndarray]:
    """Return (indices, prices) for confirmed swing pivots."""
    col = f"{prefix}_{side}"
    px_col = f"{prefix}_{side}_price"
    if df is None or col not in df.columns:
        return np.array([], dtype=int), np.array([], dtype=float)
    mask = df[col].fillna(False).astype(bool)
    idx = np.flatnonzero(mask.to_numpy())
    prices = pd.to_numeric(df.loc[mask, px_col], errors="coerce").to_numpy(dtype=float)
    return idx, prices
