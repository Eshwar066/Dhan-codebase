"""
Generic file cache for historical DataFrames (intraday, futures, etc.).
Used by source-specific cache modules (dhan_historical_cache, delta_historical_cache).
Load before API, save after; one file per symbol/series, stitch on request.
"""

import json
import re
from pathlib import Path

import pandas as pd


def _safe_key(*parts) -> str:
    """Build a safe cache key from parts (no path separators, short)."""
    return re.sub(r"[^\w\-]", "_", "_".join(str(p) for p in parts))


def _path(cache_dir: Path, name: str) -> Path:
    return cache_dir / f"{name}.json"


def load_df(cache_dir: Path, name: str) -> pd.DataFrame | None:
    """Load a DataFrame from cache. Returns None if missing or invalid."""
    path = _path(cache_dir, name)
    if not path.exists():
        return None
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df
    except Exception:
        return None


def save_df(cache_dir: Path, name: str, df: pd.DataFrame) -> None:
    """Save a DataFrame to cache (JSON records; timestamps and time as strings)."""
    if df is None or df.empty:
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _path(cache_dir, name)
    out = df.copy()
    if "timestamp" in out.columns:
        out = out.assign(timestamp=out["timestamp"].astype(str))
    if "time" in out.columns:
        out = out.assign(time=out["time"].astype(str))
    with open(path, "w") as f:
        json.dump(out.to_dict(orient="records"), f, indent=0)
