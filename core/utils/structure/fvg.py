"""Fair value gaps (FVG) and inverse FVG (IFVG) tracking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

import numpy as np
import pandas as pd


@dataclass
class _FvgZone:
    top: float
    bottom: float
    side: str  # "bull" | "bear"
    start_idx: int
    mitigated: bool = False
    inverted: bool = False


def add_fvg_columns(
    df: Any,
    *,
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
) -> Any:
    """
    Detect 3-candle FVGs and track nearest active zone per bar.

    Bullish FVG: ``low[i] > high[i-2]`` (gap up).
    Bearish FVG: ``high[i] < low[i-2]`` (gap down).

    Columns added:
    - ``fvg_bull_top``, ``fvg_bull_bot`` — nearest active bullish FVG (NaN if none)
    - ``fvg_bear_top``, ``fvg_bear_bot``
    - ``fvg_bull_new``, ``fvg_bear_new`` — bool, new gap formed this bar
    - ``ifvg_bull``, ``ifvg_bear`` — bool, inverse FVG event (reclaim after mitigation)
    """
    if df is None or len(df) < 3:
        return df
    for c in (high_col, low_col, close_col):
        if c not in df.columns:
            return df

    n = len(df)
    highs = pd.to_numeric(df[high_col], errors="coerce").to_numpy(dtype=float)
    lows = pd.to_numeric(df[low_col], errors="coerce").to_numpy(dtype=float)
    closes = pd.to_numeric(df[close_col], errors="coerce").to_numpy(dtype=float)

    bull_top = np.full(n, np.nan)
    bull_bot = np.full(n, np.nan)
    bear_top = np.full(n, np.nan)
    bear_bot = np.full(n, np.nan)
    bull_new = np.zeros(n, dtype=bool)
    bear_new = np.zeros(n, dtype=bool)
    ifvg_bull = np.zeros(n, dtype=bool)
    ifvg_bear = np.zeros(n, dtype=bool)

    active: List[_FvgZone] = []

    def _nearest(side: str) -> Optional[_FvgZone]:
        zones = [z for z in active if z.side == side and not z.mitigated]
        if not zones:
            return None
        return zones[-1]

    for i in range(2, n):
        h2, l2 = highs[i - 2], lows[i - 2]
        hi, lo, cl = highs[i], lows[i], closes[i]

        if not np.isnan(h2) and not np.isnan(lo) and lo > h2:
            active.append(_FvgZone(top=float(lo), bottom=float(h2), side="bull", start_idx=i))
            bull_new[i] = True

        if not np.isnan(l2) and not np.isnan(hi) and hi < l2:
            active.append(_FvgZone(top=float(l2), bottom=float(hi), side="bear", start_idx=i))
            bear_new[i] = True

        for z in active:
            if z.mitigated:
                continue
            if z.side == "bull":
                if not np.isnan(lo) and lo <= z.bottom:
                    z.mitigated = True
                    if not np.isnan(cl) and cl > z.top:
                        ifvg_bull[i] = True
            else:
                if not np.isnan(hi) and hi >= z.top:
                    z.mitigated = True
                    if not np.isnan(cl) and cl < z.bottom:
                        ifvg_bear[i] = True

        nb = _nearest("bull")
        nr = _nearest("bear")
        if nb is not None:
            bull_top[i], bull_bot[i] = nb.top, nb.bottom
        if nr is not None:
            bear_top[i], bear_bot[i] = nr.top, nr.bottom

    out = df.copy()
    out["fvg_bull_top"] = bull_top
    out["fvg_bull_bot"] = bull_bot
    out["fvg_bear_top"] = bear_top
    out["fvg_bear_bot"] = bear_bot
    out["fvg_bull_new"] = bull_new
    out["fvg_bear_new"] = bear_new
    out["ifvg_bull"] = ifvg_bull
    out["ifvg_bear"] = ifvg_bear
    return out
