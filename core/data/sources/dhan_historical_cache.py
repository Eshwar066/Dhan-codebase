"""
File cache for Dhan historical intraday and futures data.
Uses data_cache/dhan_historical/ so futures and long-term historical data
are separate from NSE/other caches. Same pattern as NSEClient: load before API, save after.
"""

import json
import os
import re
from pathlib import Path

import pandas as pd

# Dedicated subdir for Dhan futures and historical long-term data
CACHE_DIR = Path("data_cache") / "dhan_historical"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _safe_key(*parts) -> str:
    """Build a safe cache key from parts (no path separators, short)."""
    return re.sub(r"[^\w\-]", "_", "_".join(str(p) for p in parts))


def _path(name: str) -> Path:
    return CACHE_DIR / f"{name}.json"


def load_df(name: str) -> pd.DataFrame | None:
    """Load a DataFrame from cache. Returns None if missing or invalid."""
    path = _path(name)
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


def save_df(name: str, df: pd.DataFrame) -> None:
    """Save a DataFrame to cache (JSON records; timestamps and time as strings)."""
    if df is None or df.empty:
        return
    path = _path(name)
    out = df.copy()
    # JSON-serializable: datetime/time objects → string
    if "timestamp" in out.columns:
        out = out.assign(timestamp=out["timestamp"].astype(str))
    if "time" in out.columns:
        out = out.assign(time=out["time"].astype(str))
    with open(path, "w") as f:
        json.dump(out.to_dict(orient="records"), f, indent=0)


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
