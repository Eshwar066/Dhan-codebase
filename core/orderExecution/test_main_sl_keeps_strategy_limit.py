"""MAIN_SL limit must not be overwritten by live ask in price_map."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.orderExecution.order_router import OrderRouter


class TestMainSlKeepsStrategyLimit(unittest.TestCase):
    def _router(self):
        router = OrderRouter.__new__(OrderRouter)
        router.broker = MagicMock()
        router.intent_store = MagicMock()
        router.engine_logger = MagicMock()
        router.strategy_id = "DirectionalOptionSelling"
        router.engine_id = "test"
        router.risk = MagicMock()
        router.risk.allow_intent.return_value = True
        router.circuit_breaker_threshold = 5
        router._consecutive_failures = 0
        router._order_state = {}
        router._order_state_log = []
        router.slippage_model = lambda p: p
        router.execution_validator = None
        router.bracket_registry = MagicMock()
        router.on_invalid_stop = None
        router.on_broker_no_open_position = None
        return router

    def test_resolve_prefers_intent_price_for_main_sl(self):
        router = self._router()
        intent = SimpleNamespace(
            tag="MAIN_SL",
            order_type="SL",
            price=41.4,
            instrument=SimpleNamespace(trading_symbol="P-BTC-63000-020826"),
        )
        px = router._resolve_exec_price(
            intent, {"P-BTC-63000-020826": 20.3}, "P-BTC-63000-020826"
        )
        self.assertEqual(px, 41.4)

    def test_resolve_uses_price_map_for_entry(self):
        router = self._router()
        intent = SimpleNamespace(
            tag="MAIN",
            order_type="LIMIT",
            price=41.4,
            instrument=SimpleNamespace(trading_symbol="P-BTC-63000-020826"),
        )
        px = router._resolve_exec_price(
            intent, {"P-BTC-63000-020826": 20.3}, "P-BTC-63000-020826"
        )
        self.assertEqual(px, 20.3)

    def test_process_intent_places_main_sl_at_strategy_limit(self):
        router = self._router()
        intent = SimpleNamespace(
            intent_id="sl-limit-keep",
            tag="MAIN_SL",
            action="FORCE_EXIT",
            order_type="SL",
            price=41.4,
            trigger_price=40.4,
            structure_id="sid",
            strategy_id="DirectionalOptionSelling",
            side="BUY",
            qty=50,
            candle_ts=None,
            parent_intent_id=None,
            metadata_extras={"stop_trigger_method": "mark_price"},
            instrument=SimpleNamespace(
                trading_symbol="P-BTC-63000-020826", lot_size=1
            ),
            trade_type="MARGIN",
            symbol="BTCUSD",
        )
        router.broker.place_order.return_value = "1448134881"
        router.intent_store.exists.return_value = True
        router.intent_store.get.return_value = {
            "intent_id": intent.intent_id,
            "payload": {},
        }
        with patch.object(router, "_log_oms_step"), patch.object(
            router, "_set_order_state"
        ), patch.object(router, "_validate_intent_execution", return_value=None):
            result = router.process_intent(
                intent,
                {"P-BTC-63000-020826": 20.3},
                skip_margin_check=True,
            )
        self.assertTrue(result.get("ok"))
        router.broker.place_order.assert_called_once()
        _args, kwargs = router.broker.place_order.call_args
        self.assertEqual(kwargs.get("execution_price"), 41.4)


if __name__ == "__main__":
    unittest.main()
