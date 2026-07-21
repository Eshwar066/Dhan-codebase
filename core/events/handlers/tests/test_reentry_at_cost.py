"""Unit tests for reentry-at-cost event adapters (GTT-style)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.events.context import EngineEventContext
from core.events.handlers.reentry_at_cost import (
    ReentryAtCostFillHandler,
    arm_from_main_sl,
    register_reentry_at_cost_handlers,
    strategy_opts_into_reentry,
    stop_on_main_opened,
    tick_book,
)
from core.events.types import EventType, make_event


class TestStrategyOptsIn(unittest.TestCase):
    def test_detects_class_policy(self):
        s = SimpleNamespace(
            name="ElevenPM",
            reentry_at_cost={"enabled": True, "max_reentries": 1},
        )
        self.assertTrue(strategy_opts_into_reentry(s))

    def test_disabled_or_missing(self):
        self.assertFalse(strategy_opts_into_reentry(None))
        self.assertFalse(strategy_opts_into_reentry(SimpleNamespace(name="X")))
        self.assertFalse(
            strategy_opts_into_reentry(
                SimpleNamespace(name="X", reentry_at_cost={"enabled": False})
            )
        )


class TestArmIdempotent(unittest.TestCase):
    def test_skips_when_watch_already_present(self):
        book = SimpleNamespace(
            _watches={"sid-1": object()},
            maybe_arm_from_main_sl=MagicMock(return_value=True),
        )
        engine = SimpleNamespace(order_router=SimpleNamespace(reentry_at_cost_book=book))
        ok = arm_from_main_sl(
            engine,
            strategy=SimpleNamespace(name="S"),
            instrument=SimpleNamespace(trading_symbol="P-BTC-1"),
            structure_id="sid-1",
        )
        self.assertTrue(ok)
        book.maybe_arm_from_main_sl.assert_not_called()

    def test_arms_when_missing(self):
        book = SimpleNamespace(
            _watches={},
            maybe_arm_from_main_sl=MagicMock(return_value=True),
        )
        engine = SimpleNamespace(order_router=SimpleNamespace(reentry_at_cost_book=book))
        strat = SimpleNamespace(name="S")
        inst = SimpleNamespace(trading_symbol="P-BTC-1")
        ok = arm_from_main_sl(
            engine,
            strategy=strat,
            instrument=inst,
            structure_id="sid-2",
            qty=2,
            side="BUY",
            price=10,
        )
        self.assertTrue(ok)
        book.maybe_arm_from_main_sl.assert_called_once()


class TestFillHandler(unittest.TestCase):
    def test_main_sl_arms(self):
        book = SimpleNamespace(
            _watches={},
            maybe_arm_from_main_sl=MagicMock(return_value=True),
            on_position_opened=MagicMock(),
            cancel_for_structure=MagicMock(),
        )
        engine = SimpleNamespace(
            order_router=SimpleNamespace(
                reentry_at_cost_book=book, intent_store=None
            ),
            _strategy_obj_for_name=lambda _n: SimpleNamespace(
                name="ElevenPM", reentry_at_cost={"enabled": True}
            ),
            instrument_store=None,
        )
        ctx = SimpleNamespace(engine=engine)
        handler = ReentryAtCostFillHandler(ctx)
        inst = SimpleNamespace(
            trading_symbol="P-BTC-100-210726",
            strike=100,
            expiry="210726",
            option_type="PE",
        )
        event = make_event(
            EventType.INTENT_FILLED,
            {
                "tag": "MAIN_SL",
                "strategy": "ElevenPM",
                "structure_id": "sid-x",
                "instrument": inst,
                "metadata_extras": {"entry_premium": 50, "reentry_at_cost": {"enabled": True}},
                "qty": 1,
                "side": "BUY",
                "price": 55,
            },
            engine_id="test",
        )
        handler(event)
        book.maybe_arm_from_main_sl.assert_called_once()

    def test_main_entry_stops(self):
        book = SimpleNamespace(
            _watches={},
            on_position_opened=MagicMock(),
        )
        engine = SimpleNamespace(
            order_router=SimpleNamespace(reentry_at_cost_book=book)
        )
        handler = ReentryAtCostFillHandler(SimpleNamespace(engine=engine))
        event = make_event(
            EventType.INTENT_FILLED,
            {
                "tag": "MAIN",
                "action": "ENTRY",
                "strategy": "ElevenPM",
                "symbol": "P-BTC-1",
                "instrument": SimpleNamespace(trading_symbol="P-BTC-1"),
            },
            engine_id="test",
        )
        handler(event)
        book.on_position_opened.assert_called_once()


class TestRegister(unittest.TestCase):
    def test_register_subscribes(self):
        bus = MagicMock()
        engine = SimpleNamespace(
            order_router=SimpleNamespace(reentry_at_cost_book=object()),
            engine_id="e1",
            engine_logger=None,
        )
        ctx = EngineEventContext.from_engine(engine, bus)
        register_reentry_at_cost_handlers(ctx)
        names = [c.kwargs.get("name") for c in bus.subscribe.call_args_list]
        self.assertIn("reentry_at_cost_fill", names)
        self.assertIn("reentry_at_cost_quote_tick", names)

    def test_tick_book_noop_without_pending(self):
        book = SimpleNamespace(has_pending=lambda: False, tick=MagicMock())
        engine = SimpleNamespace(order_router=SimpleNamespace(reentry_at_cost_book=book))
        self.assertEqual(tick_book(engine), 0)
        book.tick.assert_not_called()


class TestStopHelper(unittest.TestCase):
    def test_stop_on_main_opened(self):
        book = SimpleNamespace(on_position_opened=MagicMock())
        engine = SimpleNamespace(order_router=SimpleNamespace(reentry_at_cost_book=book))
        stop_on_main_opened(
            engine,
            strategy=SimpleNamespace(name="S"),
            instrument=SimpleNamespace(trading_symbol="X"),
        )
        book.on_position_opened.assert_called_once()


if __name__ == "__main__":
    unittest.main()
