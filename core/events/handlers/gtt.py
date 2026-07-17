"""QuoteUpdated → GttFallbackBook (push from feed ticks)."""

from __future__ import annotations

from typing import Any, Optional

from core.events.context import EngineEventContext
from core.events.types import Event


def _quote_from_payload(payload: dict) -> Any:
    from core.orderExecution.gtt_fallback_book import BidAskLtp

    bid = payload.get("bid")
    ask = payload.get("ask")
    ltp = payload.get("ltp")
    ts = payload.get("ts")
    if bid is None and ask is None and ltp is None:
        return None
    return BidAskLtp(
        bid=float(bid) if bid is not None else None,
        ask=float(ask) if ask is not None else None,
        ltp=float(ltp) if ltp is not None else None,
        ts=float(ts) if ts is not None else None,
    )


class GttQuoteHandler:
    def __init__(self, ctx: EngineEventContext) -> None:
        self._ctx = ctx

    def __call__(self, event: Event) -> None:
        engine = self._ctx.engine
        book = getattr(getattr(engine, "order_router", None), "gtt_fallback_book", None)
        if book is None or not book.has_active_watches():
            return
        now_ist = engine._current_ist_now()
        payload = event.payload or {}
        symbol = str(payload.get("symbol") or "").strip()
        source = str(payload.get("source") or "")

        # Maintenance / legacy poll: fill sync + active_until only (no quote trigger).
        # Never fall back to book.tick() here — LiveEngine owns quiet-period
        # QuoteProvider safety via a single book.tick() after publish.
        if source in ("gtt_maintenance", "gtt_poll") or not symbol:
            maintenance = getattr(book, "maintenance_tick", None)
            if callable(maintenance):
                maintenance(now_ist)
            return

        quote = _quote_from_payload(payload)
        on_quote = getattr(book, "on_quote", None)
        if callable(on_quote):
            on_quote(symbol, quote=quote, now_ist=now_ist)
        else:
            book.tick(now_ist)


def register_gtt_quote_handler(ctx: EngineEventContext) -> None:
    from core.events.types import EventType

    ctx.bus.subscribe(
        EventType.QUOTE_UPDATED,
        GttQuoteHandler(ctx),
        priority=40,
        name="gtt_quote_tick",
    )
