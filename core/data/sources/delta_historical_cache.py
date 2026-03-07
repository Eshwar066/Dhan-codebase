"""
File cache for Delta Exchange historical intraday data.
Uses data_cache/delta_historical/. Delegates to generic historical_cache for load/save.
"""

from pathlib import Path

from core.data.sources.historical_cache import (
    _safe_key,
    load_df as _load_df,
    save_df as _save_df,
)

# Dedicated subdir for Delta historical data
CACHE_DIR = Path("data_cache") / "delta_historical"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def load_df(name: str):
    """Load a DataFrame from Delta cache. Returns None if missing or invalid."""
    return _load_df(CACHE_DIR, name)


def save_df(name: str, df) -> None:
    """Save a DataFrame to Delta cache."""
    _save_df(CACHE_DIR, name, df)


# ---------- Cache key builders (no dates: one file per symbol/series, stitch on request) ----------


def cache_key_delta_intraday(symbol: str, timeframe: str) -> str:
    """Key for Delta intraday cache: symbol + timeframe. Dates not in key."""
    return _safe_key("intraday", symbol, timeframe)
