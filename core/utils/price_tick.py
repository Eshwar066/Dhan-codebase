"""Exchange tick-size helpers for order prices (NSE/BSE/Dhan)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional


def normalize_dhan_tick_size(tick: Optional[float]) -> float:
    """
  Dhan ``SEM_TICK_SIZE`` may be stored as rupees (0.05) or paise (5 → ₹0.05).
  """
    if tick is None:
        return 0.05
    try:
        t = float(tick)
    except (TypeError, ValueError):
        return 0.05
    if t <= 0:
        return 0.05
    if t >= 1.0:
        t = t / 100.0
    return t if t > 0 else 0.05


def resolve_tick_size(
    trading_symbol: str,
    instrument_store: Any = None,
    *,
    instrument: Any = None,
    default: float = 0.05,
) -> float:
    tick = getattr(instrument, "tick_size", None) if instrument is not None else None
    if tick is not None:
        return normalize_dhan_tick_size(tick)
    sym = str(trading_symbol or "").strip()
    if instrument_store is not None and sym and hasattr(instrument_store, "get_tick_size"):
        try:
            store_tick = instrument_store.get_tick_size(sym)
        except Exception:
            store_tick = None
        if store_tick is not None:
            return normalize_dhan_tick_size(store_tick)
    return normalize_dhan_tick_size(default)


def round_by_tick_size(
    price: Optional[float],
    tick_size: Optional[float],
    *,
    floor_or_ceil: Optional[str] = None,
) -> Optional[float]:
    """Round price to exchange tick size. Uses Decimal to avoid float precision errors."""
    if price is None:
        return None
    try:
        p = float(price)
    except (TypeError, ValueError):
        return None
    if p != p or p <= 0:
        return None
    tick = normalize_dhan_tick_size(tick_size)
    dec_p = Decimal(str(p))
    dec_ts = Decimal(str(tick))
    remainder = dec_p % dec_ts
    if remainder == 0:
        return float(dec_p)
    if floor_or_ceil is None:
        floor_or_ceil = "ceil" if (remainder >= dec_ts / 2) else "floor"
    if floor_or_ceil == "ceil":
        dec_p = dec_p - remainder + dec_ts
    else:
        dec_p = dec_p - remainder
    frac = format(dec_ts, "f").rstrip("0").split(".")[-1] if "." in format(dec_ts, "f") else "0"
    n = len(frac) if frac else 0
    return float(round(dec_p, n))
