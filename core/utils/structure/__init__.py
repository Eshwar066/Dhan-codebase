"""
Market structure utilities (swings, FVG/IFVG, BOS/CHoCH, order blocks, RSI divergence,
liquidity sweeps, SMA, Supertrend, ADX).

Use from strategy ``prepare_indicators``::

    from core.utils.structure import (
        add_market_structure,
        MarketStructureConfig,
        add_sma,
        add_supertrend,
        add_adx,
    )

    def prepare_indicators(self, df):
        df = add_market_structure(df, self.market_structure_config())
        df = add_sma(df, period=self.sma_period)
        df = add_supertrend(
            df,
            length=self.supertrend_length,
            factor=self.supertrend_factor,
        )
        return add_adx(df, period=self.adx_period)
"""

from core.utils.structure.fvg import add_fvg_columns
from core.utils.structure.liquidity import (
    LiquidityConfig,
    add_liquidity_levels,
    add_liquidity_sweeps,
    liquidity_column_names,
)
from core.utils.structure.order_blocks import add_order_blocks
from core.utils.structure.pipeline import (
    DEFAULT_STRUCTURE_LOOKBACK,
    MarketStructureConfig,
    add_market_structure,
    market_structure_column_names,
    structure_signature,
)
from core.utils.structure.adx import (
    add_adx,
    adx_column_names,
    default_persisted_keys_for_adx,
)
from core.utils.structure.rsi_divergence import add_rsi_divergence
from core.utils.structure.sma import add_sma, sma_column_name, sma_column_names
from core.utils.structure.supertrend import add_supertrend, supertrend_column_names
from core.utils.structure.structure_events import add_bos_choch
from core.utils.structure.swings import add_swing_points, swing_pivot_indices

__all__ = [
    "DEFAULT_STRUCTURE_LOOKBACK",
    "LiquidityConfig",
    "MarketStructureConfig",
    "add_adx",
    "add_bos_choch",
    "add_fvg_columns",
    "add_liquidity_levels",
    "add_liquidity_sweeps",
    "add_market_structure",
    "add_order_blocks",
    "add_rsi_divergence",
    "add_sma",
    "add_supertrend",
    "add_swing_points",
    "adx_column_names",
    "default_persisted_keys_for_adx",
    "liquidity_column_names",
    "market_structure_column_names",
    "sma_column_name",
    "sma_column_names",
    "structure_signature",
    "supertrend_column_names",
    "swing_pivot_indices",
]
