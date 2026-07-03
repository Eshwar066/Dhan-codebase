"""Liquidity pools (PDH/PDL, session, OR, equal highs/lows, …) and sweep detection."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class LiquidityConfig:
    """Parameters for ``add_liquidity_levels`` / ``add_liquidity_sweeps``."""

    session_exchange: str = "DELTA"
    opening_range_minutes: int = 30
    equal_tolerance_pct: float = 0.0005
    equal_min_touches: int = 2
    equal_lookback_bars: int = 120
    round_step: Optional[float] = None
    min_pierce_pct: float = 0.0
    swing_prefix: str = "swing"


def liquidity_level_column_names() -> List[str]:
    return [
        "pdh",
        "pdl",
        "pwh",
        "pwl",
        "pmh",
        "pml",
        "session_high",
        "session_low",
        "orh",
        "orl",
        "eqh",
        "eql",
        "round_near",
    ]


def liquidity_sweep_column_names() -> List[str]:
    return [
        "liq_sweep_bull",
        "liq_sweep_bear",
        "sweep_pdh",
        "sweep_pdl",
        "sweep_pwh",
        "sweep_pwl",
        "sweep_pmh",
        "sweep_pml",
        "sweep_session_hi",
        "sweep_session_lo",
        "sweep_orh",
        "sweep_orl",
        "sweep_swing_hi",
        "sweep_swing_lo",
        "sweep_eqh",
        "sweep_eql",
        "sweep_round",
    ]


def liquidity_column_names() -> List[str]:
    return liquidity_level_column_names() + liquidity_sweep_column_names()


def _auto_round_step(price: float) -> float:
    if price <= 0 or math.isnan(price):
        return 100.0
    exp = int(math.floor(math.log10(price))) - 2
    return float(max(10 ** exp, 1.0))


def _session_start_end(exchange: str) -> Tuple[Any, Any]:
    from core.utils.session.market_calendar import MARKET_SESSIONS

    ex = str(exchange or "DELTA").upper()
    sess = MARKET_SESSIONS.get(ex, MARKET_SESSIONS["DELTA"])["regular"]
    return sess["start"], sess["end"]


def _bar_ist(ts: pd.Series) -> pd.Series:
    t = pd.to_datetime(ts, utc=True, errors="coerce")
    return t.dt.tz_convert(IST)


def _in_session_mask(ist: pd.Series, exchange: str) -> np.ndarray:
    start_t, end_t = _session_start_end(exchange)
    tod = ist.dt.time
    if str(exchange).upper() == "DELTA":
        return np.ones(len(ist), dtype=bool)
    return np.array([(start_t <= t <= end_t) for t in tod], dtype=bool)


def _add_calendar_levels(
    df: pd.DataFrame,
    *,
    high_col: str,
    low_col: str,
    ts_col: str,
) -> pd.DataFrame:
    """PDH/PDL, PWH/PWL, PMH/PML from completed prior periods (IST)."""
    out = df.copy()
    n = len(out)
    for col in ("pdh", "pdl", "pwh", "pwl", "pmh", "pml"):
        out[col] = np.nan

    if ts_col not in out.columns or n == 0:
        return out

    ist = _bar_ist(out[ts_col])
    highs = pd.to_numeric(out[high_col], errors="coerce")
    lows = pd.to_numeric(out[low_col], errors="coerce")
    dates = ist.dt.date
    weeks = ist.dt.isocalendar().week.to_numpy()
    years = ist.dt.isocalendar().year.to_numpy()
    months = ist.dt.month.to_numpy()

    day_hi: dict = {}
    day_lo: dict = {}
    week_hi: dict = {}
    week_lo: dict = {}
    month_hi: dict = {}
    month_lo: dict = {}

    for i in range(n):
        d = dates.iloc[i]
        wk = (int(years[i]), int(weeks[i]))
        mo = (int(years[i]), int(months[i]))
        h = highs.iloc[i]
        l = lows.iloc[i]
        if not pd.isna(h):
            day_hi[d] = max(day_hi.get(d, h), h)
            week_hi[wk] = max(week_hi.get(wk, h), h)
            month_hi[mo] = max(month_hi.get(mo, h), h)
        if not pd.isna(l):
            day_lo[d] = min(day_lo.get(d, l), l)
            week_lo[wk] = min(week_lo.get(wk, l), l)
            month_lo[mo] = min(month_lo.get(mo, l), l)

    sorted_days = sorted(day_hi.keys())
    sorted_weeks = sorted(week_hi.keys())
    sorted_months = sorted(month_hi.keys())

    def _prev_key(keys: list, key) -> Optional[Any]:
        for j, k in enumerate(keys):
            if k == key:
                return keys[j - 1] if j > 0 else None
        return None

    pdh = np.full(n, np.nan)
    pdl = np.full(n, np.nan)
    pwh = np.full(n, np.nan)
    pwl = np.full(n, np.nan)
    pmh = np.full(n, np.nan)
    pml = np.full(n, np.nan)

    for i in range(n):
        d = dates.iloc[i]
        wk = (int(years[i]), int(weeks[i]))
        mo = (int(years[i]), int(months[i]))
        prev_d = _prev_key(sorted_days, d)
        prev_w = _prev_key(sorted_weeks, wk)
        prev_m = _prev_key(sorted_months, mo)
        if prev_d is not None:
            pdh[i] = day_hi.get(prev_d, np.nan)
            pdl[i] = day_lo.get(prev_d, np.nan)
        if prev_w is not None:
            pwh[i] = week_hi.get(prev_w, np.nan)
            pwl[i] = week_lo.get(prev_w, np.nan)
        if prev_m is not None:
            pmh[i] = month_hi.get(prev_m, np.nan)
            pml[i] = month_lo.get(prev_m, np.nan)

    out["pdh"] = pdh
    out["pdl"] = pdl
    out["pwh"] = pwh
    out["pwl"] = pwl
    out["pmh"] = pmh
    out["pml"] = pml
    return out


def _add_session_and_or_levels(
    df: pd.DataFrame,
    *,
    high_col: str,
    low_col: str,
    ts_col: str,
    exchange: str,
    or_minutes: int,
) -> pd.DataFrame:
    """Running session high/low and opening-range high/low (IST session)."""
    out = df.copy()
    n = len(out)
    session_high = np.full(n, np.nan)
    session_low = np.full(n, np.nan)
    orh = np.full(n, np.nan)
    orl = np.full(n, np.nan)

    if ts_col not in out.columns or n == 0:
        out["session_high"] = session_high
        out["session_low"] = session_low
        out["orh"] = orh
        out["orl"] = orl
        return out

    ist = _bar_ist(out[ts_col])
    highs = pd.to_numeric(out[high_col], errors="coerce").to_numpy(dtype=float)
    lows = pd.to_numeric(out[low_col], errors="coerce").to_numpy(dtype=float)
    in_sess = _in_session_mask(ist, exchange)
    or_minutes = max(1, int(or_minutes))

    cur_day = None
    sess_hi = np.nan
    sess_lo = np.nan
    or_hi = np.nan
    or_lo = np.nan
    or_done = False
    or_end: Optional[Any] = None

    for i in range(n):
        bar_ist = ist.iloc[i]
        day = bar_ist.date()
        if day != cur_day:
            cur_day = day
            sess_hi = np.nan
            sess_lo = np.nan
            or_hi = np.nan
            or_lo = np.nan
            or_done = False
            start_t, _ = _session_start_end(exchange)
            or_end = bar_ist.replace(
                hour=start_t.hour,
                minute=start_t.minute,
                second=0,
                microsecond=0,
            ) + pd.Timedelta(minutes=or_minutes)
            if str(exchange).upper() == "DELTA":
                or_end = bar_ist.normalize() + pd.Timedelta(minutes=or_minutes)

        if not in_sess[i]:
            session_high[i] = sess_hi
            session_low[i] = sess_lo
            orh[i] = or_hi if or_done else np.nan
            orl[i] = or_lo if or_done else np.nan
            continue

        h = highs[i]
        l = lows[i]
        if not np.isnan(h):
            sess_hi = h if np.isnan(sess_hi) else max(sess_hi, h)
        if not np.isnan(l):
            sess_lo = l if np.isnan(sess_lo) else min(sess_lo, l)

        if not or_done and or_end is not None and bar_ist < or_end:
            if not np.isnan(h):
                or_hi = h if np.isnan(or_hi) else max(or_hi, h)
            if not np.isnan(l):
                or_lo = l if np.isnan(or_lo) else min(or_lo, l)
        elif not or_done and or_end is not None and bar_ist >= or_end:
            or_done = True

        session_high[i] = sess_hi
        session_low[i] = sess_lo
        orh[i] = or_hi if or_done else np.nan
        orl[i] = or_lo if or_done else np.nan

    out["session_high"] = session_high
    out["session_low"] = session_low
    out["orh"] = orh
    out["orl"] = orl
    return out


def _add_equal_high_low_levels(
    df: pd.DataFrame,
    *,
    cfg: LiquidityConfig,
    high_col: str,
    low_col: str,
) -> pd.DataFrame:
    """Most recent equal-high / equal-low pool in lookback (swing pivots preferred)."""
    out = df.copy()
    n = len(out)
    eqh = np.full(n, np.nan)
    eql = np.full(n, np.nan)
    tol_pct = max(0.0, float(cfg.equal_tolerance_pct))
    min_t = max(2, int(cfg.equal_min_touches))
    lb = max(20, int(cfg.equal_lookback_bars))
    p = cfg.swing_prefix
    sh_col = f"{p}_high_price"
    sl_col = f"{p}_low_price"

    highs_src = (
        pd.to_numeric(out[sh_col], errors="coerce").to_numpy(dtype=float)
        if sh_col in out.columns
        else pd.to_numeric(out[high_col], errors="coerce").to_numpy(dtype=float)
    )
    lows_src = (
        pd.to_numeric(out[sl_col], errors="coerce").to_numpy(dtype=float)
        if sl_col in out.columns
        else pd.to_numeric(out[low_col], errors="coerce").to_numpy(dtype=float)
    )

    def _cluster_level(prices: np.ndarray, side: str) -> float:
        vals = prices[~np.isnan(prices)]
        if len(vals) < min_t:
            return np.nan
        best_count = 0
        best_level = np.nan
        for anchor in vals:
            if anchor <= 0:
                continue
            band = abs(anchor) * tol_pct
            if band <= 0:
                band = anchor * 1e-6
            count = int(np.sum(np.abs(vals - anchor) <= band))
            if count >= min_t and count >= best_count:
                cluster = vals[np.abs(vals - anchor) <= band]
                level = float(np.max(cluster) if side == "high" else np.min(cluster))
                if count > best_count or (count == best_count and not np.isnan(level)):
                    best_count = count
                    best_level = level
        return best_level

    for i in range(n):
        start = max(0, i - lb + 1)
        eqh[i] = _cluster_level(highs_src[start : i + 1], "high")
        eql[i] = _cluster_level(lows_src[start : i + 1], "low")

    out["eqh"] = eqh
    out["eql"] = eql
    return out


def _add_round_near(
    df: pd.DataFrame,
    *,
    close_col: str,
    step: Optional[float],
) -> pd.DataFrame:
    out = df.copy()
    closes = pd.to_numeric(out[close_col], errors="coerce").to_numpy(dtype=float)
    near = np.full(len(out), np.nan)
    for i, c in enumerate(closes):
        if np.isnan(c) or c <= 0:
            continue
        st = float(step) if step and step > 0 else _auto_round_step(c)
        near[i] = round(c / st) * st
    out["round_near"] = near
    return out


def add_liquidity_levels(
    df: Any,
    config: Optional[LiquidityConfig] = None,
    *,
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    ts_col: str = "timestamp",
) -> Any:
    """Attach liquidity pool reference levels (no sweep flags)."""
    if df is None or len(df) == 0:
        return df
    for c in (high_col, low_col, close_col):
        if c not in df.columns:
            return df

    cfg = config or LiquidityConfig()
    out = _add_calendar_levels(df, high_col=high_col, low_col=low_col, ts_col=ts_col)
    out = _add_session_and_or_levels(
        out,
        high_col=high_col,
        low_col=low_col,
        ts_col=ts_col,
        exchange=cfg.session_exchange,
        or_minutes=cfg.opening_range_minutes,
    )
    out = _add_equal_high_low_levels(
        out, cfg=cfg, high_col=high_col, low_col=low_col
    )
    out = _add_round_near(out, close_col=close_col, step=cfg.round_step)
    return out


def _pierce_beyond(level: float, extreme: float, side: str, min_pct: float) -> bool:
    if np.isnan(level) or np.isnan(extreme):
        return False
    margin = abs(level) * max(0.0, min_pct)
    if side == "high":
        return extreme > level + margin
    return extreme < level - margin


def _sweep_high_side(
    high: float, close: float, level: float, min_pct: float
) -> bool:
    """Sell-side liquidity sweep: wick above level, close back below."""
    return _pierce_beyond(level, high, "high", min_pct) and not np.isnan(close) and close < level


def _sweep_low_side(
    low: float, close: float, level: float, min_pct: float
) -> bool:
    """Buy-side liquidity sweep: wick below level, close back above."""
    return _pierce_beyond(level, low, "low", min_pct) and not np.isnan(close) and close > level


def _round_sweeps(
    high: float,
    low: float,
    close: float,
    step: float,
    min_pct: float,
) -> Tuple[bool, bool]:
    if np.isnan(high) or np.isnan(low) or step <= 0:
        return False, False
    lo = math.floor(low / step) * step
    hi = math.ceil(high / step) * step
    bull = bear = False
    lvl = lo
    while lvl <= hi + step * 0.5:
        if _sweep_high_side(high, close, lvl, min_pct):
            bear = True
        if _sweep_low_side(low, close, lvl, min_pct):
            bull = True
        lvl += step
    return bull, bear


def add_liquidity_sweeps(
    df: Any,
    config: Optional[LiquidityConfig] = None,
    *,
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
) -> Any:
    """
    Detect liquidity sweeps against levels from ``add_liquidity_levels``.

    Requires swing columns when detecting intraday swing sweeps.
    """
    if df is None or len(df) == 0:
        return df
    for c in (high_col, low_col, close_col):
        if c not in df.columns:
            return df

    cfg = config or LiquidityConfig()
    if "pdh" not in df.columns:
        df = add_liquidity_levels(df, config=cfg, high_col=high_col, low_col=low_col, close_col=close_col)

    out = df.copy()
    n = len(out)
    highs = pd.to_numeric(out[high_col], errors="coerce").to_numpy(dtype=float)
    lows = pd.to_numeric(out[low_col], errors="coerce").to_numpy(dtype=float)
    closes = pd.to_numeric(out[close_col], errors="coerce").to_numpy(dtype=float)
    min_pct = max(0.0, float(cfg.min_pierce_pct))
    p = cfg.swing_prefix
    lsh_col = f"last_{p}_high"
    lsl_col = f"last_{p}_low"

    flags = {name: np.zeros(n, dtype=bool) for name in liquidity_sweep_column_names()}

    for i in range(n):
        h, l, c = highs[i], lows[i], closes[i]
        pairs = (
            ("sweep_pdh", "pdh", "high"),
            ("sweep_pwh", "pwh", "high"),
            ("sweep_pmh", "pmh", "high"),
            ("sweep_session_hi", "session_high", "high"),
            ("sweep_orh", "orh", "high"),
            ("sweep_eqh", "eqh", "high"),
            ("sweep_pdl", "pdl", "low"),
            ("sweep_pwl", "pwl", "low"),
            ("sweep_pml", "pml", "low"),
            ("sweep_session_lo", "session_low", "low"),
            ("sweep_orl", "orl", "low"),
            ("sweep_eql", "eql", "low"),
        )
        for flag, lvl_col, side in pairs:
            if lvl_col not in out.columns:
                continue
            lvl = float(out[lvl_col].iloc[i]) if not pd.isna(out[lvl_col].iloc[i]) else np.nan
            if side == "high" and _sweep_high_side(h, c, lvl, min_pct):
                flags[flag][i] = True
                flags["liq_sweep_bear"][i] = True
            elif side == "low" and _sweep_low_side(l, c, lvl, min_pct):
                flags[flag][i] = True
                flags["liq_sweep_bull"][i] = True

        if lsh_col in out.columns:
            lvl = out[lsh_col].iloc[i]
            if not pd.isna(lvl) and _sweep_high_side(h, c, float(lvl), min_pct):
                flags["sweep_swing_hi"][i] = True
                flags["liq_sweep_bear"][i] = True
        if lsl_col in out.columns:
            lvl = out[lsl_col].iloc[i]
            if not pd.isna(lvl) and _sweep_low_side(l, c, float(lvl), min_pct):
                flags["sweep_swing_lo"][i] = True
                flags["liq_sweep_bull"][i] = True

        ref = closes[i]
        step = float(cfg.round_step) if cfg.round_step and cfg.round_step > 0 else _auto_round_step(ref)
        rb, rr = _round_sweeps(h, l, c, step, min_pct)
        if rb:
            flags["sweep_round"][i] = True
            flags["liq_sweep_bull"][i] = True
        if rr:
            flags["sweep_round"][i] = True
            flags["liq_sweep_bear"][i] = True

    for name, arr in flags.items():
        out[name] = arr.astype(int)
    return out
