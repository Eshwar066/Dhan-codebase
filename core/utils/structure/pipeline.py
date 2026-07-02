"""Composable market-structure pipeline for strategies and indicator manager."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

from core.utils.structure.fvg import add_fvg_columns
from core.utils.structure.order_blocks import add_order_blocks
from core.utils.structure.rsi_divergence import add_rsi_divergence
from core.utils.structure.structure_events import add_bos_choch
from core.utils.structure.swings import add_swing_points

DEFAULT_STRUCTURE_LOOKBACK = 300


@dataclass(frozen=True)
class MarketStructureConfig:
    """Tunable parameters for ``add_market_structure``."""

    swing_left: int = 2
    swing_right: int = 2
    swing_prefix: str = "swing"
    rsi_period: int = 14
    rsi_lookback_swings: int = 5
    ob_body_atr_mult: float = 1.2
    ob_atr_period: int = 14
    include_fvg: bool = True
    include_bos_choch: bool = True
    include_order_blocks: bool = True
    include_rsi_divergence: bool = True


def market_structure_column_names(
    config: Optional[MarketStructureConfig] = None,
) -> List[str]:
    """Columns produced by ``add_market_structure`` (for ``persisted_indicator_keys``)."""
    cfg = config or MarketStructureConfig()
    p = cfg.swing_prefix
    cols = [
        f"{p}_high",
        f"{p}_low",
        f"last_{p}_high",
        f"last_{p}_low",
    ]
    if cfg.include_fvg:
        cols.extend(
            [
                "fvg_bull_top",
                "fvg_bull_bot",
                "fvg_bear_top",
                "fvg_bear_bot",
                "fvg_bull_new",
                "fvg_bear_new",
                "ifvg_bull",
                "ifvg_bear",
            ]
        )
    if cfg.include_bos_choch:
        cols.extend(["bos", "choch", "structure_trend"])
    if cfg.include_order_blocks:
        cols.extend(
            [
                "ob_bull_top",
                "ob_bull_bot",
                "ob_bear_top",
                "ob_bear_bot",
                "ob_bull_new",
                "ob_bear_new",
            ]
        )
    if cfg.include_rsi_divergence:
        cols.extend(["rsi", "rsi_div_bull", "rsi_div_bear"])
    return cols


def add_market_structure(
    df: Any,
    config: Optional[MarketStructureConfig] = None,
) -> Any:
    """
    Full SMC-style feature pass on OHLCV dataframe.

    Safe to call from ``strategy.prepare_indicators`` (live + backtest).
  """
    if df is None or len(df) == 0:
        return df

    cfg = config or MarketStructureConfig()
    p = cfg.swing_prefix

    # Drop prior structure columns so stale jsonl/live_append values cannot
    # pollute RSI (add_rsi_divergence reuses an existing ``rsi`` column).
    stale = [c for c in market_structure_column_names(cfg) if c in df.columns]
    if stale:
        df = df.drop(columns=stale)

    out = add_swing_points(
        df,
        left=cfg.swing_left,
        right=cfg.swing_right,
        prefix=p,
    )
    if cfg.include_fvg:
        out = add_fvg_columns(out)
    if cfg.include_bos_choch:
        out = add_bos_choch(
            out,
            last_swing_high_col=f"last_{p}_high",
            last_swing_low_col=f"last_{p}_low",
            swing_high_col=f"{p}_high",
            swing_low_col=f"{p}_low",
        )
    if cfg.include_order_blocks:
        out = add_order_blocks(
            out,
            body_atr_mult=cfg.ob_body_atr_mult,
            atr_period=cfg.ob_atr_period,
        )
    if cfg.include_rsi_divergence:
        out = add_rsi_divergence(
            out,
            swing_high_col=f"{p}_high",
            swing_low_col=f"{p}_low",
            swing_high_price_col=f"{p}_high_price",
            swing_low_price_col=f"{p}_low_price",
            rsi_period=cfg.rsi_period,
            lookback_swings=cfg.rsi_lookback_swings,
        )
    return out


def structure_signature(config: Optional[MarketStructureConfig] = None) -> str:
    """Stable cache key for ``IndicatorManager.shared_indicator_signature``."""
    cfg = config or MarketStructureConfig()
    return (
        f"ms_v1_{cfg.swing_left}_{cfg.swing_right}_{int(cfg.include_fvg)}"
        f"_{int(cfg.include_bos_choch)}_{int(cfg.include_order_blocks)}"
        f"_{int(cfg.include_rsi_divergence)}_rsi{cfg.rsi_period}"
    )
