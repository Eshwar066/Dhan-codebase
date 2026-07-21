"""Integration: reentry-at-cost is hooks XOR bus (bus-only when wired)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.events.bus import EventBus
from core.events.handlers.reentry_at_cost import (
    assert_reentry_path_xor,
    mark_reentry_bus_wired,
    reentry_driven_by_bus,
)
from core.events.types import EventType, make_event
from core.events.wiring import wire_event_bus


class TestAssertXor(unittest.TestCase):
    def test_xor_allows_single_path(self):
        assert_reentry_path_xor(bus_wired=True, hooks_drive=False)
        assert_reentry_path_xor(bus_wired=False, hooks_drive=True)
        assert_reentry_path_xor(bus_wired=False, hooks_drive=False)

    def test_xor_rejects_both(self):
        with self.assertRaises(AssertionError):
            assert_reentry_path_xor(bus_wired=True, hooks_drive=True)


class TestBusOnlyWhenWired(unittest.TestCase):
    def _opt_in_strategy(self):
        return SimpleNamespace(
            name="ElevenPM",
            reentry_at_cost={"enabled": True, "max_reentries": 1},
            timeframe="EVENT",
            ENTRY_EXECUTION_MODE="MARKET",
        )

    def _engine_with_book(self, book: MagicMock):
        return SimpleNamespace(
            engine_id="test_reentry_xor",
            engine_logger=None,
            strategies=[self._opt_in_strategy()],
            strategy=self._opt_in_strategy(),
            order_router=SimpleNamespace(
                reentry_at_cost_book=book,
                gtt_fallback_book=None,
                intent_store=None,
            ),
            _strategy_obj_for_name=lambda _n: self._opt_in_strategy(),
            instrument_store=None,
        )

    def test_wire_marks_bus_and_skips_hook_helpers(self):
        book = MagicMock()
        book.has_pending = MagicMock(return_value=True)
        book.maybe_arm_from_main_sl = MagicMock(return_value=True)
        book.on_position_opened = MagicMock()
        book.cancel_for_structure = MagicMock()
        book.tick = MagicMock(return_value=0)
        book._watches = {}

        engine = self._engine_with_book(book)
        bus = EventBus(engine_id="test_reentry_xor")
        wire_event_bus(engine, bus)

        self.assertTrue(reentry_driven_by_bus(engine))
        assert_reentry_path_xor(bus_wired=True, hooks_drive=False)

        from core.events.handlers.reentry_at_cost import (
            arm_from_main_sl,
            cancel_for_structure,
            stop_on_main_opened,
            tick_book,
        )

        inst = SimpleNamespace(trading_symbol="P-BTC-1")
        # Hook-style calls (via_bus=False) must no-op when bus owns the path.
        self.assertFalse(
            arm_from_main_sl(
                engine,
                strategy=self._opt_in_strategy(),
                instrument=inst,
                structure_id="sid-hook",
                qty=1,
                side="SELL",
                price=10,
            )
        )
        book.maybe_arm_from_main_sl.assert_not_called()
        stop_on_main_opened(engine, strategy_id="ElevenPM", instrument=inst)
        book.on_position_opened.assert_not_called()
        cancel_for_structure(engine, "sid-hook")
        book.cancel_for_structure.assert_not_called()
        self.assertEqual(tick_book(engine), 0)
        book.tick.assert_not_called()

        # Bus IntentFilled / QuoteUpdated drive the book.
        bus.publish(
            make_event(
                EventType.INTENT_FILLED,
                {
                    "tag": "MAIN_SL",
                    "strategy": "ElevenPM",
                    "structure_id": "sid-bus",
                    "instrument": inst,
                    "metadata_extras": {
                        "entry_premium": 50,
                        "reentry_at_cost": {"enabled": True},
                    },
                    "qty": 1,
                    "side": "BUY",
                    "price": 55,
                },
                engine_id="test_reentry_xor",
            )
        )
        book.maybe_arm_from_main_sl.assert_called_once()

        bus.publish(
            make_event(
                EventType.QUOTE_UPDATED,
                {"source": "reentry_maintenance", "symbol": ""},
                engine_id="test_reentry_xor",
            )
        )
        book.tick.assert_called_once()

    def test_hooks_drive_when_bus_not_wired(self):
        book = MagicMock()
        book._watches = {}
        book.maybe_arm_from_main_sl = MagicMock(return_value=True)
        book.tick = MagicMock(return_value=1)
        book.has_pending = MagicMock(return_value=True)

        engine = self._engine_with_book(book)
        mark_reentry_bus_wired(engine, False)
        self.assertFalse(reentry_driven_by_bus(engine))
        assert_reentry_path_xor(bus_wired=False, hooks_drive=True)

        from core.events.handlers.reentry_at_cost import arm_from_main_sl, tick_book

        ok = arm_from_main_sl(
            engine,
            strategy=self._opt_in_strategy(),
            instrument=SimpleNamespace(trading_symbol="P-BTC-1"),
            structure_id="sid-hook-only",
            qty=1,
            side="SELL",
            price=10,
        )
        self.assertTrue(ok)
        book.maybe_arm_from_main_sl.assert_called_once()
        self.assertEqual(tick_book(engine), 1)
        book.tick.assert_called_once()


if __name__ == "__main__":
    unittest.main()
