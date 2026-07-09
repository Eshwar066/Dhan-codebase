"""Tests for in-process event bus and manifest subscriptions."""

from core.events.bus import EventBus
from core.events.subscriptions import (
    bar_closed_filter_for_strategies,
    collect_enabled_events,
    event_enabled,
    resolve_strategy_subscriptions,
)
from core.events.types import EventType, make_event
from tools.strategy_manifest.schema import (
    ExecutionSpec,
    default_subscriptions_for,
    resolve_subscriptions,
)


def test_publish_priority_order():
    bus = EventBus(engine_id="test")
    order = []

    def handler_a(_event):
        order.append("a")

    def handler_b(_event):
        order.append("b")

    bus.subscribe(EventType.BAR_CLOSED, handler_b, priority=20, name="b")
    bus.subscribe(EventType.BAR_CLOSED, handler_a, priority=10, name="a")
    bus.publish(
        make_event(EventType.BAR_CLOSED, {"symbol": "NIFTY"}, engine_id="test")
    )
    assert order == ["a", "b"]


def test_filter_skips_handler():
    bus = EventBus(engine_id="test")
    hits = []

    bus.subscribe(
        EventType.INTENT_CREATED,
        lambda _e: hits.append(1),
        filter_fn=lambda e: e.payload.get("symbol") == "BTCUSD",
        name="btc_only",
    )
    bus.publish(
        make_event(
            EventType.INTENT_CREATED,
            {"symbol": "NIFTY"},
            engine_id="test",
        )
    )
    bus.publish(
        make_event(
            EventType.INTENT_CREATED,
            {"symbol": "BTCUSD"},
            engine_id="test",
        )
    )
    assert hits == [1]


def test_handler_exception_does_not_block_others():
    bus = EventBus(engine_id="test")
    order = []

    def bad(_event):
        raise RuntimeError("boom")

    def good(_event):
        order.append("ok")

    bus.subscribe(EventType.QUOTE_UPDATED, bad, priority=10, name="bad")
    bus.subscribe(EventType.QUOTE_UPDATED, good, priority=20, name="good")
    bus.publish(
        make_event(EventType.QUOTE_UPDATED, {}, engine_id="test")
    )
    assert order == ["ok"]


def test_default_subscriptions_live_feed():
    subs = default_subscriptions_for(
        eval_mode="live_feed",
        timeframe="15",
        symbols=["NIFTY"],
        execution=ExecutionSpec(),
    )
    assert subs.enabled("BarClosed")
    assert not subs.enabled("ScheduledSlot")
    assert not subs.enabled("QuoteUpdated")
    assert subs.events["BarClosed"].timeframes == ["15"]
    assert subs.enabled("IntentCreated")


def test_default_subscriptions_scheduled_gtt():
    subs = default_subscriptions_for(
        eval_mode="scheduled",
        timeframe=None,
        symbols=["BANKNIFTY"],
        execution=ExecutionSpec(mode="HYBRID_GTT", gtt_fallback={"trigger_field": "ask"}),
    )
    assert not subs.enabled("BarClosed")
    assert subs.enabled("ScheduledSlot")
    assert subs.enabled("QuoteUpdated")


def test_resolve_subscriptions_override():
    subs = resolve_subscriptions(
        {"BarClosed": False, "QuoteUpdated": True},
        eval_mode="live_feed",
        timeframe="60",
        symbols=["NIFTY"],
        execution=ExecutionSpec(),
    )
    assert not subs.enabled("BarClosed")
    assert subs.enabled("QuoteUpdated")


def test_collect_enabled_events_union():
    class _S:
        def __init__(self, name):
            self.name = name

    table = {
        "A": {
            "BarClosed": {"enabled": True, "timeframes": ["15"]},
            "IntentCreated": {"enabled": True},
        },
        "B": {
            "ScheduledSlot": {"enabled": True},
            "QuoteUpdated": {"enabled": True},
        },
    }
    enabled = collect_enabled_events([_S("A"), _S("B")], table)
    assert "BarClosed" in enabled
    assert "ScheduledSlot" in enabled
    assert "QuoteUpdated" in enabled


def test_bar_closed_filter_timeframe():
    class _S:
        name = "A"

    table = {
        "A": {
            "BarClosed": {
                "enabled": True,
                "timeframes": ["15"],
                "symbols": ["NIFTY"],
            }
        }
    }
    filt = bar_closed_filter_for_strategies([_S()], table)
    assert filt(
        make_event(
            EventType.BAR_CLOSED,
            {"symbol": "NIFTY", "timeframe": "15"},
            engine_id="t",
        )
    )
    assert not filt(
        make_event(
            EventType.BAR_CLOSED,
            {"symbol": "NIFTY", "timeframe": "60"},
            engine_id="t",
        )
    )
    assert not filt(
        make_event(
            EventType.BAR_CLOSED,
            {"symbol": "BANKNIFTY", "timeframe": "15"},
            engine_id="t",
        )
    )


def test_resolve_strategy_subscriptions_from_table():
    class _S:
        name = "IPOBreakout"

    table = {
        "IPOBreakout": {"BarClosed": {"enabled": True, "timeframes": ["DAY"]}},
    }
    subs = resolve_strategy_subscriptions(_S(), table)
    assert event_enabled(subs, "BarClosed")


def test_gtt_quote_handler_push_calls_on_quote():
    from core.events.context import EngineEventContext
    from core.events.handlers.gtt import GttQuoteHandler
    from core.orderExecution.gtt_fallback_book import BidAskLtp

    calls = []

    class _Book:
        def has_active_watches(self):
            return True

        def on_quote(self, symbol, quote=None, now_ist=None):
            calls.append(("on_quote", symbol, quote))

        def maintenance_tick(self, now_ist=None):
            calls.append(("maintenance",))

        def tick(self, now_ist=None):
            calls.append(("tick",))

    class _Router:
        gtt_fallback_book = _Book()

    class _Engine:
        order_router = _Router()
        engine_id = "t"

        def _current_ist_now(self):
            return None

    bus = EventBus(engine_id="t")
    ctx = EngineEventContext.from_engine(_Engine(), bus)
    handler = GttQuoteHandler(ctx)
    handler(
        make_event(
            EventType.QUOTE_UPDATED,
            {
                "symbol": "BANKNIFTY25APR50000CE",
                "bid": 99.0,
                "ask": 100.0,
                "ltp": 99.5,
                "source": "feed",
            },
            engine_id="t",
        )
    )
    assert len(calls) == 1
    assert calls[0][0] == "on_quote"
    assert calls[0][1] == "BANKNIFTY25APR50000CE"
    assert isinstance(calls[0][2], BidAskLtp)
    assert calls[0][2].ask == 100.0


def test_gtt_quote_handler_maintenance():
    from core.events.context import EngineEventContext
    from core.events.handlers.gtt import GttQuoteHandler

    calls = []

    class _Book:
        def has_active_watches(self):
            return True

        def on_quote(self, *a, **k):
            calls.append("on_quote")

        def maintenance_tick(self, now_ist=None):
            calls.append("maintenance")

        def tick(self, now_ist=None):
            calls.append("tick")

    class _Router:
        gtt_fallback_book = _Book()

    class _Engine:
        order_router = _Router()
        engine_id = "t"

        def _current_ist_now(self):
            return None

    bus = EventBus(engine_id="t")
    ctx = EngineEventContext.from_engine(_Engine(), bus)
    GttQuoteHandler(ctx)(
        make_event(
            EventType.QUOTE_UPDATED,
            {"source": "gtt_maintenance"},
            engine_id="t",
        )
    )
    assert calls == ["maintenance"]
