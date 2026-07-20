"""Delta must never place market orders (plain or stop-market)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from core.broker.internal.delta.broker import (
    DeltaBroker,
    _delta_limit_price_from_payload,
    _intent_to_delta_payload,
)
from core.data.sources.delta_source import DeltaSource


class TestDeltaNoMarketOrders(unittest.TestCase):
    def test_payload_default_is_limit(self):
        payload = _intent_to_delta_payload(
            {
                "intent_id": "i1",
                "trading_symbol": "C-BTC",
                "side": "BUY",
                "qty": 1,
                "price": 12.5,
            }
        )
        self.assertEqual(payload["order_type"], "LIMIT")

    def test_limit_price_helper(self):
        self.assertEqual(
            _delta_limit_price_from_payload({"price": 0, "trigger_price": 9}),
            9.0,
        )
        self.assertIsNone(_delta_limit_price_from_payload({"price": 0, "trigger_price": 0}))

    def test_place_order_refuses_market_without_price(self):
        broker = DeltaBroker.__new__(DeltaBroker)
        broker.api = MagicMock()
        broker.intent_store = None
        broker._last_place_order_failure = None
        oid = broker.place_order(
            {
                "intent_id": "m1",
                "trading_symbol": "C-BTC",
                "side": "BUY",
                "qty": 1,
                "order_type": "MARKET",
                "price": 0,
            }
        )
        self.assertIsNone(oid)
        broker.api.place_order.assert_not_called()
        self.assertEqual(
            broker._last_place_order_failure["error_code"],
            "market_order_forbidden",
        )

    def test_place_order_coerces_market_to_limit(self):
        broker = DeltaBroker.__new__(DeltaBroker)
        broker.api = MagicMock()
        broker.api.place_order.return_value = {
            "status": "success",
            "order_id": "oid-1",
        }
        broker.intent_store = None
        broker._last_place_order_failure = None
        oid = broker.place_order(
            {
                "intent_id": "m2",
                "trading_symbol": "C-BTC",
                "side": "BUY",
                "qty": 1,
                "order_type": "MARKET",
                "price": 11.0,
            }
        )
        self.assertEqual(oid, "oid-1")
        kwargs = broker.api.place_order.call_args.kwargs
        self.assertEqual(kwargs["order_type"], "LIMIT")
        self.assertEqual(kwargs["price"], 11.0)

    def test_sl_m_coerced_to_stop_limit(self):
        broker = DeltaBroker.__new__(DeltaBroker)
        broker.api = MagicMock()
        broker.api.place_bracket_stop_loss.return_value = {
            "status": "success",
            "order_id": "sl-1",
        }
        broker.intent_store = None
        broker._last_place_order_failure = None
        oid = broker.place_order(
            {
                "intent_id": "sl1",
                "trading_symbol": "C-BTC",
                "side": "BUY",
                "qty": 1,
                "order_type": "SL-M",
                "price": 5.0,
                "trigger_price": 5.0,
                "action": "FORCE_EXIT",
            }
        )
        self.assertEqual(oid, "sl-1")
        kwargs = broker.api.place_bracket_stop_loss.call_args.kwargs
        self.assertEqual(kwargs["price"], 5.0)

    def test_bracket_leg_payload_never_market(self):
        leg = DeltaSource._bracket_leg_payload(10.0, None)
        self.assertEqual(leg["order_type"], "limit_order")
        self.assertEqual(leg["limit_price"], "10.0")
        with self.assertRaises(ValueError):
            DeltaSource._bracket_leg_payload(0, None)


if __name__ == "__main__":
    unittest.main()
