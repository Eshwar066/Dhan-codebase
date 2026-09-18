"""LEAPS ENTRY intents persist strategy_meta for open-positions CSV."""

from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

from core.strategies.IBBM.Leaps.LeapsQuatery_RSI_52_32 import LeapsQuarterly
from core.strategies.IndiaMktMixins import IST
from core.strategies.meta import unpack_strategy_meta


class LeapsStrategyMetaTests(unittest.TestCase):
    def test_entry_strategy_meta_payload(self):
        s = LeapsQuarterly()
        hedge = SimpleNamespace(
            price=57.75,
            instrument=SimpleNamespace(
                trading_symbol="NIFTY-Oct2026-24500-CE",
                strike=24500.0,
                expiry=date(2026, 10, 27),
            ),
        )
        extras = s._entry_strategy_meta(
            {"symbol": "NIFTY", "rsi": 29.88, "prev_rsi": 33.83},
            structure_id="LEAPS_RSI:NIFTY:RSI_LT_32:QTR",
            option_type="CALL",
            expiry_pref="QUARTERLY",
            leg_label="quarterly",
            main_symbol="NIFTY-Dec2026-24000-CE",
            main_strike=24000,
            main_expiry=date(2026, 12, 29),
            main_premium=425.95,
            hedge_intent=hedge,
        )
        body = unpack_strategy_meta(extras, "LEAPS_RSI")
        self.assertIsNotNone(body)
        self.assertEqual(body["strategy"], "LEAPS_RSI")
        self.assertEqual(body["regime"], "RSI_LT_32")
        self.assertEqual(body["main_symbol"], "NIFTY-Dec2026-24000-CE")
        self.assertEqual(body["entry_main_premium"], 425.95)
        self.assertEqual(body["hedge_symbol"], "NIFTY-Oct2026-24500-CE")
        self.assertEqual(body["entry_hedge_premium"], 57.75)
        self.assertEqual(body["main_expiry"], "2026-12-29")

    def test_build_entry_intents_attaches_metadata_extras(self):
        s = LeapsQuarterly()
        sell = SimpleNamespace(
            metadata_extras=None,
            instrument=SimpleNamespace(
                strike=24000, option_type="CE", expiry=date(2026, 12, 29)
            ),
            structure_id="LEAPS_RSI:NIFTY:RSI_LT_32:QTR",
            intent_id="main",
        )
        hedge = SimpleNamespace(
            metadata_extras=None,
            price=57.75,
            instrument=SimpleNamespace(
                trading_symbol="NIFTY-Oct2026-24500-CE",
                strike=24500.0,
                expiry=date(2026, 10, 27),
            ),
        )
        ctx = SimpleNamespace(
            position_store=SimpleNamespace(
                has_open_main_leg=MagicMock(return_value=False)
            ),
            intent_store=SimpleNamespace(
                has_pending_intent=MagicMock(return_value=False),
                has_entry_for_structure=MagicMock(return_value=False),
            ),
            instrument_store=SimpleNamespace(
                intent_creation_details=MagicMock(return_value=object())
            ),
            exchange="NSE",
        )
        candle = {
            "symbol": "NIFTY",
            "timestamp": "2026-09-15 13:15:00+05:30",
            "rsi": 29.88,
            "prev_rsi": 33.83,
        }
        with patch.object(
            s,
            "find_strike_in_premium_range",
            return_value=(24000.0, 425.95, {"ltp": 425.95}),
        ), patch.object(
            s, "_resolve_main_expiry", return_value=date(2026, 12, 29)
        ), patch.object(
            s, "map_instrument_to_intent", return_value=sell
        ), patch.object(
            s, "create_hedge_intent", return_value=hedge
        ):
            out = s._build_entry_intents(
                candle,
                ctx,
                "CALL",
                structure_id="LEAPS_RSI:NIFTY:RSI_LT_32:QTR",
                expiry_pref="QUARTERLY",
                leg_label="quarterly",
            )
        self.assertEqual(out, [hedge, sell])
        body = unpack_strategy_meta(sell.metadata_extras, "LEAPS_RSI")
        self.assertEqual(body["regime"], "RSI_LT_32")
        self.assertEqual(body["entry_main_premium"], 425.95)
        self.assertEqual(body["hedge_symbol"], "NIFTY-Oct2026-24500-CE")
        self.assertEqual(hedge.metadata_extras, sell.metadata_extras)

    def test_should_roll_hedge_skips_when_hedge_is_next_month(self):
        s = LeapsQuarterly()
        hedge = SimpleNamespace(
            structure_id="LEAPS_RSI:NIFTY:RSI_LT_32:QTR",
            tag="HEDGE",
            net_qty=65,
            instrument=SimpleNamespace(expiry=date(2026, 10, 27)),
        )
        ts = pd.Timestamp("2026-09-18 10:15:00", tz=IST)
        self.assertFalse(s.should_roll_hedge(hedge, ts))

    def test_should_roll_hedge_allows_current_month_hedge(self):
        s = LeapsQuarterly()
        trade_date = date(2026, 9, 18)
        current_month_exp = s._hedge_current_month_expiry(trade_date)
        hedge = SimpleNamespace(
            structure_id="LEAPS_RSI:NIFTY:RSI_LT_32:QTR",
            tag="HEDGE",
            net_qty=65,
            instrument=SimpleNamespace(expiry=current_month_exp),
        )
        ts = pd.Timestamp("2026-09-18 10:15:00", tz=IST)
        self.assertTrue(s.should_roll_hedge(hedge, ts))


if __name__ == "__main__":
    unittest.main()
