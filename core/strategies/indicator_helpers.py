"""Reusable indicator computations for strategy ``prepare_indicators``."""

from __future__ import annotations

from typing import Any, List, Optional

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
