"""ScheduledSlot → ScheduledEvalService."""

from __future__ import annotations

from core.events.context import EngineEventContext
from core.events.types import Event


class ScheduledSlotHandler:
    def __init__(self, ctx: EngineEventContext) -> None:
        self._ctx = ctx

    def __call__(self, event: Event) -> None:
        engine = self._ctx.engine
        svc = getattr(engine, "scheduled_eval_service", None)
        if svc is not None:
            svc.handle_scheduled_slot(event)
            return
        # Minimal fallback
        from core.events.services.scheduled_eval import ScheduledEvalService

        ScheduledEvalService(engine).handle_scheduled_slot(event)


def register_scheduled_slot_handler(ctx: EngineEventContext) -> None:
    from core.events.types import EventType

    ctx.bus.subscribe(
        EventType.SCHEDULED_SLOT,
        ScheduledSlotHandler(ctx),
        priority=30,
        name="scheduled_slot_eval",
    )
