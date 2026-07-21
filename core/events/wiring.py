"""Wire event bus handlers from strategy.yaml subscriptions."""

from __future__ import annotations

import logging
import os
from typing import Set

from core.events.bus import EventBus
from core.events.context import EngineEventContext
from core.events.handlers.execution import register_intent_created_handler
from core.events.handlers.feed import register_feed_handlers
from core.events.handlers.fills import register_fill_handlers
from core.events.handlers.gtt import register_gtt_quote_handler
from core.events.handlers.logging import register_event_tap
from core.events.handlers.market import register_bar_closed_handlers
from core.events.handlers.quotes import register_strategy_quote_handler
from core.events.handlers.reentry_at_cost import (
    register_reentry_at_cost_handlers,
    strategy_opts_into_reentry,
)
from core.events.handlers.scheduled import register_scheduled_slot_handler
from core.events.services import attach_event_services
from core.events.subscriptions import (
    bar_closed_filter_for_strategies,
    collect_enabled_events,
)

logger = logging.getLogger(__name__)

# Always register when any strategy is loaded (OMS / feed health).
_ALWAYS_ON = frozenset(
    {
        "IntentCreated",
        "IntentFilled",
        "PositionClosed",
        "FeedDisconnected",
        "FeedRecovered",
    }
)


def create_event_bus(engine: object) -> EventBus:
    engine_id = str(getattr(engine, "engine_id", None) or "live")
    return EventBus(engine_id=engine_id)


def _loaded_strategies(engine: object) -> list:
    strategies = getattr(engine, "strategies", None)
    if strategies:
        return list(strategies)
    strategy = getattr(engine, "strategy", None)
    return [strategy] if strategy is not None else []


def resolve_engine_subscriptions(engine: object) -> Set[str]:
    """Enabled event names for this engine's loaded strategies."""
    strategies = _loaded_strategies(engine)
    if not strategies:
        enabled = set(_ALWAYS_ON)
    else:
        enabled = collect_enabled_events(strategies)
        # Infrastructure handlers stay on whenever the bus is wired.
        enabled |= set(_ALWAYS_ON)
    # Safety: GTT book may exist even if YAML omitted QuoteUpdated.
    book = getattr(getattr(engine, "order_router", None), "gtt_fallback_book", None)
    if book is not None:
        enabled.add("QuoteUpdated")
    # Reentry-at-cost needs IntentFilled + QuoteUpdated when any strategy opts in.
    reentry_book = getattr(
        getattr(engine, "order_router", None), "reentry_at_cost_book", None
    )
    if reentry_book is not None and any(
        strategy_opts_into_reentry(s) for s in strategies
    ):
        enabled.add("IntentFilled")
        enabled.add("QuoteUpdated")
    return enabled


def wire_event_bus(engine: object, bus: EventBus | None = None) -> EventBus:
    """
    Register handlers on ``engine.event_bus`` from strategy subscriptions.

    New strategies declare interest in ``strategy.yaml`` → ``subscriptions:``
    (or inherit defaults from ``schedule.eval_mode`` / ``execution``). After
    ``python -m tools.strategy_manifest generate``, wiring picks them up —
    no edits to this module or LiveEngine.
    """
    if bus is None:
        bus = getattr(engine, "event_bus", None)
    if bus is None:
        bus = create_event_bus(engine)
    engine.event_bus = bus
    attach_event_services(engine)
    ctx = EngineEventContext.from_engine(engine, bus)

    strategies = _loaded_strategies(engine)
    enabled = resolve_engine_subscriptions(engine)
    engine._event_subscriptions = frozenset(enabled)

    if "BarClosed" in enabled:
        register_bar_closed_handlers(
            ctx,
            filter_fn=bar_closed_filter_for_strategies(strategies),
        )
    if "ScheduledSlot" in enabled:
        register_scheduled_slot_handler(ctx)
    if "IntentCreated" in enabled:
        register_intent_created_handler(ctx)
    if "QuoteUpdated" in enabled:
        register_strategy_quote_handler(ctx)
        register_gtt_quote_handler(ctx)
    if "IntentFilled" in enabled or "PositionClosed" in enabled:
        register_fill_handlers(ctx)
    # Reentry-at-cost: fill arm/stop + quote poll (needs book + opt-in strategy).
    if any(strategy_opts_into_reentry(s) for s in strategies):
        register_reentry_at_cost_handlers(ctx)
    if "FeedDisconnected" in enabled or "FeedRecovered" in enabled:
        register_feed_handlers(ctx)

    tap_enabled = str(os.getenv("ALGO_EVENT_TAP", "0")).strip().lower() not in (
        "0",
        "false",
        "no",
        "",
    )
    register_event_tap(ctx, enabled=tap_enabled)

    if getattr(engine, "order_router", None) is not None:
        engine.order_router.event_bus = bus
        engine.order_router.engine_id = ctx.engine_id

    logger.info(
        "Event bus wired engine_id=%s subscriptions=%s",
        ctx.engine_id,
        sorted(enabled),
    )
    return bus
