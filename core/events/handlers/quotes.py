"""QuoteUpdated dispatch for strategies with explicit quote subscriptions."""

from __future__ import annotations

from datetime import datetime, timezone
import logging

from core.events.context import EngineEventContext
from core.events.types import Event

logger = logging.getLogger(__name__)


class StrategyQuoteHandler:
    """Dispatch underlying ticks to strategies that explicitly subscribe to them."""

    def __init__(self, ctx: EngineEventContext) -> None:
        self._ctx = ctx

    def __call__(self, event: Event) -> None:
        from core.events.subscriptions import resolve_strategy_subscriptions
        from core.events.types import EventType, make_event

        engine = self._ctx.engine
        payload = event.payload or {}
        symbol = str(payload.get("symbol") or "").strip().upper()
        ltp = payload.get("ltp")
        if not symbol or ltp is None:
            return
        try:
            price = float(ltp)
        except (TypeError, ValueError):
            return
        if price <= 0:
            return

        raw_ts = payload.get("ts")
        try:
            timestamp = datetime.fromtimestamp(float(raw_ts), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            timestamp = datetime.now(timezone.utc)
        candle = {
            "symbol": symbol,
            "timestamp": timestamp,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": 0,
            "exchange": "DELTA",
            "quote_tick": True,
        }

        strategies = list(getattr(engine, "strategies", None) or [])
        if not strategies:
            strategy = getattr(engine, "strategy", None)
            strategies = [strategy] if strategy is not None else []
        for strategy in strategies:
            on_quote = getattr(strategy, "on_quote", None)
            if not callable(on_quote):
                continue
            subscription = resolve_strategy_subscriptions(strategy).get("QuoteUpdated")
            if not isinstance(subscription, dict) or not subscription.get("enabled"):
                continue
            allowed = {
                str(item).strip().upper()
                for item in (subscription.get("symbols") or [])
                if str(item).strip()
            }
            if allowed and symbol not in allowed:
                continue
            try:
                ctx = engine.build_context_only(candle)
                intents = on_quote(dict(payload), ctx)
            except Exception:
                logger.exception(
                    "Strategy quote hook failed strategy=%s symbol=%s",
                    getattr(strategy, "name", ""),
                    symbol,
                )
                continue
            if not intents:
                continue
            self._ctx.bus.publish(
                make_event(
                    EventType.INTENT_CREATED,
                    {
                        "strategy": strategy,
                        "symbol": symbol,
                        "candle": candle,
                        "intent": intents,
                        "timeframe": "QUOTE",
                    },
                    engine_id=self._ctx.engine_id,
                    trace_id=event.trace_id,
                )
            )


def register_strategy_quote_handler(ctx: EngineEventContext) -> None:
    from core.events.types import EventType

    ctx.bus.subscribe(
        EventType.QUOTE_UPDATED,
        StrategyQuoteHandler(ctx),
        priority=30,
        name="strategy_quote_tick",
    )
