"""Smoke tests for market structure pipeline."""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.utils.structure import (
    LiquidityConfig,
    add_liquidity_sweeps,
    add_market_structure,
    liquidity_column_names,
    market_structure_column_names,
)
from core.utils.structure.pipeline import MarketStructureConfig


def _sample_ohlc(n: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    close = 100 + np.cumsum(rng.normal(0, 0.5, n))
    high = close + rng.uniform(0.2, 1.0, n)
    low = close - rng.uniform(0.2, 1.0, n)
    open_ = close + rng.normal(0, 0.2, n)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC"),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.integers(100, 1000, n),
        }
    )


def test_pipeline_runs_and_columns() -> None:
    df = add_market_structure(_sample_ohlc())
    for col in market_structure_column_names():
        assert col in df.columns, col
    assert df["last_swing_high"].notna().any()
    assert "bos" in df.columns
    assert "pdh" in df.columns
    assert "liq_sweep_bull" in df.columns


def test_liquidity_sweep_detects_pdh_wick() -> None:
    ts = pd.date_range("2026-07-01 18:30", periods=30, freq="1h", tz="UTC")
    rng = np.random.default_rng(1)
    close = 60000 + rng.normal(0, 50, len(ts)).cumsum()
    df = pd.DataFrame(
        {
            "timestamp": ts,
            "open": close,
            "high": close + 80,
            "low": close - 80,
            "close": close,
            "volume": np.ones(len(ts)),
        }
    )
    out = add_liquidity_sweeps(
        df,
        config=LiquidityConfig(session_exchange="DELTA", opening_range_minutes=60),
    )
    for col in liquidity_column_names():
        assert col in out.columns, col
    assert out["pdh"].notna().any()


def test_pipeline_liquidity_can_disable() -> None:
    cfg = MarketStructureConfig(include_liquidity_sweeps=False)
    df = add_market_structure(_sample_ohlc(), cfg)
    assert "pdh" not in df.columns
    assert "liq_sweep_bull" not in df.columns


if __name__ == "__main__":
    test_pipeline_runs_and_columns()
    test_liquidity_sweep_detects_pdh_wick()
    test_pipeline_liquidity_can_disable()
    print("ok")
