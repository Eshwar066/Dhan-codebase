"""Smoke tests for market structure pipeline."""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.utils.structure import add_market_structure, market_structure_column_names


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


if __name__ == "__main__":
    test_pipeline_runs_and_columns()
    print("ok")
