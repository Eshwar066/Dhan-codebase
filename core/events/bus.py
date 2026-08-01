"""Synchronous in-process event bus."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from core.events.types import Event, EventType

logger = logging.getLogger(__name__)

Handler = Callable[[Event], None]
FilterFn = Callable[[Event], bool]


@dataclass
class Subscription:
    handler: Handler
    filter_fn: Optional[FilterFn] = None
    priority: int = 100
    name: str = ""


class EventBus:
    """Priority-ordered synchronous dispatch. Handlers must not re-enter publish."""

    def __init__(self, engine_id: str = "live") -> None:
        self.engine_id = str(engine_id or "live")
        self._subs: Dict[EventType, List[Subscription]] = {}

    def subscribe(
        self,
        event_type: EventType,
        handler: Handler,
        *,
        filter_fn: Optional[FilterFn] = None,
        priority: int = 100,
        name: str = "",
    ) -> None:
        sub = Subscription(
            handler=handler,
            filter_fn=filter_fn,
            priority=int(priority),
            name=str(name or getattr(handler, "__name__", "handler")),
        )
        bucket = self._subs.setdefault(event_type, [])
        bucket.append(sub)
        bucket.sort(key=lambda s: s.priority)

    def publish(self, event: Event) -> None:
        if event.engine_id != self.engine_id:
            event = Event(
                type=event.type,
                payload=event.payload,
                ts=event.ts,
                engine_id=self.engine_id,
                trace_id=event.trace_id,
            )
        for sub in self._subs.get(event.type, []):
            if sub.filter_fn is not None:
                try:
                    if not sub.filter_fn(event):
                        continue
                except Exception:
                    logger.exception(
                        "Event filter failed type=%s handler=%s",
                        event.type.value,
                        sub.name,
                    )
                    continue
            try:
                sub.handler(event)
            except Exception:
                logger.exception(
                    "Event handler failed type=%s handler=%s",
                    event.type.value,
                    sub.name,
                )

    def publish_many(self, events: List[Event]) -> None:
        for event in events:
            self.publish(event)

    def clear(self) -> None:
        self._subs.clear()
