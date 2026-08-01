"""BarClosed → exits then entries (priority ordered) via services."""

from __future__ import annotations

from core.events.context import EngineEventContext
from core.events.types import Event


class BarClosedExitHandler:
    """Priority 10 — run exits and rollover before entries."""

    def __init__(self, ctx: EngineEventContext) -> None:
        self._ctx = ctx

    def __call__(self, event: Event) -> None:
        engine = self._ctx.engine
        payload = event.payload
        symbol = str(payload.get("symbol") or "")
        timeframe = str(payload.get("timeframe") or "")
        candle = payload.get("candle") or {}
        enriched = payload.get("enriched_candle")
        svc = getattr(engine, "exit_rollover_service", None)
        if svc is not None:
            svc.run_for_closed_bar(
                symbol, candle, timeframe, enriched_candle=enriched
            )
        else:
            engine._run_exits_and_rollover_for_closed_bar(
                symbol, candle, timeframe, enriched_candle=enriched
            )


class BarClosedEntryHandler:
    """Priority 20 — evaluate strategies and publish IntentCreated."""

    def __init__(self, ctx: EngineEventContext) -> None:
        self._ctx = ctx

    def __call__(self, event: Event) -> None:
        engine = self._ctx.engine
        svc = getattr(engine, "strategy_eval_service", None)
        if svc is not None:
            svc.handle_bar_closed(event)
            return
        # Fallback if services not attached
        from core.events.types import EventType, make_event

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
            intent = eval_result["intent"]
            if engine._log_entry_skipped_if_paused(
                strategy=eval_strategy, symbol=symbol, intent=intent
            ):
                continue
            bus.publish(
                make_event(
                    EventType.INTENT_CREATED,
                    {
                        "strategy": eval_strategy,
                        "symbol": symbol,
                        "candle": payload.get("candle") or enriched,
                        "intent": intent,
                        "strategy_time_ms": eval_result.get("strategy_time_ms"),
                        "timeframe": timeframe,
                    },
                    engine_id=engine.engine_id,
                    trace_id=event.trace_id,
                )
            )
        if eval_key is not None and eval_ts_key is not None:
            pending = int(
                getattr(engine, "_last_eval_pending_close_owners", 0) or 0
            )
            queued = int(getattr(engine, "_last_eval_queued", 0) or 0)
            if pending <= 0 or queued > 0:
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
