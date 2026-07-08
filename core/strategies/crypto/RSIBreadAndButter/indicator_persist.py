"""
RSIBreadAndButter-only indicator history persist lag.

Fractal swings use ``swing_right`` bars to confirm, so shared
``logs/indicators/{symbol}/{tf}/indicator_history.jsonl`` rows are written
``swing_right`` bars after the closed candle (not on the close itself).

Other strategies must not use this delay — see
``IndicatorManager._structure_confirm_delay_bars`` (defaults to 0).
"""

from __future__ import annotations

from typing import Any

# Match ``RSIBreadAndButter.market_structure_config().swing_right``.
STRUCTURE_PERSIST_DELAY_BARS = 2


def persist_delay_bars(strategy: Any = None) -> int:
    """Bars to wait after close before writing ``live_append`` history."""
    fn = getattr(strategy, "market_structure_config", None) if strategy is not None else None
    if callable(fn):
        try:
            return max(0, int(fn().swing_right))
        except Exception:
            pass
    return int(STRUCTURE_PERSIST_DELAY_BARS)


def persist_tail_rows(strategy: Any = None) -> int:
    """Bars of lag-window used when copying confirmed structure onto the eval candle."""
    return max(1, persist_delay_bars(strategy) + 1)
