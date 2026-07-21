"""Tests for no_open_position → broker flat sync (PM + MAIN_SL retry + reentry cancel)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.engine.live_engine import LiveEngine
from core.orderExecution.order_router import IntentStatus, OrderRouter, OrderState
from core.orderExecution.reentry_at_cost_book import ReentryAtCostBook


class _FakePos:
    def __init__(self, *, net_qty, structure_id="sid-1", strategy="TestStrat"):
        self.net_qty = net_qty
        self.structure_id = structure_id
        self.strategy = strategy
        self.tag = "MAIN"
        self.intent_id = "main-1"
        self.instrument = SimpleNamespace(trading_symbol="P-BTC-63200-210726")


class TestBrokerNoOpenPositionSync(unittest.TestCase):
    def _router(self):
        router = OrderRouter.__new__(OrderRouter)
        router.broker = MagicMock()
        router.intent_store = MagicMock()
        router.engine_logger = MagicMock()
        router.strategy_id = "TestStrat"
        router.engine_id = "test"
        router.risk = MagicMock()
        router.risk.allow_intent.return_value = True
        router.circuit_breaker_threshold = 5
        router._consecutive_failures = 0
        router._order_state = {}
        router._order_state_log = []
        router.slippage_model = lambda p: p
        router.on_broker_no_open_position = None
        router._set_order_state = MagicMock()
        router._log_oms_step = MagicMock()
        return router

    def test_delta_bracket_bundle_no_open_position_syncs(self):
        router = self._router()
        synced: dict = {}

        def _handler(**kwargs):
            synced.update(kwargs)

        router.on_broker_no_open_position = _handler
        sl = SimpleNamespace(
            intent_id="sl-1",
            tag="MAIN_SL",
            action="FORCE_EXIT",
            structure_id="BTCZero:PE",
            strategy_id="BTCZero",
            instrument=SimpleNamespace(trading_symbol="P-BTC-63200-210726"),
        )
        tgt = SimpleNamespace(
            intent_id="tgt-1",
            tag="MAIN_TARGET",
            action="FORCE_EXIT",
            structure_id="BTCZero:PE",
            strategy_id="BTCZero",
            instrument=SimpleNamespace(trading_symbol="P-BTC-63200-210726"),
        )
        router.broker.place_combined_bracket_orders.return_value = {
            "ok": False,
            "reason": "no_open_position",
            "message": "no_open_position for P-BTC-63200-210726",
        }
        bundle_item = {
            "intent_bundle": [sl, tgt],
            "price_map": {"P-BTC-63200-210726": 10.0},
            "strategy_id": "BTCZero",
        }
        with patch.object(router, "process_intent", return_value={"ok": True}):
            result = router._process_delta_bracket_bundle(bundle_item)

        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("reason"), "broker_flat_synced")
        router.engine_logger.log.assert_called()
        log_args = router.engine_logger.log.call_args
        self.assertEqual(log_args[0][0], "reconciliation")
        self.assertIn("BROKER_FLAT_SYNC", log_args[0][1])
        router.intent_store.update.assert_any_call(
            "sl-1", IntentStatus.CANCELLED, order_state=OrderState.CANCELLED
        )
        self.assertEqual(synced.get("trading_symbol"), "P-BTC-63200-210726")
        self.assertEqual(synced.get("structure_id"), "BTCZero:PE")

    def test_process_intent_no_open_position_on_main_sl(self):
        router = self._router()
        handler = MagicMock()
        router.on_broker_no_open_position = handler
        intent = SimpleNamespace(
            intent_id="sl-only",
            tag="MAIN_SL",
            action="FORCE_EXIT",
            structure_id="sid-x",
            strategy_id="Strat",
            side="BUY",
            qty=1,
            instrument=SimpleNamespace(
                trading_symbol="P-BTC-100-210726", lot_size=1
            ),
        )
        router.broker.place_order.return_value = None
        router.broker._last_place_order_failure = {
            "message": "no_open_position",
            "error_code": "no_open_position",
            "retryable": False,
        }
        router.intent_store.exists.return_value = True
        with patch.object(router, "_log_oms_step"), patch.object(
            router, "_set_order_state"
        ):
            result = router.process_intent(
                intent, {"P-BTC-100-210726": 5.0}, skip_margin_check=True
            )
        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("reason"), "broker_flat_synced")
        handler.assert_called_once()
        router.engine_logger.log.assert_called()
        self.assertEqual(router.engine_logger.log.call_args[0][0], "reconciliation")

    def test_live_engine_on_broker_no_open_position(self):
        eng = LiveEngine.__new__(LiveEngine)
        eng.engine_logger = MagicMock()
        eng._delta_main_sl_retry = {"sid-1": {"attempts": 2, "next_at": 0.0}}
        pos = _FakePos(net_qty=-1, structure_id="sid-1", strategy="BTCZero")
        pm = SimpleNamespace(
            positions={"P-BTC-63200-210726": pos},
            sync_symbol_flat_at_broker=MagicMock(return_value=True),
        )
        eng.position_manager = pm

        book = ReentryAtCostBook.__new__(ReentryAtCostBook)
        book._watches = {
            "sid-1": SimpleNamespace(
                watch_id="sid-1",
                strategy_id="BTCZero",
                trading_symbol="P-BTC-63200-210726",
            )
        }
        book._lock = __import__("threading").Lock()
        book._save = MagicMock()
        book._log = MagicMock()
        eng.order_router = SimpleNamespace(reentry_at_cost_book=book)

        eng._on_broker_no_open_position(
            trading_symbol="P-BTC-63200-210726",
            structure_id="sid-1",
            strategy_id="BTCZero",
            message="no_open_position",
        )

        pm.sync_symbol_flat_at_broker.assert_called_once_with(
            "P-BTC-63200-210726", reason="no_open_position"
        )
        self.assertNotIn("sid-1", eng._delta_main_sl_retry)
        self.assertNotIn("sid-1", book._watches)
        eng.engine_logger.log.assert_called()


if __name__ == "__main__":
    unittest.main()
