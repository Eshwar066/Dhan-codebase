"""DH-906: SELL STOPLIMIT must have trigger_price > price after tick quantize."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from core.broker.internal.dhan.broker import _order_intent_to_payload, _quantize_order_prices


class TestDh906SlPricing(unittest.TestCase):
    def test_quantize_sell_stop_nudges_limit_below_trigger(self):
        out = _quantize_order_prices(
            {
                "tradingsymbol": "BANKNIFTY 28 JUL 55900 PUT",
                "price": 72,
                "trigger_price": 72,
                "order_type": "STOPLIMIT",
                "transaction_type": "SELL",
            },
            instrument=SimpleNamespace(tick_size=0.05),
            side="SELL",
        )
        self.assertGreater(float(out["trigger_price"]), float(out["price"]))
        self.assertEqual(float(out["trigger_price"]), 72.0)
        self.assertEqual(float(out["price"]), 71.95)

    def test_order_intent_payload_sell_sl_not_equal(self):
        inst = SimpleNamespace(
            segment="NFO",
            lot_size=30,
            tick_size=0.05,
            place_order_symbol=lambda: "BANKNIFTY 28 JUL 55900 PUT",
        )
        intent = SimpleNamespace(
            instrument=inst,
            price=72.0,
            trigger_price=72.0,
            order_type="SL",
            qty=1,
            side="SELL",
            intent_id="sl-1",
            trade_type="MARGIN",
            metadata_extras={},
        )
        payload = _order_intent_to_payload(intent)
        self.assertEqual(payload["order_type"], "STOPLIMIT")
        self.assertGreater(
            float(payload["trigger_price"]), float(payload["price"])
        )


if __name__ == "__main__":
    unittest.main()
