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
        # Nearest eligible with premium >= MIN_PREMIUM_USD (150): 118500 @ 250.
        self.assertEqual(selected[0], 118500)
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

    def test_trail_sl_levels_follow_supertrend(self):
        self.assertEqual(self.strategy._trail_sl_level(1, 118000), 117900)
        self.assertEqual(self.strategy._trail_sl_level(-1, 118000), 118100)
        self.assertEqual(self.strategy._force_exit_level(1, 118000), 117700)
        self.assertEqual(self.strategy._force_exit_level(-1, 118000), 118300)

    def test_quote_force_exit_uses_300_point_strategy_level(self):
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
            order_router=None,
        )
        self.strategy._confirmed_direction = 1
        self.strategy._current_supertrend = 118000
        marker = object()
        # Broker trail is ST-100=117900; strategy emergency is ST-300=117700.
        quote_inside_trail = {
            "symbol": "BTCUSD",
            "ltp": 117900,
            "ts": datetime(2026, 7, 17, 6, 0, tzinfo=timezone.utc).timestamp(),
        }
        with patch.object(self.strategy, "_exit_intent", return_value=marker):
            self.assertIsNone(self.strategy.on_quote(quote_inside_trail, ctx))
        quote = {
            "symbol": "BTCUSD",
            "ltp": 117700,
            "ts": datetime(2026, 7, 17, 6, 1, tzinfo=timezone.utc).timestamp(),
        }
        with patch.object(self.strategy, "_exit_intent", return_value=marker):
            result = self.strategy.on_quote(quote, ctx)
        self.assertEqual(result, [marker])
        self.assertEqual(self.strategy._sl_reentry_direction, 1)

    def test_same_direction_supertrend_modifies_broker_sl(self):
        instrument = SimpleNamespace(
            option_type="PE",
            expiry="180726",
            strike=118000,
            trading_symbol="P-BTC-118000-180726",
            product_id=99,
        )
        position = SimpleNamespace(
            tag="MAIN",
            net_qty=-1,
            structure_id="DirectionalOptionSelling:BTCUSD:test",
            instrument=instrument,
            intent_id="entry1",
            avg_price=350,
        )
        broker = SimpleNamespace(
            update_pending_sl_trigger=lambda *_a, **_k: True,
            update_order_stop_price=lambda **_k: False,
        )
        ctx = SimpleNamespace(
            position_store=_PositionStore([position]),
            intent_store=None,
            order_router=SimpleNamespace(broker=broker),
        )
        self.strategy._confirmed_direction = 1
        self.strategy._current_supertrend = 118000
        candle = {
            "symbol": "BTCUSD",
            "timestamp": datetime(2026, 7, 17, 7, 0, tzinfo=timezone.utc),
            "close": 118500,
            "supertrend": 118200,
            "supertrend_direction": 1,
        }
        with patch.object(
            self.strategy, "_modify_broker_trail_sl", return_value=True
        ) as modify:
            self.assertIsNone(self.strategy.on_candle(candle, ctx))
        self.assertEqual(self.strategy._current_supertrend, 118200)
        self.assertEqual(modify.call_args.kwargs["supertrend"], 118200)
        self.assertEqual(modify.call_args.kwargs["direction"], 1)

    def test_on_main_entry_filled_arms_spot_trail_sl(self):
        instrument = SimpleNamespace(
            option_type="PE",
            expiry="180726",
            strike=118000,
            trading_symbol="P-BTC-118000-180726",
            lot_size=1,
        )
        self.strategy._confirmed_direction = 1
        self.strategy._current_supertrend = 118000
        from core.strategies.crypto.DirectionalOptionSelling.DirectionalOptionSelling import (
            _PositionMeta,
        )

        self.strategy._meta_by_structure_id["sid1"] = _PositionMeta(
            symbol="BTCUSD",
            direction=1,
            option_type="PE",
            supertrend=118000,
            strike=118000,
            expiry="180726",
            entry_premium=350,
            entry_reason="test",
        )
        intents = self.strategy.on_main_entry_filled(
            ctx=SimpleNamespace(position_store=_PositionStore()),
            structure_id="sid1",
            instrument=instrument,
            qty=1,
            intent_id="parent1",
            price=350,
            candle_ts=datetime(2026, 7, 17, 6, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(len(intents), 1)
        sl = intents[0]
        self.assertEqual(sl.tag, "MAIN_SL")
        self.assertEqual(sl.order_type, "SL")
        self.assertEqual(sl.trigger_price, 117900)
        self.assertEqual(sl.price, 350)
        self.assertEqual(sl.metadata_extras["stop_trigger_method"], "spot_price")
        self.assertEqual(sl.metadata_extras["direction"], 1)

    def test_sl_at_1101_reenters_on_1130_close_same_direction(self):
        """SL at 11:01 inside 10:30→11:30 bar → re-enter at that bar's 11:30 close."""
        ctx = SimpleNamespace(position_store=_PositionStore())
        # Candle bucket start 10:30 IST; SL fill wall-clock 11:01 IST.
        sl_ts = datetime(2026, 7, 17, 5, 31, tzinfo=timezone.utc)  # 11:01 IST
        bar_open = datetime(2026, 7, 17, 5, 0, tzinfo=timezone.utc)  # 10:30 IST
        self.strategy._confirmed_direction = 1
        self.strategy._current_supertrend = 118000
        self.strategy._arm_sl_reentry(1, sl_ts)
        self.assertEqual(
            self.strategy._closed_bar_time_ist({"timestamp": bar_open}).time().hour,
            11,
        )
        self.assertTrue(
            self.strategy._sl_reentry_ready({"timestamp": bar_open})
        )
        candle = {
            "symbol": "BTCUSD",
            "timestamp": bar_open,
            "close": 118100,
            "supertrend": 118000,
            "supertrend_direction": 1,
        }
        marker = object()
        with patch.object(self.strategy, "_build_entry", return_value=marker) as build:
            result = self.strategy.on_candle(candle, ctx)
        self.assertEqual(result, [marker])
        self.assertEqual(build.call_args.kwargs["reason"], "sl_reentry_same")

    def test_sl_reentry_same_direction_after_next_hour_close(self):
        ctx = SimpleNamespace(position_store=_PositionStore())
        force_time = datetime(2026, 7, 17, 6, 15, tzinfo=timezone.utc)
        self.strategy._confirmed_direction = 1
        self.strategy._current_supertrend = 118000
        self.strategy._arm_sl_reentry(1, force_time)
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
        self.assertEqual(build.call_args.kwargs["reason"], "sl_reentry_same")
        self.assertIsNone(self.strategy._sl_reentry_direction)

    def test_sl_reentry_flip_direction_after_next_hour_close(self):
        ctx = SimpleNamespace(position_store=_PositionStore())
        force_time = datetime(2026, 7, 17, 6, 15, tzinfo=timezone.utc)
        self.strategy._confirmed_direction = 1
        self.strategy._current_supertrend = 118000
        self.strategy._arm_sl_reentry(1, force_time)
        candle = {
            "symbol": "BTCUSD",
            "timestamp": datetime(2026, 7, 17, 7, 0, tzinfo=timezone.utc),
            "close": 117500,
            "supertrend": 118200,
            "supertrend_direction": -1,
        }
        marker = object()
        with patch.object(self.strategy, "_build_entry", return_value=marker) as build:
            result = self.strategy.on_candle(candle, ctx)
        self.assertEqual(result, [marker])
        self.assertEqual(build.call_args.kwargs["reason"], "sl_reentry_flip")
        self.assertEqual(build.call_args.args[2], -1)
        self.assertIsNone(self.strategy._sl_reentry_direction)

    def test_main_sl_fill_arms_reentry_wait(self):
        from core.strategies.crypto.DirectionalOptionSelling.DirectionalOptionSelling import (
            _PositionMeta,
        )

        self.strategy._meta_by_structure_id["sid1"] = _PositionMeta(
            symbol="BTCUSD",
            direction=1,
            option_type="PE",
            supertrend=118000,
            strike=118000,
            expiry="180726",
            entry_premium=350,
            entry_reason="test",
        )
        self.strategy._confirmed_direction = 1
        out = self.strategy.on_main_exit_filled(
            structure_id="sid1",
            tag="MAIN_SL",
            candle_ts=datetime(2026, 7, 17, 6, 20, tzinfo=timezone.utc),
            ctx=SimpleNamespace(spot_price=117800),
        )
        self.assertEqual(out, [])
        self.assertEqual(self.strategy._sl_reentry_direction, 1)
        self.assertIsNotNone(self.strategy._sl_reentry_after)


if __name__ == "__main__":
    unittest.main()
