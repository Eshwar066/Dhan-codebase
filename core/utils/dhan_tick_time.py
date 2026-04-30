"""
Dhan last-trade-time (LTT) normalization: binary feed uses int32 unix seconds that may
alternate between interpretations (~IST vs UTC). Align to UTC epoch for monotonic ticks
and candle buckets (same rules as LiveEngineHelpersMixin._dhan_repair_naive_as_ist_wallclock).
"""

from __future__ import annotations

import datetime as dt
from datetime import timezone
from typing import Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore[misc, assignment]

_IST: Optional["ZoneInfo"] = ZoneInfo("Asia/Kolkata") if ZoneInfo else None


def repair_dhan_tick_unix_seconds(ts: float) -> float:
    """
    Map broker LTT unix seconds to canonical UTC epoch seconds.

    - If decoding as UTC yields a datetime ~5.5h **ahead** of wall UTC, treat wall
      components as IST (DHAN IST-as-naive-UTC quirk).
    - If ~5.5h **behind** wall UTC, shift forward by one IST offset (alternate packet path).
    """
    try:
        t = float(ts)
    except (TypeError, ValueError):
        return float(ts)
    if t <= 0 or t < 1e8:
        return t

    naive = dt.datetime.utcfromtimestamp(t)
    nowu = dt.datetime.utcnow()
    dsec = (naive - nowu).total_seconds()

    if 4.25 * 3600 <= dsec <= 7.25 * 3600 and _IST is not None:
        try:
            aware = naive.replace(tzinfo=_IST).astimezone(timezone.utc)
            return float(aware.timestamp())
        except Exception:
            return t - 19800.0

    if -7.25 * 3600 <= dsec <= -4.25 * 3600:
        return t + 19800.0

    return t


def unix_epoch_to_ist_iso(ts: float) -> str:
    """UTC unix epoch → ISO-8601 string in Asia/Kolkata (IST)."""
    try:
        sec = float(ts)
    except (TypeError, ValueError):
        return ""
    tz = _IST or dt.timezone(dt.timedelta(hours=5, minutes=30))
    return dt.datetime.fromtimestamp(sec, tz=timezone.utc).astimezone(tz).isoformat()
