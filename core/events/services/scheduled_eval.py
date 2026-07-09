"""ScheduledSlot orchestration."""

from __future__ import annotations

from typing import Any

from core.events.types import Event


class ScheduledEvalService:
    """Scheduled IST-slot eval: exits then entry IntentCreated publishes."""

    def __init__(self, engine: Any) -> None:
        self._engine = engine

    def handle_scheduled_slot(self, event: Event) -> None:
        engine = self._engine
        payload = event.payload or {}
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

        exit_svc = getattr(engine, "exit_rollover_service", None)
        if exit_svc is not None:
            exit_svc.run_exits_and_rollover(
                strategy, sym, candle, ctx_pre, timeframe=None
            )
        else:
            engine._run_exits_and_rollover(
                strategy, sym, candle, ctx_pre, timeframe=None
            )

        eval_svc = getattr(engine, "strategy_eval_service", None)
        if eval_svc is not None:
            eval_svc.evaluate_and_publish_intents(
                candle=candle,
                symbol=sym,
                timeframe=None,
                scheduled=True,
                source_candle=candle,
                trace_id=event.trace_id,
            )
        else:
            # Fallback without services (should not happen after wire_event_bus).
            from core.events.types import EventType, make_event

            bus = getattr(engine, "event_bus", None)
            for eval_result in engine._evaluate_strategies_parallel(
                candle, scheduled=True
            ):
                eval_strategy = eval_result.get("strategy")
                intent = eval_result["intent"]
                if engine._log_entry_skipped_if_paused(
                    strategy=eval_strategy, symbol=sym, intent=intent
                ):
                    continue
                if bus is not None:
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
