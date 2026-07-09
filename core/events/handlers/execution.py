"""IntentCreated → ExecutionService."""

from __future__ import annotations

from core.events.context import EngineEventContext
from core.events.types import Event


class IntentCreatedHandler:
    def __init__(self, ctx: EngineEventContext) -> None:
        self._ctx = ctx

    def __call__(self, event: Event) -> None:
        engine = self._ctx.engine
        svc = getattr(engine, "execution_service", None)
        if svc is not None:
            svc.handle_intent_created(event)
            return
        from core.events.services.execution import ExecutionService

        ExecutionService(engine).handle_intent_created(event)


def register_intent_created_handler(ctx: EngineEventContext) -> None:
    from core.events.types import EventType

    ctx.bus.subscribe(
        EventType.INTENT_CREATED,
        IntentCreatedHandler(ctx),
        priority=50,
        name="intent_created_execution",
    )
