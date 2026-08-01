"""IntentFilled / PositionClosed — audit and risk hooks."""

from __future__ import annotations

import logging

from core.events.context import EngineEventContext
from core.events.types import Event

logger = logging.getLogger(__name__)


class FillAuditHandler:
    def __init__(self, ctx: EngineEventContext) -> None:
        self._ctx = ctx

    def on_intent_filled(self, event: Event) -> None:
        if self._ctx.engine_logger:
            p = event.payload
            self._ctx.engine_logger.log(
                "intent_filled",
                f"Intent filled {p.get('intent_id')}",
                intent_id=p.get("intent_id"),
                strategy=p.get("strategy"),
                symbol=p.get("symbol"),
            )

    def on_position_closed(self, event: Event) -> None:
        if self._ctx.engine_logger:
            p = event.payload
            self._ctx.engine_logger.log(
                "position_closed",
                f"Position closed {p.get('symbol')}",
                strategy=p.get("strategy"),
                symbol=p.get("symbol"),
                realized_pnl=p.get("realized_pnl"),
            )


def register_fill_handlers(ctx: EngineEventContext) -> None:
    from core.events.types import EventType

    audit = FillAuditHandler(ctx)
    ctx.bus.subscribe(
        EventType.INTENT_FILLED,
        audit.on_intent_filled,
        priority=200,
        name="fill_audit",
    )
    ctx.bus.subscribe(
        EventType.POSITION_CLOSED,
        audit.on_position_closed,
        priority=200,
        name="position_closed_audit",
    )
