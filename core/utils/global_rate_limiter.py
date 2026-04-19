"""
Global per-key rate limiting (wall-clock coordination across components).

Dhan Quote API is capped aggressively (see Introduction rate table); multiple modules
(MarketFeed client, reconciliation, strategies) must share the same bucket — not only
per-instance throttle.
"""

from __future__ import annotations

import threading
import time
from typing import Dict, Optional

# Keys used across codebase
DHAN_QUOTE_API = "dhan_v2_marketfeed"
DHAN_ORDER_API = "dhan_v2_orders"
DHAN_DATA_API = "dhan_v2_data"


class GlobalRateLimiter:
    _instance: Optional["GlobalRateLimiter"] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_mono: Dict[str, float] = {}

    @classmethod
    def instance(cls) -> "GlobalRateLimiter":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def acquire(self, key: str, min_interval_seconds: float) -> None:
        """Block until at least min_interval_seconds since last acquire for this key."""
        if min_interval_seconds <= 0:
            return
        with self._lock:
            now = time.monotonic()
            last = self._last_mono.get(key, 0.0)
            wait = min_interval_seconds - (now - last)
            if wait > 0:
                time.sleep(wait)
            self._last_mono[key] = time.monotonic()
