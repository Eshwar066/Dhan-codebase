"""
Opt-in mixin: market structure columns on every enriched candle (live + backtest).

Example::

    class MyStrategy(MarketStructureMixin, BaseStrategy):
        timeframe = "15"
        market_structure_enabled = True

        def on_candle(self, candle, ctx):
            if candle.get("bos") == 1 and candle.get("fvg_bull_new"):
                ...
"""

from __future__ import annotations

from typing import Any, List, Optional

from core.utils.structure import (
    DEFAULT_STRUCTURE_LOOKBACK,
    MarketStructureConfig,
    add_market_structure,
    market_structure_column_names,
    structure_signature,
)


class MarketStructureMixin:
    """Add SMC-style features via ``prepare_indicators`` when enabled."""

    market_structure_enabled: bool = False
    _structure_session_exchange: Optional[str] = None

    def set_structure_session_exchange(self, exchange: Optional[str]) -> None:
        """Live/backtest: align liquidity session/OR with venue (NSE vs DELTA)."""
        self._structure_session_exchange = (
            str(exchange or "").strip().upper() or None
        )

    def market_structure_config(self) -> MarketStructureConfig:
        """Override for custom swing/FVG/BOS/liquidity parameters."""
        from dataclasses import replace

        cfg = MarketStructureConfig()
        ex = getattr(self, "_structure_session_exchange", None)
        if ex:
            cfg = replace(cfg, liquidity_session_exchange=ex)
        return cfg

    def get_structure_lookback(self) -> int:
        """Bars of OHLC history ``IndicatorManager`` should retain."""
        return int(getattr(self, "structure_lookback", DEFAULT_STRUCTURE_LOOKBACK))

    def prepare_indicators(self, df: Any) -> Any:
        if getattr(self, "market_structure_enabled", False):
            df = add_market_structure(df, self.market_structure_config())
        parent = super().prepare_indicators  # type: ignore[misc]
        if callable(parent):
            return parent(df)
        return df

    def persisted_indicator_keys(self) -> List[str]:
        keys: List[str] = []
        parent = super().persisted_indicator_keys  # type: ignore[misc]
        if callable(parent):
            try:
                keys.extend(list(parent() or []))
            except Exception:
                pass
        if getattr(self, "market_structure_enabled", False):
            keys.extend(market_structure_column_names(self.market_structure_config()))
        return keys

    def shared_indicator_signature(self) -> str:
        if getattr(self, "market_structure_enabled", False):
            return structure_signature(self.market_structure_config())
        parent = super().shared_indicator_signature  # type: ignore[misc]
        if callable(parent):
            try:
                sig = str(parent() or "").strip()
                if sig:
                    return sig
            except Exception:
                pass
        return ""
