"""Delta Exchange WebSocket candlestick resolutions (shared by feed + WS client)."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

# Engine/strategy timeframe key → Delta candlestick channel suffix (candlestick_{suffix}).
RESOLUTION_MAP: Dict[str, str] = {
    "1": "1m",
    "3": "3m",
    "5": "5m",
    "15": "15m",
    "30": "30m",
    "60": "1h",
    "1h": "1h",
    "2h": "2h",
    "2": "2h",
    "4h": "4h",
    "4": "4h",
    "6h": "6h",
    "12h": "12h",
    "1d": "1d",
    "d": "1d",
    "1w": "1w",
}

RESOLUTION_SECONDS: Dict[str, int] = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "12h": 43200,
    "1d": 86400,
    "1w": 604800,
}


def _resolution_sort_key(resolution: str) -> int:
    return RESOLUTION_SECONDS.get(str(resolution), 0)


DELTA_WS_CANDLESTICK_RESOLUTIONS: tuple[str, ...] = tuple(
    sorted(set(RESOLUTION_MAP.values()), key=_resolution_sort_key)
)


def engine_timeframe_to_delta_resolution(timeframe: Optional[str]) -> Optional[str]:
    tf = str(timeframe or "").strip()
    if not tf:
        return None
    if tf in RESOLUTION_MAP:
        return RESOLUTION_MAP[tf]
    tl = tf.lower()
    if tl in RESOLUTION_SECONDS:
        return tl
    return None


def delta_ws_supports_timeframe(timeframe: Optional[str]) -> bool:
    res = engine_timeframe_to_delta_resolution(timeframe)
    return res is not None and res in RESOLUTION_SECONDS


def resolution_to_seconds(resolution: str) -> int:
    return int(RESOLUTION_SECONDS.get(str(resolution).strip().lower(), 60))


def resolutions_from_engine_timeframes(
    engine_timeframes: List[str],
) -> Tuple[List[str], List[str]]:
    """
    Map engine/strategy timeframe keys to unique Delta WS candlestick resolutions.

    Returns (supported_resolutions_sorted, unsupported_timeframes).
    """
    supported: List[str] = []
    unsupported: List[str] = []
    seen: set[str] = set()
    for tf in engine_timeframes or []:
        tf_s = str(tf or "").strip()
        if not tf_s:
            continue
        res = engine_timeframe_to_delta_resolution(tf_s)
        if res is not None and res in RESOLUTION_SECONDS:
            if res not in seen:
                seen.add(res)
                supported.append(res)
        else:
            unsupported.append(tf_s)
    supported.sort(key=_resolution_sort_key)
    return supported, unsupported
