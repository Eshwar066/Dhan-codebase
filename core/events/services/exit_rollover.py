"""Exit + hedge rollover orchestration (was LiveEngine._run_exits_*)."""

from __future__ import annotations

from typing import Any, Dict, Optional


def _position_allows_strategy_exit(pos: Any) -> bool:
    """MAIN book and post-partial trail legs (tag may become MAIN_TARGET after TARGET fill)."""
    tag_u = str(getattr(pos, "tag", None) or "").upper()
    if tag_u == "HEDGE":
        return False
    return tag_u == "MAIN" or tag_u.startswith("MAIN_")


class ExitRolloverService:
    """
    Runs strategy ``should_exit`` / ``on_position_exit`` and hedge rollover.

    Collaborators stay on the engine (position_manager, order enqueue helpers).
    """

    def __init__(self, engine: Any) -> None:
        self._engine = engine

    def run_for_closed_bar(
        self,
        symbol: str,
        candle: Dict[str, Any],
        timeframe: str,
        enriched_candle: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Exits + monthly hedge rollover on every closed live-feed bar."""
        engine = self._engine
        tf = str(timeframe or "").strip()
        sym_u = str(symbol or "").strip().upper()
        for strategy in engine.strategies:
            if engine._is_scheduled_strategy(strategy, engine.strategy_eval_modes):
                continue
            if str(getattr(strategy, "timeframe", "") or "").strip() != tf:
                continue
            if sym_u and not strategy.applies_to_symbol(sym_u):
                continue
            strategy_candle = enriched_candle
            if strategy_candle is None:
                strategy_candle = engine._enrich_candle_for_strategy(
                    strategy, candle, allow_live_persist=False
                )
            recent = engine._recent_candles_for_strategy(strategy, strategy_candle)
            ctx = engine.build_context_only(strategy_candle, recent_candles=recent)
            self.run_exits_and_rollover(
                strategy, sym_u, strategy_candle, ctx, timeframe=tf
            )

    def run_exits_and_rollover(
        self,
        strategy: Any,
        symbol: str,
        candle: Dict[str, Any],
        ctx: Any,
        timeframe: Optional[str] = None,
        strategy_time_ms: Optional[float] = None,
    ) -> None:
        """Strategy exits and hedge rollover — always run before entry evaluation."""
        engine = self._engine
        risk_manager = getattr(engine.order_router, "risk", None)
        if risk_manager and risk_manager.is_engine_blocked():
            return
        engine.evaluate_sim_broker_stops(candle, ctx)
        open_positions = engine.position_manager.get_open_positions(
            underlying=symbol, strategy=strategy.name
        )
        exited_structures: set[str] = set()
        for position in open_positions:
            if not _position_allows_strategy_exit(position):
                continue
            if not strategy.should_exit(position, candle, ctx):
                continue
            sid = getattr(position, "structure_id", None)
            if sid is not None:
                exited_structures.add(str(sid))
            exit_intents = strategy.on_position_exit(position, candle, ctx) or []
            is_sell = position.net_qty > 0
            required_exit_side = "SELL" if is_sell else "BUY"
            if exit_intents and engine.engine_logger:
                engine.engine_logger.exit_triggered(
                    symbol,
                    required_exit_side,
                    abs(position.net_qty),
                    "Strategy exit",
                )
            for raw_intent in exit_intents:
                engine._process_strategy_exit_intent(
                    raw_intent,
                    strategy,
                    symbol,
                    candle,
                    position,
                    required_exit_side,
                    strategy_time_ms,
                    timeframe,
                    risk_manager,
                )

        rollover_fn = getattr(strategy, "on_candle_rollover", None)
        if not callable(rollover_fn):
            return
        rollover_positions = (
            [
                p
                for p in open_positions
                if str(getattr(p, "structure_id", "") or "") not in exited_structures
            ]
            if exited_structures
            else open_positions
        )
        rollover_intents = (
            rollover_fn(
                open_positions=rollover_positions, candle=candle, ctx=ctx
            )
            or []
        )
        if not rollover_intents:
            return
        if not engine._within_trading_hours():
            if engine.engine_logger:
                engine.engine_logger.time_window_blocked(
                    "Hedge rollover blocked: outside allowed trading hours"
                )
            return
        if engine.engine_logger:
            engine.engine_logger.log(
                "hedge_rollover",
                f"Hedge rollover {len(rollover_intents)} intent(s)",
                strategy=strategy.name,
                symbol=symbol,
                intent_count=len(rollover_intents),
            )
        for raw_intent in rollover_intents:
            engine._process_rollover_intent(
                raw_intent,
                strategy,
                symbol,
                candle,
                strategy_time_ms,
                timeframe,
                risk_manager,
            )
