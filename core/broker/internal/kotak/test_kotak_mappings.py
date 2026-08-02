"""Unit tests for Kotak Neo dual-venue mappings and feed normalize."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.broker.internal.kotak import mappings as kotak_map
from core.broker.internal.kotak.broker import KotakBroker
from core.broker.internal.kotak.api import KotakBrokerApi
from core.data.feeds.kotak_feed import normalize_kotak_tick
from core.data.feeds.kotak_order_update_feed import normalize_kotak_order_update


class TestKotakMappings(unittest.TestCase):
    def test_segment_and_order_type(self):
        self.assertEqual(kotak_map.internal_segment_to_neo("NFO"), "nse_fo")
        self.assertEqual(kotak_map.internal_segment_to_neo("NSE"), "nse_cm")
        self.assertEqual(kotak_map.normalize_order_type("MARKET"), "MKT")
        self.assertEqual(kotak_map.normalize_order_type("SL-M"), "SL-M")
        self.assertEqual(kotak_map.normalize_product("MARGIN", "NFO"), "NRML")
        self.assertEqual(kotak_map.normalize_transaction("SELL"), "S")

    def test_intent_to_payload(self):
        inst = SimpleNamespace(
            place_order_symbol=lambda: "NIFTY24JUL25000CE",
            segment="NFO",
            lot_size=25,
            instrument_id="12345",
        )
        intent = SimpleNamespace(
            instrument=inst,
            qty=1,
            price=100.0,
            trigger_price=0,
            side="BUY",
            order_type="LIMIT",
            trade_type="MARGIN",
            intent_id="abc-123",
        )
        payload = kotak_map.intent_to_neo_payload(intent)
        self.assertEqual(payload["exchange_segment"], "nse_fo")
        self.assertEqual(payload["product"], "NRML")
        self.assertEqual(payload["order_type"], "L")
        self.assertEqual(payload["quantity"], "25")
        self.assertEqual(payload["transaction_type"], "B")
        self.assertEqual(payload["trading_symbol"], "NIFTY24JUL25000CE")

    def test_extract_order_id(self):
        self.assertEqual(
            kotak_map.extract_order_id({"nOrdNo": "998877"}),
            "998877",
        )
        self.assertEqual(
            kotak_map.extract_order_id({"data": {"orderId": "1"}}),
            "1",
        )


class TestKotakFeedNormalize(unittest.TestCase):
    def test_normalize_tick(self):
        tick = normalize_kotak_tick(
            {"tok": "26000", "ltp": 24500.5, "v": 10, "ft": 1720000000},
            {"26000": "NIFTY"},
        )
        self.assertIsNotNone(tick)
        self.assertEqual(tick["symbol"], "NIFTY")
        self.assertEqual(tick["price"], 24500.5)
        self.assertEqual(tick["volume"], 10.0)

    def test_normalize_order_fill(self):
        trade = normalize_kotak_order_update(
            {
                "nOrdNo": "55",
                "trdSym": "RELIANCE",
                "ordSt": "complete",
                "trantype": "B",
                "fldQty": 1,
                "avgPrc": 2500.0,
            }
        )
        self.assertIsNotNone(trade)
        self.assertTrue(str(trade["order_id"]).startswith("KOTAK_WS:"))
        self.assertEqual(trade["side"], "BUY")
        self.assertEqual(trade["qty"], 1.0)
        self.assertEqual(trade["price"], 2500.0)


class TestKotakBrokerPlace(unittest.TestCase):
    def test_place_order_prefixes_rest_id(self):
        api = MagicMock()
        api.place_order.return_value = {
            "status": "success",
            "order_id": "42",
            "message": "",
        }
        broker = KotakBroker(api=api)
        intent = {
            "trading_symbol": "RELIANCE",
            "segment": "NSE",
            "qty": 1,
            "lot_size": 1,
            "side": "BUY",
            "order_type": "MARKET",
            "price": 0,
            "trigger_price": 0,
            "trade_type": "MIS",
            "intent_id": "t1",
        }
        oid = broker.place_order(intent)
        self.assertEqual(oid, "KOTAK_REST:42")
        api.place_order.assert_called_once()

    def test_broker_api_maps_segment(self):
        source = MagicMock()
        source.place_order.return_value = {
            "status": "success",
            "order_id": "9",
            "message": "",
        }
        api = KotakBrokerApi(source)
        api.place_order(
            tradingsymbol="RELIANCE",
            exchange="NSE",
            quantity=1,
            order_type="LIMIT",
            price=100,
            transaction_type="BUY",
            trade_type="MIS",
        )
        kwargs = source.place_order.call_args.kwargs
        self.assertEqual(kwargs["exchange_segment"], "nse_cm")
        self.assertEqual(kwargs["order_type"], "L")
        self.assertEqual(kwargs["transaction_type"], "B")


if __name__ == "__main__":
    unittest.main()
