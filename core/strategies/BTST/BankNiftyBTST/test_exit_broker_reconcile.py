"""BankNiftyBTST: reconcile once before MAIN_EXIT; skip if broker flat."""

from __future__ import annotations

import unittest
from datetime import date, datetime, time
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from run.config import RunMode
from core.strategies.BTST.BankNiftyBTST import BankNiftyBTST as mod
from core.strategies.BTST.BankNiftyBTST.BankNiftyBTST import (
    EXIT_TIME,
    BankNiftyBTST,
    _BtstLegMeta,
)

IST = ZoneInfo("Asia/Kolkata")


class TestBtstExitBrokerReconcile(unittest.TestCase):
    def setUp(self):
        self._prev_mode = mod.RUN_MODE
        mod.RUN_MODE = RunMode.LIVE
        self.strat = BankNiftyBTST()
        self.strat._meta_by_structure_id["BankNiftyBTST:BANKNIFTY:2026-07-23:PE"] = (
            _BtstLegMeta(
                symbol="BANKNIFTY",
                entry_date=date(2026, 7, 23),
                option_type="PE",
                ref_premium=100.0,
                limit_price=150.0,
            )
        )

    def tearDown(self):
        mod.RUN_MODE = self._prev_mode

    def _candle(self):
        return {
            "symbol": "BANKNIFTY",
            "timestamp": datetime(2026, 7, 24, 3, 55, tzinfo=IST),  # ~09:25 IST UTC-naive path
            "scheduled_slot": EXIT_TIME,
        }

    def _position(self, *, qty=30):
        inst = SimpleNamespace(
            trading_symbol="BANKNIFTY-Jul2026-56300-PE",
            custom_symbol="BANKNIFTY-Jul2026-56300-PE",
            strike=56300,
            option_type="PE",
            expiry=date(2026, 7, 28),
            place_order_symbol=lambda: "BANKNIFTY 28 JUL 56300 PUT",
        )
        return SimpleNamespace(
            instrument=inst,
            net_qty=qty,
            avg_price=148.5,
            strategy="BankNiftyBTST",
            tag="MAIN",
            structure_id="BankNiftyBTST:BANKNIFTY:2026-07-23:PE",
            intent_id="x",
        )

    def test_skips_exit_when_broker_flat_after_reconcile(self):
        pos = self._position()
        pm = MagicMock()
        pm.get_open_positions.side_effect = lambda strategy=None: [pos]
        broker = MagicMock()
        broker.get_positions_for_recon.return_value = {}
        ctx = SimpleNamespace(
            position_store=pm,
            order_router=SimpleNamespace(broker=broker),
            intent_store=None,
            instrument_store=None,
        )
        candle = self._candle()
        intents = self.strat._build_overnight_exit_intents(candle, ctx)
        self.assertEqual(intents, [])
        broker.get_positions_for_recon.assert_called_once()
        pm.reconcile_with_broker.assert_called_once()

    def test_places_exit_when_broker_still_open(self):
        pos = self._position()
        pm = MagicMock()
        pm.get_open_positions.side_effect = lambda strategy=None: [pos]
        broker = MagicMock()
        broker.get_positions_for_recon.return_value = {
            "BANKNIFTY 28 JUL 56300 PUT": {"qty": 30, "avg_price": 148.5}
        }
        ctx = SimpleNamespace(
            position_store=pm,
            order_router=SimpleNamespace(broker=broker),
            intent_store=None,
            instrument_store=None,
        )
        candle = self._candle()
        # Avoid option-chain pricing in on_position_exit under LIVE (price=None).
        intents = self.strat._build_overnight_exit_intents(candle, ctx)
        self.assertEqual(len(intents), 1)
        self.assertEqual(getattr(intents[0], "tag", None) or intents[0].get("tag"), "MAIN_EXIT")
        broker.get_positions_for_recon.assert_called_once()

    def test_reconcile_cached_once_per_slot(self):
        candle = self._candle()
        broker = MagicMock()
        broker.get_positions_for_recon.return_value = {"X": {"qty": 1}}
        pm = MagicMock()
        ctx = SimpleNamespace(
            position_store=pm,
            order_router=SimpleNamespace(broker=broker),
        )
        a = self.strat._reconcile_broker_positions_for_exit(candle, ctx)
        b = self.strat._reconcile_broker_positions_for_exit(candle, ctx)
        self.assertIs(a, b)
        broker.get_positions_for_recon.assert_called_once()


if __name__ == "__main__":
    unittest.main()
