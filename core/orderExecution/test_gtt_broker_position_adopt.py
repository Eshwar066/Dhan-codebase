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

    def test_restore_from_disk_rebuilds_intent_stub(self):
        import tempfile
        from pathlib import Path

        from core.orderExecution.intent_store import IntentStore

        router = OrderRouter.__new__(OrderRouter)
        router.intent_store = IntentStore()
        router.engine_id = "test_engine"
        router._order_state_engine_id = "test_engine"
        router._order_state = {}
        router._logs_root = Path(tempfile.mkdtemp())
        router._set_order_state = MagicMock()
        book = GttFallbackBook(router, engine_logger=None)
        watch = GttFallbackWatch(
            gtt_intent_id="f2bd-test",
            strategy_id="BankNiftyBTST",
            structure_id="BankNiftyBTST:BANKNIFTY:2026-07-24:CE",
            trading_symbol="BANKNIFTY 28 JUL 57200 CALL",
            side="BUY",
            limit_price=161.4,
            entry_date=date.today(),
            broker_order_id="34132607241157",
            metadata_extras={"execution_mode": "HYBRID_GTT"},
            symbol="BANKNIFTY-Jul2026-57200-CE",
            phase=GttFallbackPhase.GTT,
        )
        book._watches[watch.gtt_intent_id] = watch
        book._persist_watches()
        book._watches.clear()
        n = book.restore_from_disk()
        self.assertEqual(n, 1)
        self.assertIn("f2bd-test", book._watches)
        rec = router.intent_store.get("f2bd-test")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["status"], IntentStatus.SENT)
        self.assertEqual(
            str((rec.get("payload") or {}).get("execution_mode")), "HYBRID_GTT"
        )

    def test_rebind_attaches_metadata_without_shadow_sl_hook(self):
        """Regression 2026-07-24: rebind+ensure both armed MAIN_SL → duplicates."""
        from core.orderExecution.intent_store import IntentStore

        router = OrderRouter.__new__(OrderRouter)
        router.intent_store = IntentStore()
        router.engine_id = "test_engine"
        router._order_state_engine_id = "test_engine"
        router._order_state = {}
        router._logs_root = None
        router._set_order_state = MagicMock()
        router._adopt_main_entry_shadow_fill = MagicMock()

        pm = MagicMock()
        pm.positions = {}
        pm._lock = MagicMock()
        pm._lock.__enter__ = MagicMock(return_value=None)
        pm._lock.__exit__ = MagicMock(return_value=False)
        router.position_manager = pm

        book = GttFallbackBook(router, engine_logger=None)
        book._watches["pe-1"] = GttFallbackWatch(
            gtt_intent_id="pe-1",
            strategy_id="BankNiftyBTST",
            structure_id="BankNiftyBTST:BANKNIFTY:2026-07-24:PE",
            trading_symbol="BANKNIFTY 28 JUL 55500 PUT",
            side="BUY",
            limit_price=149.2,
            entry_date=date.today(),
            broker_order_id="341",
            metadata_extras={
                "execution_mode": "HYBRID_GTT",
                "banknifty_btst": {
                    "symbol": "BANKNIFTY",
                    "entry_date": date.today().isoformat(),
                    "option_type": "PE",
                    "ref_premium": 99.0,
                    "limit_price": 149.2,
                },
            },
            symbol="BANKNIFTY-Jul2026-55500-PE",
            phase=GttFallbackPhase.GTT,
        )
        n = book.rebind_filled_legs_for_brackets(
            {
                "BANKNIFTY-Jul2026-55500-PE": {
                    "qty": 30,
                    "avg_price": 149.2,
                    "lot_size": 30,
                }
            }
        )
        self.assertEqual(n, 1)
        router._adopt_main_entry_shadow_fill.assert_not_called()
        pm._merge_position_metadata.assert_called()


class TestForeverTriggeredNormalize(unittest.TestCase):
    def test_triggered_maps_to_filled(self):
        from core.broker.internal.dhan.broker import DhanBroker

        broker = DhanBroker.__new__(DhanBroker)
        norm = broker._normalize_forever_order_for_recon(
            {
                "orderId": "34132607241158",
                "tradingSymbol": "BANKNIFTY-Jul2026-55500-PE",
                "quantity": 30,
                "price": 149.2,
                "orderStatus": "TRIGGERED",
                "correlationId": "NR",
            }
        )
        self.assertEqual(norm["status"], "filled")
        self.assertEqual(norm["filled_size"], 30.0)


