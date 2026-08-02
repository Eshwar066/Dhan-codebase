"""LiquiditySweepStrategy package.

Avoid importing the strategy class at package import time so CLI tools like
``rebuild_liquidity_zones`` do not pull the full strategy stack first.
"""

from __future__ import annotations

__all__ = ["LiquiditySweepStrategy"]


def __getattr__(name: str):
    if name == "LiquiditySweepStrategy":
        from core.strategies.crypto.LiquiditySweepStrategy.LiquiditySweepStrategy import (
            LiquiditySweepStrategy,
        )

        return LiquiditySweepStrategy
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
