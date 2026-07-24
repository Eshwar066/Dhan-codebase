"""Overnight reconcile: empty book + compact/space Dhan symbol identity."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.orderExecution.order_router import OrderRouter
from core.orderExecution.position_manager import PositionManager
from core.utils.expiry_resolver import ExpiryResolver
from core.utils.instruments.base import Instrument


class TestOvernightReconcileSymbolMap(unittest.TestCase):
    def test_option_identity_matches_compact_and_space(self):
        a = ExpiryResolver.option_identity_key("BANKNIFTY-Jul2026-56300-PE")
        b = ExpiryResolver.option_identity_key("BANKNIFTY 28 JUL 56300 PUT")
        self.assertEqual(a, "BANKNIFTY|56300|PE")
        self.assertEqual(a, b)

    def test_empty_broker_book_zeros_local_qty_keeps_metadata(self):
        pm = PositionManager.__new__(PositionManager)
        pm._lock = __import__("threading").RLock()
        pm.open_positions_csv_path = None
        pm.position_metadata = {
            "BANKNIFTY-Jul2026-56300-PE": {
                "strategy": "BankNiftyBTST",
                "structure_id": "BankNiftyBTST:BANKNIFTY:2026-07-22:PE",
                "tag": "MAIN",
                "intent_id": "x",
            }
        }
        from core.orderExecution.position_manager import Position

        inst = Instrument(
            trading_symbol="BANKNIFTY-Jul2026-56300-PE",
            custom_symbol="BANKNIFTY-Jul2026-56300-PE",
            exchange="NSE",
            segment="NFO",
            instrument_type="OP",
            lot_size=30,
        )
        real = Position(inst)
        real.net_qty = 30
        real.avg_price = 148.5
        real.strategy = "BankNiftyBTST"
        real.tag = "MAIN"
        real.structure_id = "BankNiftyBTST:BANKNIFTY:2026-07-22:PE"
        real.intent_id = "x"
        pm.positions = {"BANKNIFTY-Jul2026-56300-PE": real}
        pm.strategy_pos = {"BankNiftyBTST": {"BANKNIFTY-Jul2026-56300-PE": 30}}
        pm._trade_led_symbol_ts = {}
        pm._merge_position_metadata = MagicMock()
        pm.merge_ownership_from_all_strategy_open_positions_csvs = MagicMock()

        pm.reconcile_with_broker({})
        self.assertNotIn("BANKNIFTY-Jul2026-56300-PE", pm.positions)
        pm._merge_position_metadata.assert_called()

    def test_space_broker_key_maps_onto_compact_local(self):
        pm = PositionManager.__new__(PositionManager)
        pm._lock = __import__("threading").RLock()
        pm.open_positions_csv_path = None
        pm.position_metadata = {
            "BANKNIFTY-Jul2026-56300-PE": {
                "strategy": "BankNiftyBTST",
                "structure_id": "BankNiftyBTST:BANKNIFTY:2026-07-22:PE",
                "tag": "MAIN",
                "intent_id": "x",
            }
        }
        from core.orderExecution.position_manager import Position

        inst = Instrument(
            trading_symbol="BANKNIFTY-Jul2026-56300-PE",
            custom_symbol="BANKNIFTY-Jul2026-56300-PE",
            exchange="NSE",
            segment="NFO",
            instrument_type="OP",
            lot_size=30,
        )
        real = Position(inst)
        real.net_qty = 30
        real.avg_price = 148.5
        real.strategy = "BankNiftyBTST"
        real.tag = "MAIN"
        real.structure_id = "BankNiftyBTST:BANKNIFTY:2026-07-22:PE"
        real.intent_id = "x"
        pm.positions = {"BANKNIFTY-Jul2026-56300-PE": real}
        pm.strategy_pos = {"BankNiftyBTST": {"BANKNIFTY-Jul2026-56300-PE": 30}}
        pm._trade_led_symbol_ts = {}
        pm._merge_position_metadata = MagicMock()
        pm.merge_ownership_from_all_strategy_open_positions_csvs = MagicMock()

        pm.reconcile_with_broker(
            {
                "BANKNIFTY 28 JUL 56300 PUT": {
                    "qty": 30,
                    "avg_price": 148.5,
                    "lot_size": 30,
                    "segment": "NFO",
                }
            }
        )
        self.assertIn("BANKNIFTY-Jul2026-56300-PE", pm.positions)
        self.assertEqual(pm.positions["BANKNIFTY-Jul2026-56300-PE"].net_qty, 30)
        self.assertNotIn("BANKNIFTY 28 JUL 56300 PUT", pm.positions)

    def test_adopt_matches_compact_intent_to_space_broker_via_identity(self):
        router = OrderRouter.__new__(OrderRouter)
        router.intent_store = MagicMock()
        router.broker = MagicMock()
        router.position_manager = MagicMock()
        router.engine_logger = None
        router._order_state = {}
        router._order_state_log = []
        # Intent without place_order_symbol alias — identity must still match.
        inst = SimpleNamespace(
            trading_symbol="BANKNIFTY-Jul2026-56300-PE",
            custom_symbol="BANKNIFTY-Jul2026-56300-PE",
            lot_size=30,
        )
        rec = {
            "intent_id": "gtt-1",
            "status": "SENT",
            "side": "BUY",
            "broker_order_id": "341",
            "instrument": inst,
            "payload": {
                "action": "ENTRY",
                "side": "BUY",
                "symbol": "BANKNIFTY-Jul2026-56300-PE",
                "price": 148.5,
                "lot_size": 30,
                "execution_mode": "HYBRID_GTT",
            },
            "price": 148.5,
        }
        applied = []

        def _apply(intent_rec, *, price, qty_lots, order_id):
            applied.append(
                {
                    "price": price,
                    "qty_lots": qty_lots,
                    "order_id": order_id,
                }
            )
            return True

        router._apply_gtt_fill_from_intent = _apply  # type: ignore[method-assign]
        router._intent_is_gtt = lambda _r: True  # type: ignore[method-assign]
        router.cancel_gtt_fallback_watch = MagicMock(return_value=True)

        ok = router.adopt_gtt_intent_from_broker_positions(
            rec,
            {
                "BANKNIFTY 28 JUL 56300 PUT": {
                    "qty": 30,
                    "avg_price": 147.0,
                    "lot_size": 30,
                }
            },
        )
        self.assertTrue(ok)
        self.assertEqual(applied[0]["qty_lots"], 1)
        self.assertEqual(applied[0]["price"], 147.0)


if __name__ == "__main__":
    unittest.main()
