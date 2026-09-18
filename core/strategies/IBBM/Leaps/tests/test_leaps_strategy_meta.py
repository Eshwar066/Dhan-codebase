"""LEAPS ENTRY intents persist strategy_meta for open-positions CSV."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

from core.models.order_intent import OrderIntent
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
        inst = SimpleNamespace(
            trading_symbol="NIFTY-Dec2026-24000-CE",
            custom_symbol="NIFTY-24000-CE",
            strike=24000,
            option_type="CE",
            expiry=date(2026, 12, 29),
            lot_size=65,
        )
        sell = OrderIntent(
            intent_id="main",
            instrument=inst,
            side="SELL",
            qty=1,
            price=425.95,
            order_type="LIMIT",
            strategy=s.name,
            structure_id="LEAPS_RSI:NIFTY:RSI_LT_32:QTR",
            trade_type="MARGIN",
            tag="MAIN",
            symbol="NIFTY",
            action="ENTRY",
            candle_ts=datetime(2026, 9, 15, 13, 15),
        )
        hedge_inst = SimpleNamespace(
            trading_symbol="NIFTY-Oct2026-24500-CE",
            custom_symbol="NIFTY-24500-CE",
            strike=24500.0,
            expiry=date(2026, 10, 27),
            lot_size=65,
        )
        hedge = OrderIntent(
            intent_id="hedge",
            instrument=hedge_inst,
            side="BUY",
            qty=1,
            price=57.75,
            order_type="LIMIT",
            strategy=s.name,
            structure_id="LEAPS_RSI:NIFTY:RSI_LT_32:QTR",
            trade_type="MARGIN",
            tag="HEDGE",
            symbol="NIFTY",
            action="ENTRY",
            candle_ts=datetime(2026, 9, 15, 13, 15),
            parent_intent_id="main",
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
        self.assertIsNotNone(out)
        self.assertEqual(len(out), 2)
        hedge_out, sell_out = out[0], out[1]
        body = unpack_strategy_meta(sell_out.metadata_extras, "LEAPS_RSI")
        self.assertEqual(body["regime"], "RSI_LT_32")
        self.assertEqual(body["entry_main_premium"], 425.95)
        self.assertEqual(body["hedge_symbol"], "NIFTY-Oct2026-24500-CE")
        self.assertEqual(hedge_out.metadata_extras, sell_out.metadata_extras)

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

    def test_resolve_main_expiry_quarterly_ignores_chain_expiry(self):
        s = LeapsQuarterly()
        s._last_option_chain = {
            "expiry": date(2026, 9, 22),
            "chain": pd.DataFrame({"Strike Price": [23500], "PE LTP": [200.0]}),
        }
        candle = {"timestamp": pd.Timestamp("2026-09-18 14:15:00", tz=IST)}
        ctx = SimpleNamespace(get_expiry_list=lambda: [])
        resolved = s._resolve_main_expiry(candle, ctx, "QUARTERLY")
        self.assertEqual(resolved, date(2026, 12, 29))

    def test_build_entry_intents_skips_when_chain_expiry_mismatch(self):
        s = LeapsQuarterly()
        s._last_option_chain = {"expiry": date(2026, 9, 22)}
        ctx = SimpleNamespace(
            position_store=SimpleNamespace(
                has_open_main_leg=MagicMock(return_value=False)
            ),
            intent_store=SimpleNamespace(
                has_pending_intent=MagicMock(return_value=False),
                has_entry_for_structure=MagicMock(return_value=False),
            ),
            instrument_store=SimpleNamespace(),
            exchange="NSE",
            get_expiry_list=lambda: [],
        )
        candle = {
            "symbol": "NIFTY",
            "timestamp": pd.Timestamp("2026-09-18 14:15:00", tz=IST),
            "rsi": 55.0,
            "prev_rsi": 50.0,
        }
        with patch.object(
            s,
            "find_strike_in_premium_range",
            return_value=(23500.0, 223.85, {"ltp": 223.85}),
        ):
            out = s._build_entry_intents(
                candle,
                ctx,
                "PUT",
                structure_id="LEAPS_RSI:NIFTY:RSI_GT_52:QTR",
                expiry_pref="QUARTERLY",
                leg_label="quarterly",
            )
        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()
