"""Manual Dhan exit → clear ownership metadata + cancel resting local intents."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.engine.live_engine import LiveEngine
from core.orderExecution.intent_store import IntentStatus
from core.orderExecution.order_router import OrderRouter, OrderState
from core.orderExecution.position_manager import PositionManager
from core.utils.instruments.base import Instrument
from run.config import RunMode


class TestManualBrokerFlatSync(unittest.TestCase):
    def test_sync_symbol_flat_clears_metadata_when_requested(self):
        pm = PositionManager.__new__(PositionManager)
        pm._lock = __import__("threading").RLock()
        pm.positions = {}
        pm.position_metadata = {}
        pm.strategy_pos = __import__("collections").defaultdict(dict)
        pm._structure_slices = {}
        pm._trade_led_symbol_ts = {}
        pm._merge_position_metadata = MagicMock()

        inst = Instrument(
            trading_symbol="BANKNIFTY-Jul2026-55900-PE",
            custom_symbol="BANKNIFTY-Jul2026-55900-PE",
            exchange="NSE",
            segment="NFO",
            instrument_type="OP",
            lot_size=30,
        )
        from core.orderExecution.position_manager import Position

        pos = Position(inst)
        pos.net_qty = 30
        pos.strategy = "BankNiftyBTST"
        pos.structure_id = "BankNiftyBTST:BANKNIFTY:2026-07-23:PE"
        pos.tag = "MAIN"
        pos.intent_id = "x"
        pm.positions[inst.trading_symbol] = pos
        pm.position_metadata[inst.trading_symbol] = {
            "strategy": "BankNiftyBTST",
            "structure_id": pos.structure_id,
            "tag": "MAIN",
            "intent_id": "x",
        }
        pm.strategy_pos["BankNiftyBTST"][inst.trading_symbol] = 30

        ok = pm.sync_symbol_flat_at_broker(
            inst.trading_symbol,
            reason="confirmed_broker_flat",
            clear_metadata=True,
        )
        self.assertTrue(ok)
        self.assertNotIn(inst.trading_symbol, pm.positions)
        self.assertNotIn(inst.trading_symbol, pm.position_metadata)

    def test_router_cancels_resting_sl_on_manual_flat(self):
        router = OrderRouter.__new__(OrderRouter)
        router.broker = MagicMock()
        router.intent_store = MagicMock()
        router.engine_logger = MagicMock()
        router.gtt_fallback_book = SimpleNamespace(_watches={})
        router._order_state = {}
        router._order_state_log = []
        router._set_order_state = MagicMock()
        router.cancel_gtt_fallback_watch = MagicMock(return_value=True)
        router.on_broker_no_open_position = None

        sl_rec = {
            "intent_id": "sl-1",
            "status": IntentStatus.SENT,
            "tag": "MAIN_SL",
            "action": "FORCE_EXIT",
            "structure_id": "BankNiftyBTST:BANKNIFTY:2026-07-23:PE",
            "strategy": "BankNiftyBTST",
            "broker_order_id": "999",
            "instrument": SimpleNamespace(
                trading_symbol="BANKNIFTY-Jul2026-55900-PE",
                custom_symbol="BANKNIFTY-Jul2026-55900-PE",
                place_order_symbol=lambda: "BANKNIFTY 28 JUL 55900 PUT",
            ),
            "payload": {
                "tag": "MAIN_SL",
                "action": "FORCE_EXIT",
                "structure_id": "BankNiftyBTST:BANKNIFTY:2026-07-23:PE",
                "strategy_id": "BankNiftyBTST",
                "symbol": "BANKNIFTY-Jul2026-55900-PE",
            },
        }
        router.intent_store.list_by_status.side_effect = lambda st: (
            [sl_rec] if st == IntentStatus.SENT else []
        )

        n = router.sync_local_after_manual_broker_flat(
            trading_symbol="BANKNIFTY-Jul2026-55900-PE",
            structure_id="BankNiftyBTST:BANKNIFTY:2026-07-23:PE",
            strategy_id="BankNiftyBTST",
            reason="manual_broker_exit",
        )
        self.assertEqual(n, 1)
        router.broker.cancel_order_by_id.assert_called()
        router.intent_store.update.assert_called_with(
            "sl-1",
            IntentStatus.CANCELLED,
            order_state=OrderState.CANCELLED,
        )


class TestManualFlatSessionGate(unittest.TestCase):
    def _engine(self):
        eng = LiveEngine.__new__(LiveEngine)
        eng.run_mode = RunMode.LIVE
        eng.engine_logger = MagicMock()
        eng.order_router = MagicMock()
        eng.order_router.sync_local_after_manual_broker_flat = MagicMock(return_value=1)
        eng._strategy_obj_for_name = MagicMock(return_value=None)
        pm = PositionManager.__new__(PositionManager)
        pm._lock = __import__("threading").RLock()
        pm.positions = {}
        pm.position_metadata = {
            "BANKNIFTY-Jul2026-55900-PE": {
                "strategy": "BankNiftyBTST",
                "structure_id": "BankNiftyBTST:BANKNIFTY:2026-07-23:PE",
                "tag": "MAIN",
                "intent_id": "x",
            }
        }
        pm.strategy_pos = __import__("collections").defaultdict(dict)
        pm._structure_slices = {}
        pm.sync_symbol_flat_at_broker = MagicMock(return_value=True)
        pm.clear_ownership_metadata = MagicMock()
        pm.ownership_snapshot = MagicMock(
            return_value=pm.position_metadata["BANKNIFTY-Jul2026-55900-PE"]
        )
        eng.position_manager = pm
        return eng

    def test_outside_hours_empty_book_keeps_metadata(self):
        """Overnight empty/ambiguous book must NOT clear ownership."""
        eng = self._engine()
        with patch.object(
            LiveEngine, "_nse_session_open_for_manual_flat", return_value=False
        ):
            eng._apply_manual_flat_closes_after_reconcile({})
        eng.position_manager.sync_symbol_flat_at_broker.assert_not_called()
        eng.order_router.sync_local_after_manual_broker_flat.assert_not_called()

    def test_market_hours_empty_book_clears_and_cancels(self):
        """In-session empty book = confirmed flat → clear meta + cancel MAIN_SL."""
        eng = self._engine()
        with patch.object(
            LiveEngine, "_nse_session_open_for_manual_flat", return_value=True
        ):
            eng._apply_manual_flat_closes_after_reconcile({})
        eng.position_manager.sync_symbol_flat_at_broker.assert_called()
        self.assertTrue(
            eng.position_manager.sync_symbol_flat_at_broker.call_args.kwargs.get(
                "clear_metadata"
            )
        )
        eng.order_router.sync_local_after_manual_broker_flat.assert_called()

    def test_nonempty_book_missing_leg_clears_even_outside_hours(self):
        """Specific leg absent from a real book → confirmed gone (not ambiguous)."""
        eng = self._engine()
        with patch.object(
            LiveEngine, "_nse_session_open_for_manual_flat", return_value=False
        ):
            eng._apply_manual_flat_closes_after_reconcile(
                {"NIFTY-Jul2026-25000-CE": {"qty": 50, "avg_price": 100.0}}
            )
        eng.position_manager.sync_symbol_flat_at_broker.assert_called()
        eng.order_router.sync_local_after_manual_broker_flat.assert_called()


if __name__ == "__main__":
    unittest.main()
