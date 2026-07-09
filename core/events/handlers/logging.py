"""Structured event tap — optional JSONL audit log."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from core.events.context import EngineEventContext
from core.events.types import Event, EventType

logger = logging.getLogger(__name__)


class EventTapHandler:
    def __init__(self, ctx: EngineEventContext, log_path: Optional[Path] = None) -> None:
        self._ctx = ctx
        self._log_path = log_path

    def __call__(self, event: Event) -> None:
        if self._log_path is None:
            return
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event.to_log_dict(), default=str) + "\n")
        except Exception:
            logger.debug("Event tap write failed", exc_info=True)


def register_event_tap(
    ctx: EngineEventContext, *, enabled: bool = True
) -> None:
    if not enabled:
        return
    log_dir = Path("logs")
    path = log_dir / f"{ctx.engine_id}_events.jsonl"
    tap = EventTapHandler(ctx, path)
    for event_type in EventType:
        ctx.bus.subscribe(
            event_type,
            tap,
            priority=1000,
            name="event_tap",
        )
