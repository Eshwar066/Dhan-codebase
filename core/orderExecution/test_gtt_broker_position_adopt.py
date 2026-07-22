"""Regression: GTT Forever fill lags status; broker position must adopt + arm SL path."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from core.orderExecution.gtt_fallback_book import (
    BidAskLtp,
    GttFallbackBook,
    GttFallbackPhase,
    GttFallbackWatch,
)
from core.orderExecution.intent_store import IntentStatus
from core.orderExecution.order_router import OrderRouter, OrderState

IST = ZoneInfo("Asia/Kolkata")


class TestGttBrokerPositionAdopt(unittest.TestCase):
    def _intent_rec(self, *, intent_id="gtt-1", engine_sym="BANKNIFTY-Jul2026-56300-PE"):
        inst = SimpleNamespace(
            trading_symbol=engine_sym,
            custom_symbol=engine_sym,
            lot_size=30,
            place_order_symbol=lambda: "BANKNIFTY 28 JUL 56300 PUT",
        )
        return {
            "intent_id": intent_id,
            "status": IntentStatus.SENT,
            "side": "BUY",
            "broker_order_id": "341",
            "instrument": inst,
            "payload": {
                "action": "ENTRY",
                "side": "BUY",
                "symbol": engine_sym,
                "price": 148.5,
                "lot_size": 30,
                "execution_mode": "HYBRID_GTT",
                "structure_id": "BankNiftyBTST:BANKNIFTY:2026-07-22:PE",
                "strategy_id": "BankNiftyBTST",
                "tag": "MAIN",
            },
            "price": 148.5,
            "tag": "MAIN",
            "structure_id": "BankNiftyBTST:BANKNIFTY:2026-07-22:PE",
        }

    def test_alnum_match_adopts_dhan_place_order_symbol(self):
        router = OrderRouter.__new__(OrderRouter)
        router.intent_store = MagicMock()
        router.broker = MagicMock()
        router.position_manager = MagicMock()
        router.engine_logger = None
        router._order_state = {}
        router._order_state_log = []
        rec = self._intent_rec()
        router.intent_store.list_by_status.side_effect = lambda st: (
            [rec] if st == IntentStatus.SENT else []
        )
        applied = []

        def _apply(intent_rec, *, price, qty_lots, order_id):
            applied.append(
                {
                    "intent_id": intent_rec["intent_id"],
                    "price": price,
                    "qty_lots": qty_lots,
                    "order_id": order_id,
                }
            )
            return True

        router._apply_gtt_fill_from_intent = _apply  # type: ignore[method-assign]
        broker_positions = {
            "BANKNIFTY 28 JUL 56300 PUT": {
                "qty": 30,
                "avg_price": 147.25,
                "lot_size": 30,
            }
        }
        n = router.adopt_pending_entries_from_broker_positions(broker_positions)
        self.assertEqual(n, 1)
        self.assertEqual(applied[0]["qty_lots"], 1)
        self.assertEqual(applied[0]["price"], 147.25)

    def test_position_detected_adopts_fill_not_just_skip_limit(self):
        router = MagicMock()
        store = MagicMock()
        rec = self._intent_rec()
        store.get.return_value = rec
        router.intent_store = store
        router._try_sync_gtt_intent_fill.return_value = False
        router.adopt_gtt_intent_from_broker_positions.return_value = True
        router.broker.get_positions_for_recon.return_value = {
            "BANKNIFTY 28 JUL 56300 PUT": {"qty": 30, "avg_price": 147.0, "lot_size": 30}
        }
        router.cancel_gtt_fallback_watch.return_value = True

        book = GttFallbackBook(router, engine_logger=None)
        watch = GttFallbackWatch(
            gtt_intent_id="gtt-1",
            strategy_id="BankNiftyBTST",
            structure_id="BankNiftyBTST:BANKNIFTY:2026-07-22:PE",
            trading_symbol="BANKNIFTY 28 JUL 56300 PUT",
            side="BUY",
            limit_price=148.5,
            entry_date=date(2026, 7, 22),
            trigger_field="ltp",
            trigger_op="<=",
            confirm_ticks=1,
            instrument=rec["instrument"],
            phase=GttFallbackPhase.GTT,
        )
        book._watches[watch.gtt_intent_id] = watch

        quote = BidAskLtp(bid=146.0, ask=147.0, ltp=146.5)
        now = datetime(2026, 7, 22, 12, 1, tzinfo=IST)
        book._tick_watch(watch, now, quote_override=quote, check_quotes=True)

        router.adopt_gtt_intent_from_broker_positions.assert_called()
        self.assertEqual(watch.phase, GttFallbackPhase.FILLED)
        router.place_gtt_fallback_order.assert_not_called()

    def test_cutoff_cancel_adopts_before_cancelling_gtt(self):
        router = OrderRouter.__new__(OrderRouter)
        router.intent_store = MagicMock()
        router.broker = MagicMock()
        router.engine_logger = None
        router._order_state = {}
        router._order_state_log = []
        rec = self._intent_rec()
        router.intent_store.list_by_status.side_effect = lambda st: (
            [rec] if st == IntentStatus.SENT else []
        )
        router._try_sync_gtt_intent_fill = MagicMock(return_value=False)  # type: ignore
        router.adopt_gtt_intent_from_broker_positions = MagicMock(return_value=True)  # type: ignore
        router.broker.cancel_order_by_id = MagicMock()

        n = router.cancel_unfilled_strategy_orders(
            "BankNiftyBTST",
            tags=["MAIN"],
            actions=["ENTRY"],
            trade_date=date(2026, 7, 22),
        )
        self.assertEqual(n, 0)
        router.adopt_gtt_intent_from_broker_positions.assert_called_once()
        router.broker.cancel_order_by_id.assert_not_called()
        self.assertNotIn("gtt-1", router._order_state)


if __name__ == "__main__":
    unittest.main()
