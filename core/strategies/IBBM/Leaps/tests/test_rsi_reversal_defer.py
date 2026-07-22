"""LEAPS RSI flip must defer reverse ENTRY until MAIN_EXIT fill."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.strategies.IBBM.Leaps.LeapsQuatery_RSI_52_32 import LeapsQuarterly


class LeapsRsiReversalDeferTests(unittest.TestCase):
    def test_on_candle_defers_call_when_put_main_still_open(self):
        s = LeapsQuarterly()
        s.mini_leaps_enabled = True
        s.quarterly_leaps_enabled = False

        put_inst = SimpleNamespace(option_type="PE", trading_symbol="NIFTY-PUT")
        put_pos = SimpleNamespace(
            tag="MAIN",
            net_qty=-65,
            structure_id="LEAPS_RSI:NIFTY:RSI_GT_52",
            instrument=put_inst,
        )
        store = SimpleNamespace(
            has_open_main_leg=MagicMock(return_value=True),
            get_open_positions=MagicMock(return_value=[put_pos]),
        )
        ctx = SimpleNamespace(position_store=store)
        candle = {
            "symbol": "NIFTY",
            "timestamp": "2026-07-22 12:15:00+05:30",
            "rsi": 31.8,
            "prev_rsi": 33.0,
            "close": 25000,
        }
        marker = object()
        with patch.object(
            s, "_build_entry_intents", return_value=[marker]
        ) as build:
            out = s.on_candle(candle, ctx)
        self.assertIsNone(out)
        self.assertIsNotNone(s._pending_rsi_reversal)
        self.assertEqual(s._pending_rsi_reversal.option_type, "CALL")
        self.assertEqual(s._pending_rsi_reversal.regime, "RSI_LT_32")
        build.assert_called()
        self.assertTrue(build.call_args.kwargs.get("ignore_open_main"))

    def test_on_main_exit_filled_emits_deferred_intents(self):
        s = LeapsQuarterly()
        candle = {"symbol": "NIFTY", "timestamp": "t"}
        intent = SimpleNamespace(tag="MAIN")
        s._pending_rsi_reversal = SimpleNamespace(
            option_type="CALL",
            regime="RSI_LT_32",
            candle=candle,
            intents=[intent],
            exit_structure_id="LEAPS_RSI:NIFTY:RSI_GT_52",
        )
        pairs = s.on_main_exit_filled(
            tag="MAIN_EXIT",
            structure_id="LEAPS_RSI:NIFTY:RSI_GT_52",
        )
        self.assertEqual(len(pairs), 1)
        self.assertIs(pairs[0][0], intent)
        self.assertIsNone(s._pending_rsi_reversal)


if __name__ == "__main__":
    unittest.main()
