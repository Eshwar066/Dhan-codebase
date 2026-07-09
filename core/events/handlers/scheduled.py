"""ScheduledSlot → scheduled strategy evaluation."""

from __future__ import annotations

from core.events.context import EngineEventContext
from core.events.types import Event, EventType, make_event


class ScheduledSlotHandler:
    def __init__(self, ctx: EngineEventContext) -> None:
        self._ctx = ctx

    def __call__(self, event: Event) -> None:
        engine = self._ctx.engine
        bus = self._ctx.bus
        payload = event.payload
        strategy = payload.get("strategy")
        sym = str(payload.get("symbol") or "")
        candle = payload.get("candle") or {}
        slot_time = payload.get("slot_time")
        key = payload.get("dedupe_key")

        if key:
            engine._scheduled_evaluated_keys.add(key)

        if engine.engine_logger:
            engine.engine_logger.log(
                "scheduled_eval",
                (
                    f"Scheduled slot {slot_time} symbol={sym} "
                    f"spot={candle.get('close')}"
                ),
                strategy=str(getattr(strategy, "name", "")),
                symbol=sym,
            )

        recent = engine._recent_candles_for_strategy(strategy, candle)
        ctx_pre = engine.build_context_only(candle, recent_candles=recent)
        engine._run_exits_and_rollover(
            strategy, sym, candle, ctx_pre, timeframe=None
        )

        for eval_result in engine._evaluate_strategies_parallel(
            candle, scheduled=True
        ):
            eval_strategy = eval_result.get("strategy")
            eval_strategy_name = str(
                getattr(eval_strategy, "name", "unknown_strategy")
            )
            if engine.engine_logger:
                engine.engine_logger.log(
                    "strategy_evaluated",
                    message=f"Strategy evaluated (scheduled): {eval_strategy_name}",
                    strategy=eval_strategy_name,
                    symbol=sym,
                )
            intent = eval_result["intent"]
            if engine._log_entry_skipped_if_paused(
                strategy=eval_strategy,
                symbol=sym,
                intent=intent,
            ):
                continue
            bus.publish(
                make_event(
                    EventType.INTENT_CREATED,
                    {
                        "strategy": eval_strategy,
                        "symbol": sym,
                        "candle": candle,
                        "ctx": eval_result["ctx"],
                        "intent": intent,
                        "strategy_time_ms": eval_result.get("strategy_time_ms"),
                        "timeframe": None,
                    },
                    engine_id=engine.engine_id,
                    trace_id=event.trace_id,
                )
            )


def register_scheduled_slot_handler(ctx: EngineEventContext) -> None:
    from core.events.types import EventType

    ctx.bus.subscribe(
        EventType.SCHEDULED_SLOT,
        ScheduledSlotHandler(ctx),
        priority=30,
        name="scheduled_slot_eval",
    )