class TestGttFallbackHarden(unittest.TestCase):
    def _watch(self, **kwargs):
        defaults = dict(
            gtt_intent_id="gtt-ce",
            strategy_id="BankNiftyBTST",
            structure_id="BankNiftyBTST:BANKNIFTY:2026-07-24:CE",
            trading_symbol="BANKNIFTY 28 JUL 57200 CALL",
            side="BUY",
            limit_price=161.4,
            entry_date=date(2026, 7, 24),
            trigger_field="ltp",
            trigger_op=">=",
            confirm_ticks=1,
            max_fallback_price=170.0,
            phase=GttFallbackPhase.GTT,
            instrument=SimpleNamespace(
                trading_symbol="BANKNIFTY-Jul2026-57200-CE",
                custom_symbol="BANKNIFTY-Jul2026-57200-CE",
                lot_size=30,
                place_order_symbol=lambda: "BANKNIFTY 28 JUL 57200 CALL",
            ),
        )
        defaults.update(kwargs)
        return GttFallbackWatch(**defaults)

    def test_triggered_forever_skips_fallback_limit(self):
        router = MagicMock()
        store = MagicMock()
        rec = {
            "intent_id": "gtt-ce",
            "status": IntentStatus.SENT,
            "broker_order_id": "341",
            "payload": {"action": "ENTRY", "execution_mode": "HYBRID_GTT"},
        }
        store.get.return_value = rec
        router.intent_store = store
        router._try_sync_gtt_intent_fill.return_value = True
        router.adopt_gtt_intent_from_broker_positions.return_value = False
        router.broker.find_forever_order_by_client_id.return_value = {
            "status": "filled",  # normalized TRIGGERED
            "filled_size": 30,
            "size": 30,
            "order_id": "341",
        }
        router.broker.get_positions_for_recon.return_value = {}
        router.cancel_gtt_fallback_watch.return_value = True

        book = GttFallbackBook(router, engine_logger=None)
        watch = self._watch()
        book._watches[watch.gtt_intent_id] = watch
        quote = BidAskLtp(bid=188.0, ask=190.4, ltp=189.0)
        now = datetime(2026, 7, 24, 12, 28, tzinfo=IST)
        book._tick_watch(watch, now, quote_override=quote, check_quotes=True)

        router.place_gtt_fallback_order.assert_not_called()
        self.assertEqual(watch.phase, GttFallbackPhase.FILLED)

    def test_price_cap_skips_limit_above_170(self):
        router = MagicMock()
        store = MagicMock()
        rec = {
            "intent_id": "gtt-ce",
            "status": IntentStatus.SENT,
            "broker_order_id": "341",
            "payload": {"action": "ENTRY", "execution_mode": "HYBRID_GTT"},
        }
        store.get.return_value = rec
        store.has_pending_intent.return_value = False
        router.intent_store = store
        router._try_sync_gtt_intent_fill.return_value = False
        router.adopt_gtt_intent_from_broker_positions.return_value = False
        router.broker.find_forever_order_by_client_id.return_value = {
            "status": "pending",
            "filled_size": 0,
            "size": 30,
            "order_id": "341",
        }
        router.broker.get_positions_for_recon.return_value = {}
        router.cancel_gtt_fallback_watch.return_value = True
        router.broker.cancel_open_day_orders_for_symbol.return_value = 0

        book = GttFallbackBook(router, engine_logger=None)
        watch = self._watch()
        book._watches[watch.gtt_intent_id] = watch
        # Ask 190.4 > max 170 → must not place, must cancel Forever without LIMIT.
        quote = BidAskLtp(bid=188.0, ask=190.4, ltp=189.0)
        now = datetime(2026, 7, 24, 12, 28, tzinfo=IST)
        book._tick_watch(watch, now, quote_override=quote, check_quotes=True)

        router.place_gtt_fallback_order.assert_not_called()
        router.cancel_gtt_fallback_watch.assert_called()
        self.assertEqual(watch.phase, GttFallbackPhase.CANCELLED)

    def test_price_cap_allows_limit_below_170(self):
        router = MagicMock()
        store = MagicMock()
        rec = {
            "intent_id": "gtt-ce",
            "status": IntentStatus.SENT,
            "broker_order_id": "341",
            "payload": {"action": "ENTRY", "execution_mode": "HYBRID_GTT"},
        }
        store.get.return_value = rec
        store.has_pending_intent.return_value = False
        store.list_by_status.return_value = []
        router.intent_store = store
        router._try_sync_gtt_intent_fill.return_value = False
        router.adopt_gtt_intent_from_broker_positions.return_value = False
        router.broker.find_forever_order_by_client_id.return_value = {
            "status": "pending",
            "filled_size": 0,
            "size": 30,
            "order_id": "341",
        }
        router.broker.get_positions_for_recon.return_value = {}
        router.cancel_gtt_fallback_watch.return_value = True
        router.broker.cancel_open_day_orders_for_symbol.return_value = 0
        router.place_gtt_fallback_order.return_value = "fb-1"

        book = GttFallbackBook(router, engine_logger=None)
        watch = self._watch()
        book._watches[watch.gtt_intent_id] = watch
        quote = BidAskLtp(bid=161.0, ask=162.5, ltp=162.0)
        now = datetime(2026, 7, 24, 12, 28, tzinfo=IST)
        book._tick_watch(watch, now, quote_override=quote, check_quotes=True)

        router.place_gtt_fallback_order.assert_called_once()
        _args, kwargs = router.place_gtt_fallback_order.call_args
        self.assertLess(float(kwargs["price"]), 170.0)
        self.assertEqual(watch.phase, GttFallbackPhase.FALLBACK_SENT)

    def test_gtt_still_unfilled_treats_triggered_as_filled(self):
        router = MagicMock()
        router.broker.find_forever_order_by_client_id.return_value = {
            "status": "triggered",
            "filled_size": 0,
            "size": 30,
        }
        book = GttFallbackBook(router, engine_logger=None)
        watch = self._watch()
        self.assertFalse(book._gtt_still_unfilled(watch, None))


if __name__ == "__main__":
    unittest.main()
