"""
Market structure utilities (swings, FVG/IFVG, BOS/CHoCH, order blocks, RSI divergence).

Use from strategy ``prepare_indicators``::

    from core.utils.structure import add_market_structure, MarketStructureConfig

    def prepare_indicators(self, df):
        return add_market_structure(df, self.market_structure_config())
"""

from core.utils.structure.fvg import add_fvg_columns
from core.utils.structure.order_blocks import add_order_blocks
from core.utils.structure.pipeline import (
    DEFAULT_STRUCTURE_LOOKBACK,
    MarketStructureConfig,
    add_market_structure,
    market_structure_column_names,
    structure_signature,
)
from core.utils.structure.rsi_divergence import add_rsi_divergence
from core.utils.structure.structure_events import add_bos_choch
from core.utils.structure.swings import add_swing_points, swing_pivot_indices

__all__ = [
    "DEFAULT_STRUCTURE_LOOKBACK",
    "MarketStructureConfig",
    "add_bos_choch",
    "add_fvg_columns",
    "add_market_structure",
    "add_order_blocks",
    "add_rsi_divergence",
    "add_swing_points",
    "market_structure_column_names",
    "structure_signature",
    "swing_pivot_indices",
]
