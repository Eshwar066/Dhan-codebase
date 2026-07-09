"""IntentCreated → execution pipeline."""

from __future__ import annotations

from typing import Any, List, Optional

from core.events.context import EngineEventContext
from core.events.types import Event


class IntentCreatedHandler:
    def __init__(self, ctx: EngineEventContext) -> None:
        self._ctx = ctx

    def __call__(self, event: Event) -> None:
        engine = self._ctx.engine
        payload = event.payload
        strategy = payload.get("strategy")
        symbol = str(payload.get("symbol") or "")
        candle = payload.get("candle") or {}
        ctx = payload.get("ctx")
        intent = payload.get("intent")
        strategy_time_ms = payload.get("strategy_time_ms")
        timeframe = payload.get("timeframe")
        risk_manager = getattr(getattr(engine, "order_router", None), "risk", None)

        if intent is None:
            return

        intents: List[Any]
        if isinstance(intent, list):
            intents = list(intent)
        else:
            intents = [intent]

        engine._enqueue_entry_intents_grouped(
            intents,
            strategy,
            symbol,
            candle,
            strategy_time_ms,
            timeframe,
            risk_manager,
        )


def register_intent_created_handler(ctx: EngineEventContext) -> None:
    handler = IntentCreatedHandler(ctx)
    from core.events.types import EventType

    ctx.bus.subscribe(
        EventType.INTENT_CREATED,
        handler,
        priority=50,
        name="intent_created_execution",
    )
