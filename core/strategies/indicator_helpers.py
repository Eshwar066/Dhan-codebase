"""Reusable indicator computations for strategy ``prepare_indicators``."""

from __future__ import annotations

from typing import Any, List, Optional

import pandas as pd

from core.utils.structure import (
    MarketStructureConfig,
    add_market_structure,
    add_sma,
    market_structure_column_names,
    sma_column_names,
    structure_signature,
)


def add_bollinger_bands(
    df: Any,
    period: int = 20,
    std_dev: float = 2.0,
    *,
    prefix: str = "bb",
) -> Any:
    import pandas as pd

    if df is None or len(df) == 0 or "close" not in df.columns:
        return df
    close = df["close"].astype(float)
    mid = close.rolling(window=period, min_periods=period).mean()
    std = close.rolling(window=period, min_periods=period).std()
    df[f"{prefix}_mid"] = mid
    df[f"{prefix}_upper"] = mid + std_dev * std
    df[f"{prefix}_lower"] = mid - std_dev * std
    return df


def add_ema_high_low(df: Any, period: int = 8) -> Any:
    if df is None or len(df) == 0:
        return df
    span = max(1, int(period))
    if "high" in df.columns:
        df["ema_high"] = df["high"].ewm(span=span, adjust=False).mean()
    if "low" in df.columns:
        df["ema_low"] = df["low"].ewm(span=span, adjust=False).mean()
    return df


def default_persisted_keys_for_rsi() -> List[str]:
    return ["rsi", "prev_rsi"]


def default_persisted_keys_for_ema_high_low() -> List[str]:
    return ["ema_high", "ema_low"]


def default_persisted_keys_for_sma(
    period: Optional[int] = None,
    *,
    periods: Optional[list] = None,
    column: Optional[str] = None,
) -> List[str]:
    """Persist keys matching ``add_sma`` / strategy ``sma_period`` / ``sma_periods``."""
    if periods is not None:
        return sma_column_names(periods)
    if period is not None:
        return sma_column_names(period, column=column)
    return ["sma"]


def default_persisted_keys_for_bollinger(prefix: str = "bb") -> List[str]:
    return [f"{prefix}_upper", f"{prefix}_mid", f"{prefix}_lower"]


def default_persisted_keys_for_market_structure(
    config: Optional[MarketStructureConfig] = None,
) -> List[str]:
    return market_structure_column_names(config)


def prepare_market_structure(
    df: Any,
    config: Optional[MarketStructureConfig] = None,
) -> Any:
    """Alias for ``add_market_structure`` — use inside ``prepare_indicators``."""
    return add_market_structure(df, config=config)


def shared_signature_for_market_structure(
    config: Optional[MarketStructureConfig] = None,
) -> str:
    return structure_signature(config)

# =====
def add_adx(df: Any, period: int = 14) -> Any:
    """Add ADX, DI+, DI- columns to dataframe."""
    if df is None or len(df) == 0:
        return df
    high = df.get("high")
    low = df.get("low")
    close = df.get("close")
    if high is None or low is None or close is None:
        return df

    high = high.astype(float)
    low = low.astype(float)
    close = close.astype(float)

    # True Range
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Directional Movement
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = ((up_move > down_move) & (up_move > 0)) * up_move
    minus_dm = ((down_move > up_move) & (down_move > 0)) * down_move

    # Smoothed TR and DM (Wilder's smoothing)
    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1/period, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1/period, adjust=False).mean() / atr)

    # ADX
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di))
    adx = dx.ewm(alpha=1/period, adjust=False).mean()

    df[f"adx_{period}"] = adx
    df[f"di_plus_{period}"] = plus_di
    df[f"di_minus_{period}"] = minus_di
    return df


def default_persisted_keys_for_adx(period: int = 14) -> List[str]:
    return [f"adx_{period}", f"di_plus_{period}", f"di_minus_{period}"]


def add_supertrend(df: Any, atr_period: int = 10, multiplier: float = 3.0) -> Any:
    """Add Supertrend columns to dataframe."""
    if df is None or len(df) == 0:
        return df
    high = df.get("high")
    low = df.get("low")
    close = df.get("close")
    if high is None or low is None or close is None:
        return df

    high = high.astype(float)
    low = low.astype(float)
    close = close.astype(float)

    # ATR calculation
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/atr_period, adjust=False).mean()

    # Basic upper and lower bands
    hl2 = (high + low) / 2
    basic_ub = hl2 + multiplier * atr
    basic_lb = hl2 - multiplier * atr

    # Final upper and lower bands
    final_ub = basic_ub.copy()
    final_lb = basic_lb.copy()

    for i in range(1, len(df)):
        if close.iloc[i-1] <= final_ub.iloc[i-1]:
            final_ub.iloc[i] = min(basic_ub.iloc[i], final_ub.iloc[i-1])
        else:
            final_ub.iloc[i] = basic_ub.iloc[i]

        if close.iloc[i-1] >= final_lb.iloc[i-1]:
            final_lb.iloc[i] = max(basic_lb.iloc[i], final_lb.iloc[i-1])
        else:
            final_lb.iloc[i] = basic_lb.iloc[i]

    # Supertrend
    st = pd.Series(index=df.index, dtype=float)
    st_dir = pd.Series(index=df.index, dtype=int)

    for i in range(len(df)):
        if i == 0:
            st.iloc[i] = final_lb.iloc[i]
            st_dir.iloc[i] = 1
        elif st.iloc[i-1] == final_ub.iloc[i-1] and close.iloc[i] <= final_ub.iloc[i]:
            st.iloc[i] = final_ub.iloc[i]
            st_dir.iloc[i] = -1
        elif st.iloc[i-1] == final_ub.iloc[i-1] and close.iloc[i] > final_ub.iloc[i]:
            st.iloc[i] = final_lb.iloc[i]
            st_dir.iloc[i] = 1
        elif st.iloc[i-1] == final_lb.iloc[i-1] and close.iloc[i] >= final_lb.iloc[i]:
            st.iloc[i] = final_lb.iloc[i]
            st_dir.iloc[i] = 1
        elif st.iloc[i-1] == final_lb.iloc[i-1] and close.iloc[i] < final_lb.iloc[i]:
            st.iloc[i] = final_ub.iloc[i]
            st_dir.iloc[i] = -1
        else:
            st.iloc[i] = final_lb.iloc[i]
            st_dir.iloc[i] = 1

    atr_key = f"{atr_period}_{multiplier}"
    df[f"supertrend_{atr_key}"] = st
    df[f"supertrend_dir_{atr_key}"] = st_dir
    return df


def default_persisted_keys_for_supertrend(atr_period: int = 10, multiplier: float = 3.0) -> List[str]:
    atr_key = f"{atr_period}_{multiplier}"
    return [f"supertrend_{atr_key}", f"supertrend_dir_{atr_key}"]
