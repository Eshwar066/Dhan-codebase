from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

from core.strategies.crypto.DirectionalOptionSelling.DirectionalOptionSelling import (
    DirectionalOptionSelling,
)


class _PositionStore:
    def __init__(self, positions=None):
        self.positions = list(positions or [])

    def get_open_positions(self, **_kwargs):
        return list(self.positions)


class _LiveSource:
    def __init__(self, products, tickers):
        self.products = products
        self.tickers = tickers

    def get_products(self, use_cache=True):
        return list(self.products)

    def get_option_tickers_for_expiry(self, _underlying, expiry, _opt):
        return {
            symbol: ticker
            for symbol, ticker in self.tickers.items()
            if symbol.endswith(f"-{expiry}")
        }

    def get_ticker(self, symbol):
        return self.tickers.get(symbol)


def _ticker(bid):
    return {"quotes": {"best_bid": bid, "best_ask": bid + 5}}


class DirectionalOptionSellingTests(unittest.TestCase):
    def setUp(self):
        self.strategy = DirectionalOptionSelling()

    def test_live_selection_uses_nearest_eligible_strike(self):
        products = [
            {"symbol": "P-BTC-118500-170726", "strike_price": 118500},
            {"symbol": "P-BTC-118000-170726", "strike_price": 118000},
            {"symbol": "P-BTC-119000-170726", "strike_price": 119000},
            {"symbol": "P-BTC-118500-180726", "strike_price": 118500},
            {"symbol": "P-BTC-118000-180726", "strike_price": 118000},
        ]
        source = _LiveSource(
            products,
            {
                "P-BTC-118500-170726": _ticker(250),
                "P-BTC-118000-170726": _ticker(320),
                "P-BTC-119000-170726": _ticker(400),
                "P-BTC-118500-180726": _ticker(500),
                "P-BTC-118000-180726": _ticker(350),
            },
        )
        candle = {
            "symbol": "BTCUSD",
            "timestamp": datetime(2026, 7, 17, 6, 0, tzinfo=timezone.utc),
            "close": 119000,
        }
        with patch(
            "core.strategies.crypto.DirectionalOptionSelling."
            "DirectionalOptionSelling._delta_source_from_ctx",
            return_value=source,
        ):
            selected = self.strategy._select_live_contract(
                candle,
                SimpleNamespace(),
                "PE",
                118450,
                min_dte=0,
                min_strike_distance=0,
            )
        self.assertIsNotNone(selected)
        self.assertEqual(selected[0], 118000)
        self.assertEqual(selected[3], "170726")

    def test_rollover_selection_enforces_200_point_strike_distance(self):
        products = [
            {"symbol": "P-BTC-118500-180726", "strike_price": 118500},
            {"symbol": "P-BTC-118000-180726", "strike_price": 118000},
        ]
        source = _LiveSource(
            products,
            {
                "P-BTC-118500-180726": _ticker(500),
                "P-BTC-118000-180726": _ticker(350),
            },
        )
        candle = {
            "symbol": "BTCUSD",
            "timestamp": datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc),
            "close": 119000,
        }
        with patch(
            "core.strategies.crypto.DirectionalOptionSelling."
            "DirectionalOptionSelling._delta_source_from_ctx",
            return_value=source,
        ):
            selected = self.strategy._select_live_contract(
                candle,
                SimpleNamespace(),
                "PE",
                118450,
                min_dte=1,
                min_strike_distance=200,
            )
        self.assertIsNotNone(selected)
        self.assertEqual(selected[0], 118000)
        self.assertEqual(selected[3], "180726")

    def test_expiry_order_prefers_today_then_next_listed(self):
        ordered = self.strategy._ordered_expiries(
            ["190726", "170726", "180726"],
            datetime(2026, 7, 17).date(),
            0,
        )
        self.assertEqual(ordered, ["170726", "180726"])
        self.assertEqual(
            self.strategy._ordered_expiries(
                ["170726", "180726", "190726"],
                datetime(2026, 7, 17).date(),
                1,
            ),
            ["180726"],
        )

    def test_prepare_indicators_adds_backtest_supertrend_columns(self):
        rows = 80
        frame = pd.DataFrame(
            {
                "high": [100 + index for index in range(rows)],
                "low": [98 + index for index in range(rows)],
                "close": [99 + index for index in range(rows)],
            }
        )
        result = self.strategy.prepare_indicators(frame)
        self.assertIn("supertrend", result.columns)
        self.assertIn("supertrend_direction", result.columns)
        self.assertFalse(pd.isna(result.iloc[-1]["supertrend"]))

    def test_first_direction_only_initializes_then_flip_enters(self):
        ctx = SimpleNamespace(position_store=_PositionStore())
        bullish = {
            "symbol": "BTCUSD",
            "timestamp": datetime(2026, 7, 17, 6, 0, tzinfo=timezone.utc),
            "close": 118800,
            "supertrend": 118000,
            "supertrend_direction": 1,
        }
        bearish = {
            **bullish,
            "timestamp": datetime(2026, 7, 17, 7, 0, tzinfo=timezone.utc),
            "close": 117800,
            "supertrend_direction": -1,
        }
        self.assertIsNone(self.strategy.on_candle(bullish, ctx))
        marker = object()
        with patch.object(self.strategy, "_build_entry", return_value=marker) as build:
            result = self.strategy.on_candle(bearish, ctx)
        self.assertEqual(result, [marker])
        self.assertEqual(build.call_args.args[2], -1)

    def test_quote_force_exit_uses_300_point_boundary(self):
        instrument = SimpleNamespace(
            option_type="PE",
            expiry="180726",
            strike=118000,
            trading_symbol="P-BTC-118000-180726",
        )
        position = SimpleNamespace(
            tag="MAIN",
            net_qty=-1,
            structure_id="DirectionalOptionSelling:BTCUSD:test",
            instrument=instrument,
            intent_id=None,
            avg_price=350,
        )
        ctx = SimpleNamespace(
            position_store=_PositionStore([position]),
            intent_store=None,
        )
        self.strategy._confirmed_direction = 1
        self.strategy._current_supertrend = 118000
        marker = object()
        quote = {
            "symbol": "BTCUSD",
            "ltp": 117700,
            "ts": datetime(2026, 7, 17, 6, 0, tzinfo=timezone.utc).timestamp(),
        }
        with patch.object(self.strategy, "_exit_intent", return_value=marker):
            result = self.strategy.on_quote(quote, ctx)
        self.assertEqual(result, [marker])
        self.assertEqual(self.strategy._force_reentry_direction, 1)

    def test_force_exit_reentry_waits_for_later_valid_close(self):
        ctx = SimpleNamespace(position_store=_PositionStore())
        force_time = datetime(2026, 7, 17, 6, 15, tzinfo=timezone.utc)
        self.strategy._confirmed_direction = 1
        self.strategy._current_supertrend = 118000
        self.strategy._force_reentry_direction = 1
        self.strategy._force_exit_after = self.strategy._timestamp_ist(force_time)
        candle = {
            "symbol": "BTCUSD",
            "timestamp": datetime(2026, 7, 17, 7, 0, tzinfo=timezone.utc),
            "close": 118100,
            "supertrend": 118000,
            "supertrend_direction": 1,
        }
        marker = object()
        with patch.object(self.strategy, "_build_entry", return_value=marker) as build:
            result = self.strategy.on_candle(candle, ctx)
        self.assertEqual(result, [marker])
        self.assertEqual(build.call_args.kwargs["reason"], "force_exit_reentry")
        self.assertIsNone(self.strategy._force_reentry_direction)


if __name__ == "__main__":
    unittest.main()
