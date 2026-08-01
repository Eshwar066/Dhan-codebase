"""FeedDisconnected / FeedRecovered → FeedSupervisorService."""

from __future__ import annotations

from core.events.context import EngineEventContext
from core.events.types import Event


class FeedSupervisorHandler:
    def __init__(self, ctx: EngineEventContext) -> None:
        self._ctx = ctx

    def on_disconnected(self, event: Event) -> None:
        engine = self._ctx.engine
        svc = getattr(engine, "feed_supervisor_service", None)
        if svc is not None:
            svc.on_disconnected(event)
            return
        from core.events.services.feed_supervisor import FeedSupervisorService

        FeedSupervisorService(engine).on_disconnected(event)

    def on_recovered(self, event: Event) -> None:
        engine = self._ctx.engine
        svc = getattr(engine, "feed_supervisor_service", None)
        if svc is not None:
            svc.on_recovered(event)
            return
        from core.events.services.feed_supervisor import FeedSupervisorService

        FeedSupervisorService(engine).on_recovered(event)


def register_feed_handlers(ctx: EngineEventContext) -> None:
    from core.events.types import EventType

    sup = FeedSupervisorHandler(ctx)
    ctx.bus.subscribe(
        EventType.FEED_DISCONNECTED,
        sup.on_disconnected,
        priority=10,
        name="feed_supervisor_disconnect",
    )
    ctx.bus.subscribe(
        EventType.FEED_RECOVERED,
        sup.on_recovered,
        priority=10,
        name="feed_supervisor_recover",
    )
