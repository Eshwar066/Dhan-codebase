"""FeedDisconnected / FeedRecovered → entry pause flags."""

from __future__ import annotations

import logging
from typing import Any

from core.events.types import Event

logger = logging.getLogger(__name__)


class FeedSupervisorService:
    def __init__(self, engine: Any) -> None:
        self._engine = engine

    def on_disconnected(self, event: Event) -> None:
        engine = self._engine
        payload = event.payload or {}
        symbols = payload.get("symbols") or []
        reason = str(payload.get("reason") or "feed_disconnected")
        engine._entries_paused_feed_stale = True
        for sym in symbols:
            st = engine._symbol_state.setdefault(sym, {})
            if isinstance(st, dict):
                st["feed_stale"] = True
        if engine.engine_logger:
            engine.engine_logger.log("feed_disconnected", reason, symbols=symbols)
        else:
            logger.warning("Feed disconnected: %s symbols=%s", reason, symbols)

    def on_recovered(self, event: Event) -> None:
        engine = self._engine
        payload = event.payload or {}
        symbols = payload.get("symbols") or []
        engine._entries_paused_feed_stale = False
        for sym in symbols:
            st = engine._symbol_state.get(sym)
            if isinstance(st, dict):
                st["feed_stale"] = False
        if engine.engine_logger:
            engine.engine_logger.log("feed_recovered", "Feed recovered", symbols=symbols)
        else:
            logger.info("Feed recovered symbols=%s", symbols)
