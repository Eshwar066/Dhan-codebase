"""REST process_trade must emit IntentFilled so bus-wired reentry can arm."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.events.types import EventType
from core.orderExecution.order_router import OrderRouter


class TestProcessTradeEmitsBusFill(unittest.TestCase):
    def test_process_trade_emits_intent_filled_for_main_sl(self):
        bus = MagicMock()
        intent_id = "sl-intent-1"
        trade_id = "trade-1"
        inst = SimpleNamespace(
            trading_symbol="P-BTC-64400-220726",
            strike=64400,
            expiry="220726",
            option_type="PE",
        )
        intent = {
            "intent_id": intent_id,
            "strategy": "BTCZeroDTEElevenPM",
            "structure_id": "BTCZeroDTEElevenPM:BTCUSD:2026-07-21:PE",
            "tag": "MAIN_SL",
            "action": "FORCE_EXIT",
            "instrument": inst,
            "payload": {
                "strategy_id": "BTCZeroDTEElevenPM",
                "structure_id": "BTCZeroDTEElevenPM:BTCUSD:2026-07-21:PE",
                "tag": "MAIN_SL",
                "action": "FORCE_EXIT",
                "strategy_meta": {
                    "entry_premium": 9.0,
                    "qty_lots": 10,
                    "reentry_at_cost": {"enabled": True, "max_reentries": 2},
                },
            },
        }
        store = MagicMock()
        store.get = MagicMock(return_value=intent)
        store.update = MagicMock()

        pm = MagicMock()
        pm.on_fill = MagicMock(return_value=(True, -1.1))
        pm.position_metadata = {}
        pm.note_trade_led_fill = MagicMock()

        router = OrderRouter.__new__(OrderRouter)
        router.event_bus = bus
        router.engine_id = "delta_engine_one"
        router.intent_store = store
        router.position_manager = pm
        router.risk = SimpleNamespace(record_realized_pnl=MagicMock())
        router.engine_logger = None
        router.gtt_fallback_book = None
        router._processed_trade_ids = set()
        router._processed_trade_ids_max = 10000
        router._order_state = {}
        router._set_order_state = MagicMock()
        router.report_fill = MagicMock()
        router._maybe_cancel_bracket_sibling_after_exit = MagicMock()
        router._instrument_trading_symbol = lambda i: getattr(i, "trading_symbol", None)
        router._terminal_fill_reflected_in_pm = MagicMock(return_value=False)

        trade = {
            "trade_id": trade_id,
            "intent_id": intent_id,
            "instrument": inst,
            "side": "BUY",
            "size": 10,
            "price": 10.1,
            "order_id": "1429204189",
            "execution_source": "REST_FILLS",
            "tag": "MAIN_SL",
            "action": "FORCE_EXIT",
            "strategy": "BTCZeroDTEElevenPM",
            "structure_id": "BTCZeroDTEElevenPM:BTCUSD:2026-07-21:PE",
        }

        ok = OrderRouter.process_trade(router, trade)
        self.assertTrue(ok)
        self.assertTrue(bus.publish.called)
        events = [c.args[0] for c in bus.publish.call_args_list]
        filled = [e for e in events if e.type == EventType.INTENT_FILLED]
        self.assertEqual(len(filled), 1)
        payload = filled[0].payload
        self.assertEqual(payload.get("tag"), "MAIN_SL")
        self.assertTrue(payload.get("position_closed"))
        self.assertEqual(
            (payload.get("metadata_extras") or {}).get("entry_premium"), 9.0
        )


if __name__ == "__main__":
    unittest.main()
