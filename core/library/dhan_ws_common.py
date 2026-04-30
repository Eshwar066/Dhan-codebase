"""Shared helpers for Dhan WebSocket clients (reconnect jitter, stall watchdog)."""

from __future__ import annotations

import logging
import random
import threading
import time
from datetime import date as dt_date, datetime, time as dtime, timedelta, timezone
from typing import Any, Callable, List, Optional

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))
DHAN_MARKET_OPEN = dtime(hour=9, minute=14)
DHAN_MARKET_CLOSE = dtime(hour=15, minute=31)


def reconnect_sleep_with_jitter(backoff_sec: float, cap: float = 60.0) -> float:
    """Sleep with jitter to avoid synchronized reconnect storms; return next backoff (capped)."""
    delay = min(float(backoff_sec), cap) + random.uniform(0.0, 1.0)
    time.sleep(delay)
    return min(float(backoff_sec) * 1.5, cap)


def _is_exchange_open(exchange: str, now_ist: datetime) -> bool:
    try:
        from core.utils.session.session_manager import SessionManager
        return bool(SessionManager.is_market_open(exchange))
    except Exception:
        if exchange == "MCX":
            if now_ist.weekday() >= 5:
                return False
            try:
                from core.utils.session.session_manager import SessionManager
                if SessionManager.is_holiday(now_ist, "MCX"):
                    return False
            except Exception:
                pass
            return dtime(hour=9, minute=0) <= now_ist.time() <= dtime(hour=23, minute=30)
        if not _is_dhan_trading_day(now_ist.date()):
            return False
        return DHAN_MARKET_OPEN <= now_ist.time() <= DHAN_MARKET_CLOSE


def is_dhan_market_open(
    now_ist: Optional[datetime] = None, exchange: Optional[str] = None
) -> bool:
    now = now_ist or datetime.now(IST)
    if exchange:
        return _is_exchange_open(str(exchange).upper(), now)
    # Unknown venue at callsite (e.g. private order-update WS): stay active
    # whenever any Dhan exchange session is open.
    return _is_exchange_open("INDEX", now) or _is_exchange_open("MCX", now)


def _is_dhan_holiday(day: dt_date) -> bool:
    try:
        from core.utils.session.session_manager import SessionManager

        probe = datetime.combine(day, dtime.min, tzinfo=IST)
        return bool(SessionManager.is_holiday(probe, "INDEX"))
    except Exception:
        return False


def _is_dhan_trading_day(day: dt_date) -> bool:
    if day.weekday() >= 5:
        return False
    if _is_dhan_holiday(day):
        return False
    return True


def sleep_until_next_dhan_market_open(
    stop_event: Optional[threading.Event] = None,
    log: Optional[Callable[..., None]] = None,
    exchange: Optional[str] = None,
) -> None:
    logger_fn = log or logger.info
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        now = datetime.now(IST)
        if is_dhan_market_open(now, exchange=exchange):
            return
        target = str(exchange or "").upper()
        is_mcx = target == "MCX"
        open_time = dtime(hour=9, minute=0) if is_mcx else DHAN_MARKET_OPEN
        close_time = dtime(hour=23, minute=30) if is_mcx else DHAN_MARKET_CLOSE

        candidate = now.date()
        if now.weekday() >= 5 or now.time() > close_time:
            candidate = candidate + timedelta(days=1)
        while True:
            if candidate.weekday() >= 5:
                candidate = candidate + timedelta(days=1)
                continue
            try:
                from core.utils.session.session_manager import SessionManager
                holiday_ex = "MCX" if is_mcx else "INDEX"
                probe = datetime.combine(candidate, dtime.min, tzinfo=IST)
                if SessionManager.is_holiday(probe, holiday_ex):
                    candidate = candidate + timedelta(days=1)
                    continue
            except Exception:
                if not _is_dhan_trading_day(candidate):
                    candidate = candidate + timedelta(days=1)
                    continue
            break

        next_open = datetime.combine(candidate, open_time, tzinfo=IST)
        delay = max(1.0, (next_open - now).total_seconds())
        logger_fn(
            "Market closed — skipping websocket start; sleeping until next open at %s IST",
            next_open.strftime("%Y-%m-%d %H:%M:%S"),
        )
        if stop_event is None:
            time.sleep(delay)
            continue
        if stop_event.wait(timeout=delay):
            return


class StallWatchdog:
    """
    Background thread: if connected but no application traffic for stall_sec, close the socket.
    get_ws() should return current WebSocketApp or None; on_stall() should close it.
    Optional stall_only_when: if provided, close only when it returns True (e.g. market open).
    """

    def __init__(
        self,
        name: str,
        stall_sec: float,
        get_last_activity_ts: Callable[[], float],
        get_ws: Callable[[], Any],
        should_run: Callable[[], bool],
        stall_only_when: Optional[Callable[[], bool]] = None,
    ):
        self._name = name
        self._stall_sec = float(stall_sec)
        self._get_ts = get_last_activity_ts
        self._get_ws = get_ws
        self._should_run = should_run
        self._stall_only_when = stall_only_when if stall_only_when is not None else (lambda: True)
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
                if not self._stall_only_when():
                    continue
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
