"""Shared helpers for Dhan WebSocket clients (reconnect jitter, stall watchdog)."""

from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any, Callable, List, Optional

logger = logging.getLogger(__name__)


def reconnect_sleep_with_jitter(backoff_sec: float, cap: float = 60.0) -> float:
    """Sleep with jitter to avoid synchronized reconnect storms; return next backoff (capped)."""
    delay = min(float(backoff_sec), cap) + random.uniform(0.0, 1.0)
    time.sleep(delay)
    return min(float(backoff_sec) * 1.5, cap)


class StallWatchdog:
    """
    Background thread: if connected but no application traffic for stall_sec, close the socket.
    get_ws() should return current WebSocketApp or None; on_stall() should close it.
    """

    def __init__(
        self,
        name: str,
        stall_sec: float,
        get_last_activity_ts: Callable[[], float],
        get_ws: Callable[[], Any],
        should_run: Callable[[], bool],
    ):
        self._name = name
        self._stall_sec = float(stall_sec)
        self._get_ts = get_last_activity_ts
        self._get_ws = get_ws
        self._should_run = should_run
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def enabled(self) -> bool:
        return self._stall_sec > 0

    def start(self) -> None:
        if not self.enabled:
            return
        self._stop.clear()
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

    def _loop(self) -> None:
        poll = min(max(2.0, self._stall_sec / 4.0), 10.0)
        while not self._stop.wait(timeout=poll):
            if not self._should_run():
                continue
            if self._stall_sec <= 0:
                continue
            ws = self._get_ws()
            if ws is None:
                continue
            try:
                sock = ws.sock
                if sock is None or not getattr(sock, "connected", False):
                    continue
            except Exception:
                continue
            idle = time.time() - self._get_ts()
            if idle > self._stall_sec:
                logger.warning(
                    "%s: stall watchdog closing socket (no traffic %.1fs > %.1fs)",
                    self._name,
                    idle,
                    self._stall_sec,
                )
                try:
                    ws.close()
                except Exception as e:
                    logger.debug("%s stall close: %s", self._name, e)


class DhanFeedSupervisor:
    """
    Optional control-plane helper: hold references to Dhan market / order / depth clients
    and emit a single health line (generation + warm flags).
    Feeds self-heal via reconnect loops + stall watchdog; this only observes.
    """

    def __init__(
        self,
        market_ws: Any = None,
        order_ws: Any = None,
        depth_ws: Any = None,
    ):
        self.market_ws = market_ws
        self.order_ws = order_ws
        self.depth_ws = depth_ws

    def log_snapshot(self, log_fn: Optional[Callable[..., None]] = None) -> None:
        log = log_fn or logger.info
        parts: List[str] = []

        def _add(name: str, ws: Any) -> None:
            if ws is None:
                return
            try:
                gen = int(getattr(ws, "connect_generation", 0))
                warm = bool(getattr(ws, "is_warm", False))
                parts.append(f"{name}_gen={gen} warm={warm}")
            except Exception:
                parts.append(f"{name}=?")

        _add("market", self.market_ws)
        _add("order", self.order_ws)
        _add("depth", self.depth_ws)
        if parts:
            log("Dhan feed supervisor: %s", " | ".join(parts))
