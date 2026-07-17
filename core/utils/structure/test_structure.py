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


def test_add_sma_strategy_defined_length() -> None:
    from core.utils.structure import add_sma, sma_column_names

    df = _sample_ohlc(80)
    out = add_sma(df, period=20)
    assert "sma_20" in out.columns
    assert out["sma_20"].iloc[19:].notna().all()
    assert out["sma_20"].iloc[:19].isna().all()

    multi = add_sma(_sample_ohlc(80), periods=[9, 21])
    assert sma_column_names([9, 21]) == ["sma_9", "sma_21"]
    assert "sma_9" in multi.columns and "sma_21" in multi.columns
    custom = add_sma(_sample_ohlc(40), period=10, column="sma_fast")
    assert "sma_fast" in custom.columns


def test_add_supertrend_strategy_defined_length_and_factor() -> None:
    from core.utils.structure import add_supertrend, supertrend_column_names

    df = _sample_ohlc(100)
    out = add_supertrend(df, length=10, factor=3.0)
    for column in supertrend_column_names():
        assert column in out.columns, column
    assert out["supertrend"].iloc[:9].isna().all()
    assert out["supertrend"].iloc[9:].notna().all()
    assert set(out["supertrend_direction"].dropna().unique()).issubset({-1.0, 1.0})
    assert (
        out["supertrend_is_bullish"].dropna().astype(bool)
        == (out["supertrend_direction"].dropna() > 0)
    ).all()


if __name__ == "__main__":
    test_pipeline_runs_and_columns()
    test_liquidity_sweep_detects_pdh_wick()
    test_pipeline_liquidity_can_disable()
    test_add_sma_strategy_defined_length()
    test_add_supertrend_strategy_defined_length_and_factor()
    print("ok")
