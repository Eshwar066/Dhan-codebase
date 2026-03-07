"""
File cache for Dhan historical intraday and futures data.
Uses data_cache/dhan_historical/. Same pattern as NSEClient: load before API, save after.
Delegates to generic historical_cache for load/save.
"""

from pathlib import Path

from core.data.sources.historical_cache import (
    _safe_key,
    load_df as _load_df,
    save_df as _save_df,
)

# Dedicated subdir for Dhan futures and historical long-term data
CACHE_DIR = Path("data_cache") / "dhan_historical"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def load_df(name: str):
    """Load a DataFrame from Dhan cache. Returns None if missing or invalid."""
    return _load_df(CACHE_DIR, name)


def save_df(name: str, df) -> None:
    """Save a DataFrame to Dhan cache."""
    _save_df(CACHE_DIR, name, df)


# ---------- Cache key builders (no dates: one file per symbol/series, stitch on request) ----------


def cache_key_intraday(symbol: str, timeframe: str, exchange: str) -> str:
    """Key for intraday cache: symbol + timeframe + exchange. Dates not in key."""
    return _safe_key("intraday", symbol, timeframe, exchange or "")


def cache_key_futures(
    security_id: str,
    exchange_segment: str,
    instrument: str,
    interval: str,
    oi: bool,
) -> str:
    """Key for futures cache: security + segment + instrument + interval + oi. Dates not in key."""
    return _safe_key(
        "futures",
        security_id,
        exchange_segment,
        instrument,
        interval,
        "oi" if oi else "no_oi",
    )
