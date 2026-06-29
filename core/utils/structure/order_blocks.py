"""Order-block zones (last opposing candle before displacement)."""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd


def add_order_blocks(
    df: Any,
    *,
    open_col: str = "open",
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    bos_col: str = "bos",
    body_atr_mult: float = 1.2,
    atr_period: int = 14,
) -> Any:
    """
    Simplified order blocks tied to BOS displacement bars.

    Bullish OB: last bearish candle before ``bos == 1``.
    Bearish OB: last bullish candle before ``bos == -1``.

    Columns:
    - ``ob_bull_top``, ``ob_bull_bot``, ``ob_bear_top``, ``ob_bear_bot`` (nearest active, ffill)
    - ``ob_bull_new``, ``ob_bear_new``
    """
    if df is None or len(df) == 0:
        return df
    for c in (open_col, high_col, low_col, close_col):
        if c not in df.columns:
            return df

    n = len(df)
    opens = pd.to_numeric(df[open_col], errors="coerce").to_numpy(dtype=float)
    highs = pd.to_numeric(df[high_col], errors="coerce").to_numpy(dtype=float)
    lows = pd.to_numeric(df[low_col], errors="coerce").to_numpy(dtype=float)
    closes = pd.to_numeric(df[close_col], errors="coerce").to_numpy(dtype=float)
    bos = (
        pd.to_numeric(df[bos_col], errors="coerce").fillna(0).to_numpy(dtype=int)
        if bos_col in df.columns
        else np.zeros(n, dtype=int)
    )

    tr = np.maximum(
        highs - lows,
        np.maximum(np.abs(highs - np.roll(closes, 1)), np.abs(lows - np.roll(closes, 1))),
    )
    tr[0] = highs[0] - lows[0]
    atr = pd.Series(tr).rolling(atr_period, min_periods=1).mean().to_numpy()

    ob_bull_top = np.full(n, np.nan)
    ob_bull_bot = np.full(n, np.nan)
    ob_bear_top = np.full(n, np.nan)
    ob_bear_bot = np.full(n, np.nan)
    ob_bull_new = np.zeros(n, dtype=bool)
    ob_bear_new = np.zeros(n, dtype=bool)

    last_bull: Optional[tuple[float, float]] = None
    last_bear: Optional[tuple[float, float]] = None

    def _bearish_candle(i: int) -> bool:
        return closes[i] < opens[i]

    def _bullish_candle(i: int) -> bool:
        return closes[i] > opens[i]

    def _displacement(i: int) -> bool:
        body = abs(closes[i] - opens[i])
        return body >= body_atr_mult * max(atr[i], 1e-9)

    for i in range(1, n):
        if bos[i] == 1 and _displacement(i):
            j = i - 1
            while j >= 0 and not _bearish_candle(j):
                j -= 1
            if j >= 0:
                last_bull = (float(highs[j]), float(lows[j]))
                ob_bull_new[i] = True
        elif bos[i] == -1 and _displacement(i):
            j = i - 1
            while j >= 0 and not _bullish_candle(j):
                j -= 1
            if j >= 0:
                last_bear = (float(highs[j]), float(lows[j]))
                ob_bear_new[i] = True

        if last_bull is not None:
            ob_bull_top[i], ob_bull_bot[i] = last_bull
        if last_bear is not None:
            ob_bear_top[i], ob_bear_bot[i] = last_bear

        if last_bull is not None and not np.isnan(lows[i]) and lows[i] < last_bull[1]:
            last_bull = None
        if last_bear is not None and not np.isnan(highs[i]) and highs[i] > last_bear[0]:
            last_bear = None

    out = df.copy()
    out["ob_bull_top"] = ob_bull_top
    out["ob_bull_bot"] = ob_bull_bot
    out["ob_bear_top"] = ob_bear_top
    out["ob_bear_bot"] = ob_bear_bot
    out["ob_bull_new"] = ob_bull_new
    out["ob_bear_new"] = ob_bear_new
    return out
