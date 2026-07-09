"""IntentCreated → OMS enqueue (was LiveEngine._enqueue_entry_intents_grouped glue)."""

from __future__ import annotations

from typing import Any, List, Optional

from core.events.types import Event


class ExecutionService:
    """Enqueues entry intents into the OMS pipeline."""

    def __init__(self, engine: Any) -> None:
        self._engine = engine

    def enqueue_intent(
        self,
        *,
        strategy: Any,
        symbol: str,
        candle: Any,
        intent: Any,
        strategy_time_ms: Optional[float] = None,
        timeframe: Optional[str] = None,
    ) -> None:
        if intent is None:
            return
        engine = self._engine
        risk_manager = getattr(getattr(engine, "order_router", None), "risk", None)
        intents: List[Any]
        if isinstance(intent, list):
            intents = list(intent)
        else:
            intents = [intent]
        engine._enqueue_entry_intents_grouped(
            intents,
            strategy,
            symbol,
            candle or {},
            strategy_time_ms,
            timeframe,
            risk_manager,
        )

    def handle_intent_created(self, event: Event) -> None:
        payload = event.payload or {}
        self.enqueue_intent(
            strategy=payload.get("strategy"),
            symbol=str(payload.get("symbol") or ""),
            candle=payload.get("candle") or {},
            intent=payload.get("intent"),
            strategy_time_ms=payload.get("strategy_time_ms"),
            timeframe=payload.get("timeframe"),
        )
