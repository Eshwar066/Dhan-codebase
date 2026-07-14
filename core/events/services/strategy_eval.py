"""Strategy evaluation → IntentCreated publish (was handler + LiveEngine eval loop glue)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.events.types import Event, EventType, make_event


class StrategyEvalService:
    """
    Runs parallel strategy evaluation and publishes IntentCreated events.

    Evaluation workers remain on the engine; this service owns the bus-facing loop.
    """

    def __init__(self, engine: Any) -> None:
        self._engine = engine

    def evaluate_and_publish_intents(
        self,
        *,
        candle: Dict[str, Any],
        symbol: str,
        timeframe: Optional[str] = None,
        scheduled: bool = False,
        already_enriched: bool = False,
        source_candle: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
        eval_key: Any = None,
        eval_ts_key: Any = None,
    ) -> List[Dict[str, Any]]:
        engine = self._engine
        bus = getattr(engine, "event_bus", None)
        results = engine._evaluate_strategies_parallel(
            candle,
            timeframe=timeframe,
            scheduled=scheduled,
            already_enriched=already_enriched,
        )
        publish_candle = source_candle if source_candle is not None else candle
        for eval_result in results:
            eval_strategy = eval_result.get("strategy")
            eval_strategy_name = str(
                getattr(eval_strategy, "name", "unknown_strategy")
            )
            label = (
                f"Strategy evaluated (scheduled): {eval_strategy_name}"
                if scheduled
                else f"Strategy evaluated: {eval_strategy_name}"
            )
            if engine.engine_logger:
                engine.engine_logger.log(
                    "strategy_evaluated",
                    message=label,
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
            if bus is not None:
                bus.publish(
                    make_event(
                        EventType.INTENT_CREATED,
                        {
                            "strategy": eval_strategy,
                            "symbol": symbol,
                            "candle": publish_candle,
                            "intent": intent,
                            "strategy_time_ms": eval_result.get("strategy_time_ms"),
                            "timeframe": timeframe,
                        },
                        engine_id=engine.engine_id,
                        trace_id=trace_id,
                    )
                )
            else:
                # No bus: enqueue directly (tests / unwired engine).
                exec_svc = getattr(engine, "execution_service", None)
                if exec_svc is not None:
                    exec_svc.enqueue_intent(
                        strategy=eval_strategy,
                        symbol=symbol,
                        candle=publish_candle,
                        intent=intent,
                        strategy_time_ms=eval_result.get("strategy_time_ms"),
                        timeframe=timeframe,
                    )
                else:
                    risk_manager = getattr(
                        getattr(engine, "order_router", None), "risk", None
                    )
                    engine._enqueue_entry_intents_grouped(
                        intent if isinstance(intent, list) else [intent],
                        eval_strategy,
                        symbol,
                        publish_candle,
                        eval_result.get("strategy_time_ms"),
                        timeframe,
                        risk_manager,
                    )

        if eval_key is not None and eval_ts_key is not None:
            engine._last_evaluated_candle_ts[eval_ts_key] = eval_key
        return results

    def handle_bar_closed(self, event: Event) -> None:
        payload = event.payload
        symbol = str(payload.get("symbol") or "")
        timeframe = payload.get("timeframe")
        enriched = payload.get("enriched_candle") or payload.get("candle") or {}
        self.evaluate_and_publish_intents(
            candle=enriched,
            symbol=symbol,
            timeframe=timeframe,
            already_enriched=True,
            source_candle=payload.get("candle") or enriched,
            trace_id=event.trace_id,
            eval_key=payload.get("eval_key"),
            eval_ts_key=payload.get("eval_ts_key"),
        )
