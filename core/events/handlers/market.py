"""BarClosed → exits then entries (priority ordered)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.events.context import EngineEventContext
from core.events.types import Event


class BarClosedExitHandler:
    """Priority 10 — run exits and rollover before entries."""

    def __init__(self, ctx: EngineEventContext) -> None:
        self._ctx = ctx

    def __call__(self, event: Event) -> None:
        payload = event.payload
        symbol = str(payload.get("symbol") or "")
        timeframe = str(payload.get("timeframe") or "")
        candle = payload.get("candle") or {}
        enriched = payload.get("enriched_candle")
        self._ctx.engine._run_exits_and_rollover_for_closed_bar(
            symbol,
            candle,
            timeframe,
            enriched_candle=enriched,
        )


class BarClosedEntryHandler:
    """Priority 20 — evaluate strategies and publish IntentCreated."""

    def __init__(self, ctx: EngineEventContext) -> None:
        self._ctx = ctx

    def __call__(self, event: Event) -> None:
        from core.events.types import EventType, make_event

        engine = self._ctx.engine
        bus = self._ctx.bus
        payload = event.payload
        symbol = str(payload.get("symbol") or "")
        timeframe = payload.get("timeframe")
        enriched = payload.get("enriched_candle") or payload.get("candle") or {}
        eval_key = payload.get("eval_key")
        eval_ts_key = payload.get("eval_ts_key")

        for eval_result in engine._evaluate_strategies_parallel(
            enriched, timeframe=timeframe, already_enriched=True
        ):
            eval_strategy = eval_result.get("strategy")
            eval_strategy_name = str(
                getattr(eval_strategy, "name", "unknown_strategy")
            )
            if engine.engine_logger:
                engine.engine_logger.log(
                    "strategy_evaluated",
                    message=f"Strategy evaluated: {eval_strategy_name}",
                    strategy=eval_strategy_name,
                    symbol=symbol,
                )
            intent = eval_result["intent"]
            if engine._log_entry_skipped_if_paused(
                strategy=eval_strategy,
                symbol=symbol,
                intent=intent,
            ):
                continue
            bus.publish(
                make_event(
                    EventType.INTENT_CREATED,
                    {
                        "strategy": eval_strategy,
                        "symbol": symbol,
                        "candle": payload.get("candle") or enriched,
                        "ctx": eval_result["ctx"],
                        "intent": intent,
                        "strategy_time_ms": eval_result.get("strategy_time_ms"),
                        "timeframe": timeframe,
                    },
                    engine_id=engine.engine_id,
                    trace_id=event.trace_id,
                )
            )

        if eval_key is not None and eval_ts_key is not None:
            engine._last_evaluated_candle_ts[eval_ts_key] = eval_key


def register_bar_closed_handlers(
    ctx: EngineEventContext,
    *,
    filter_fn=None,
) -> None:
    from core.events.types import EventType

    ctx.bus.subscribe(
        EventType.BAR_CLOSED,
        BarClosedExitHandler(ctx),
        priority=10,
        name="bar_closed_exits",
        filter_fn=filter_fn,
    )
    ctx.bus.subscribe(
        EventType.BAR_CLOSED,
        BarClosedEntryHandler(ctx),
        priority=20,
        name="bar_closed_entries",
        filter_fn=filter_fn,
    )
