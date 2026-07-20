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
        # Outside SuperTrend PE (strike < ST 118450) nearest ST with premium >= 120: 118000.
        self.assertEqual(selected[0], 118000)
        self.assertEqual(selected[3], "170726")

    def test_live_selection_rejects_itm_and_atm(self):
        products = [
            {"symbol": "C-BTC-64400-190726", "strike_price": 64400},  # ITM CE
            {"symbol": "C-BTC-64500-190726", "strike_price": 64500},  # not OTM (strike < spot)
            {"symbol": "C-BTC-64600-190726", "strike_price": 64600},  # OTM but inside ST
            {"symbol": "C-BTC-64800-190726", "strike_price": 64800},  # OTM but inside ST
            {"symbol": "C-BTC-65000-190726", "strike_price": 65000},  # outside ST
        ]
        source = _LiveSource(
            products,
            {
                "C-BTC-64400-190726": _ticker(211),
                "C-BTC-64500-190726": _ticker(180),
                "C-BTC-64600-190726": _ticker(160),
                "C-BTC-64800-190726": _ticker(170),
                "C-BTC-65000-190726": _ticker(125),
            },
        )
        candle = {
            "symbol": "BTCUSD",
            "timestamp": datetime(2026, 7, 19, 9, 0, tzinfo=timezone.utc),
            "close": 64501.5,
        }
        with patch(
            "core.strategies.crypto.DirectionalOptionSelling."
            "DirectionalOptionSelling._delta_source_from_ctx",
            return_value=source,
        ):
            selected = self.strategy._select_live_contract(
                candle,
                SimpleNamespace(),
                "CE",
                64837.05,
                min_dte=0,
                min_strike_distance=0,
            )
        self.assertIsNotNone(selected)
        # Outside SuperTrend CE (strike > ST): 65000 (64800 rejected as inside ST).
        self.assertEqual(selected[0], 65000)

    def test_quote_exits_when_spot_near_strike(self):
        instrument = SimpleNamespace(
            option_type="CE",
            expiry="200726",
            strike=64800,
            trading_symbol="C-BTC-64800-200726",
        )
        position = SimpleNamespace(
            tag="MAIN",
            net_qty=-10,
            structure_id="DirectionalOptionSelling:BTCUSD:prox",
            instrument=instrument,
            intent_id=None,
            avg_price=130,
        )
        ctx = SimpleNamespace(
            position_store=_PositionStore([position]),
            intent_store=None,
            order_router=None,
        )
        self.strategy._confirmed_direction = -1
        self.strategy._current_supertrend = 64775.63
        marker = object()
        quote = {
            "symbol": "BTCUSD",
            "ltp": 64760,  # within ±50 of strike 64800
            "ts": datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc).timestamp(),
        }
        with patch.object(self.strategy, "_exit_intent", return_value=marker) as exit_fn:
            result = self.strategy.on_quote(quote, ctx)
        self.assertEqual(result, [marker])
        self.assertEqual(
            exit_fn.call_args.args[3], "strategy_strike_proximity_exit"
        )

    def test_should_evaluate_waits_for_candle_close(self):
        candle = {
            "symbol": "BTCUSD",
            "timestamp": datetime(2026, 7, 19, 9, 0, tzinfo=timezone.utc),  # 14:30 IST
            "close": 64501.5,
        }
        mid_bar = datetime(2026, 7, 19, 9, 19, tzinfo=timezone.utc)  # 14:49 IST
        at_close = datetime(2026, 7, 19, 10, 0, 2, tzinfo=timezone.utc)  # 15:30:02 IST
        self.assertFalse(self.strategy._bar_is_fully_closed(candle, now=mid_bar))
        self.assertTrue(self.strategy._bar_is_fully_closed(candle, now=at_close))
        # Live engine stores UTC-naive; must not treat that wall clock as IST.
        naive_utc = {
            "symbol": "BTCUSD",
            "timestamp": datetime(2026, 7, 19, 9, 0),  # 09:00 UTC = 14:30 IST
            "close": 64501.5,
        }
        self.assertFalse(
            self.strategy._bar_is_fully_closed(naive_utc, now=datetime(2026, 7, 19, 9, 19))
        )
        self.assertTrue(
            self.strategy._bar_is_fully_closed(
                naive_utc, now=datetime(2026, 7, 19, 10, 0, 2)
            )
        )
        with patch.object(
            self.strategy,
            "_bar_is_fully_closed",
            return_value=False,
        ):
            self.assertFalse(self.strategy.should_evaluate(candle))
        with patch.object(
            self.strategy,
            "_bar_is_fully_closed",
            return_value=True,
        ):
            self.assertTrue(self.strategy.should_evaluate(candle))
            self.assertFalse(self.strategy.should_evaluate(candle))

    def test_reversal_exit_fill_enters_new_direction_immediately(self):
        """Signal EXIT fill must open the opposite side right away (same signal cycle)."""
        from core.strategies.crypto.DirectionalOptionSelling.DirectionalOptionSelling import (
            _PendingTransition,
        )

        self.strategy._pending_transition = _PendingTransition(
            previous_structure_id="sid-rev",
            direction=-1,
            reason="supertrend_reversal",
            min_dte=1,
        )
        self.strategy._confirmed_direction = -1
        self.strategy._current_supertrend = 64600
        self.strategy._latest_candle = {
            "symbol": "BTCUSD",
            "timestamp": datetime(2026, 7, 19, 14, 0, tzinfo=timezone.utc),
            "close": 64450,
            "supertrend": 64600,
            "supertrend_direction": -1,
        }
        ctx = SimpleNamespace(position_store=_PositionStore())
        marker = object()
        with patch.object(self.strategy, "_build_entry", return_value=marker) as build:
            out = self.strategy.on_main_exit_filled(
                structure_id="sid-rev",
                tag="MAIN_EXIT",
                candle_ts=datetime(2026, 7, 19, 14, 54, tzinfo=timezone.utc),
                ctx=ctx,
            )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][0], marker)
        self.assertIsInstance(out[0][1], dict)
        self.assertIsNone(self.strategy._pending_closed_entry)
        self.assertIsNone(self.strategy._pending_transition)
        self.assertEqual(build.call_args.args[2], -1)
        self.assertEqual(build.call_args.kwargs["reason"], "supertrend_reversal")

    def test_reversal_exit_fill_defers_when_entry_build_fails(self):
        """If immediate ENTRY cannot be built, fall back to next closed-bar retry."""
        from core.strategies.crypto.DirectionalOptionSelling.DirectionalOptionSelling import (
            _PendingTransition,
        )

        self.strategy._pending_transition = _PendingTransition(
            previous_structure_id="sid-rev",
            direction=-1,
            reason="supertrend_reversal",
            min_dte=1,
        )
        self.strategy._current_supertrend = 64600
        self.strategy._latest_candle = {
            "symbol": "BTCUSD",
            "timestamp": datetime(2026, 7, 19, 14, 0, tzinfo=timezone.utc),
            "close": 64450,
            "supertrend": 64600,
        }
        with patch.object(self.strategy, "_build_entry", return_value=None):
            out = self.strategy.on_main_exit_filled(
                structure_id="sid-rev",
                tag="MAIN_EXIT",
                candle_ts=datetime(2026, 7, 19, 14, 54, tzinfo=timezone.utc),
                ctx=SimpleNamespace(position_store=_PositionStore()),
            )
        self.assertEqual(out, [])
        self.assertIsNotNone(self.strategy._pending_closed_entry)
        self.assertEqual(self.strategy._pending_closed_entry.direction, -1)

    def test_st_flip_while_sl_reentry_pending_enters_immediately(self):
        """Confirmed ST flip must not wait for post-SL hour close when flat."""
        ctx = SimpleNamespace(position_store=_PositionStore())
        self.strategy._confirmed_direction = -1
        self.strategy._current_supertrend = 64616.31
        self.strategy._arm_sl_reentry(
            -1, datetime(2026, 7, 20, 3, 45, tzinfo=timezone.utc)
        )
        # Flip bar not yet "ready" for SL reentry path if we force ready=False;
        # flip path should still clear wait and enter.
        candle = {
            "symbol": "BTCUSD",
            "timestamp": datetime(2026, 7, 20, 3, 30, tzinfo=timezone.utc),
            "close": 64648.5,
            "supertrend": 64317.25,
            "supertrend_direction": 1,
        }
        marker = object()
        with patch.object(self.strategy, "_bar_is_fully_closed", return_value=True):
            with patch.object(self.strategy, "_sl_reentry_ready", return_value=False):
                with patch.object(
                    self.strategy, "_build_entry", return_value=marker
                ) as build:
                    result = self.strategy.on_candle(candle, ctx)
        self.assertEqual(result, [marker])
        self.assertEqual(build.call_args.kwargs["reason"], "supertrend_reversal")
        self.assertIsNone(self.strategy._sl_reentry_direction)

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

    def test_unconfirmed_st_flip_does_not_exit_open_position(self):
        """ST direction flicker with close still on old side must not reverse (MAIN_SL covers)."""
        instrument = SimpleNamespace(
            option_type="CE",
            expiry="200726",
            strike=64800,
            trading_symbol="C-BTC-64800-200726",
        )
        position = SimpleNamespace(
            tag="MAIN",
            net_qty=-10,
            structure_id="DirectionalOptionSelling:BTCUSD:test-ce",
            instrument=instrument,
            intent_id=None,
            avg_price=272,
        )
        ctx = SimpleNamespace(
            position_store=_PositionStore([position]),
            intent_store=None,
            order_router=None,
        )
        self.strategy._confirmed_direction = -1
        self.strategy._current_supertrend = 64616.31
        # Indicator says bullish (+1) but close is still below ST → ignore.
        flicker = {
            "symbol": "BTCUSD",
            "timestamp": datetime(2026, 7, 19, 16, 0, tzinfo=timezone.utc),
            "close": 64550.0,
            "supertrend": 64616.31,
            "supertrend_direction": 1,
        }
        with patch.object(self.strategy, "_bar_is_fully_closed", return_value=True):
            with patch.object(self.strategy, "_begin_transition") as begin:
                result = self.strategy.on_candle(flicker, ctx)
        self.assertIsNone(result)
        begin.assert_not_called()
        self.assertEqual(self.strategy._confirmed_direction, -1)

    def test_confirmed_st_flip_exits_on_closed_bar(self):
        """Closed bar with close on the new ST side may reverse."""
        instrument = SimpleNamespace(
            option_type="CE",
            expiry="200726",
            strike=64800,
            trading_symbol="C-BTC-64800-200726",
        )
        position = SimpleNamespace(
            tag="MAIN",
            net_qty=-10,
            structure_id="DirectionalOptionSelling:BTCUSD:test-ce2",
            instrument=instrument,
            intent_id=None,
            avg_price=272,
        )
        ctx = SimpleNamespace(
            position_store=_PositionStore([position]),
            intent_store=None,
            order_router=None,
        )
        self.strategy._confirmed_direction = -1
        self.strategy._current_supertrend = 64616.31
        confirmed = {
            "symbol": "BTCUSD",
            "timestamp": datetime(2026, 7, 19, 16, 0, tzinfo=timezone.utc),
            "close": 64700.0,  # above ST → confirms bullish
            "supertrend": 64616.31,
            "supertrend_direction": 1,
        }
        marker = object()
        with patch.object(self.strategy, "_bar_is_fully_closed", return_value=True):
            with patch.object(
                self.strategy, "_begin_transition", return_value=marker
            ) as begin:
                result = self.strategy.on_candle(confirmed, ctx)
        self.assertEqual(result, [marker])
        begin.assert_called_once()
        self.assertEqual(self.strategy._confirmed_direction, 1)

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

    def test_external_close_arms_sl_reentry(self):
        """EXTERNAL_CLOSE (misclassified MAIN_SL) must still arm hour-close reentry."""
        from core.strategies.crypto.DirectionalOptionSelling.DirectionalOptionSelling import (
            _PositionMeta,
        )

        self.strategy._meta_by_structure_id["sid-ext"] = _PositionMeta(
            symbol="BTCUSD",
            direction=1,
            option_type="PE",
            supertrend=64348.41,
            strike=64200,
            expiry="210726",
            entry_premium=335,
            entry_reason="supertrend_reversal",
        )
        self.strategy._confirmed_direction = 1
        self.strategy.on_forced_exit(
            structure_id="sid-ext",
            position_closed=True,
            execution_source="EXTERNAL_CLOSE",
            exit_reason="EXTERNAL_CLOSE",
            candle_ts=datetime(2026, 7, 20, 1, 56, tzinfo=timezone.utc),
        )
        self.assertEqual(self.strategy._sl_reentry_direction, 1)
        self.assertIsNotNone(self.strategy._sl_reentry_after)
        self.assertNotIn("sid-ext", self.strategy._meta_by_structure_id)

    def test_rollover_cancels_pending_main_sl_and_exits(self):
        """17:25 rollover must cancel resting FORCE_EXIT (MAIN_SL) then place MAIN_EXIT."""
        from core.orderExecution.intent_store import IntentStatus

        instrument = SimpleNamespace(
            option_type="CE",
            expiry="190726",
            strike=64400,
            trading_symbol="C-BTC-64400-190726",
            product_id=123,
        )
        position = SimpleNamespace(
            tag="MAIN",
            net_qty=-10,
            structure_id="DirectionalOptionSelling:BTCUSD:rollover",
            instrument=instrument,
            intent_id="entry1",
            avg_price=211,
        )
        sl_rec = {
            "intent_id": "sl1",
            "broker_order_id": "1424684009",
            "payload": {
                "structure_id": position.structure_id,
                "tag": "MAIN_SL",
                "strategy": "DirectionalOptionSelling",
                "action": "FORCE_EXIT",
                "trading_symbol": instrument.trading_symbol,
                "product_id": 123,
            },
        }

        class _IntentStore:
            def __init__(self):
                self.updated = []
                self._pending_force = True

            def list_by_status(self, status):
                if self._pending_force and status in (
                    IntentStatus.SENT,
                    IntentStatus.ACKED,
                    IntentStatus.VALIDATED,
                ):
                    return [sl_rec]
                return []

            def has_pending_intent(self, **kwargs):
                actions = {str(a).upper() for a in (kwargs.get("actions") or [])}
                if self._pending_force and ("FORCE_EXIT" in actions or "EXIT" in actions):
                    # After cancel, FORCE_EXIT is cleared; EXIT not yet pending.
                    if "FORCE_EXIT" in actions and "EXIT" in actions:
                        return self._pending_force
                    if actions == {"FORCE_EXIT"}:
                        return self._pending_force
                    if actions == {"EXIT"}:
                        return False
                return self._pending_force and "FORCE_EXIT" in actions

            def update(self, intent_id, status, **kwargs):
                self.updated.append((intent_id, status))
                if status == IntentStatus.CANCELLED:
                    self._pending_force = False

            def get(self, intent_id):
                return sl_rec if intent_id == "sl1" else None

        class _Broker:
            def __init__(self):
                self.cancelled = []

            def cancel_order_by_id(self, order_id, **kwargs):
                self.cancelled.append((order_id, kwargs))
                return True

            def find_bracket_leg_order_id(self, *_a, **_k):
                return "1424684009"

        broker = _Broker()
        intent_store = _IntentStore()
        ctx = SimpleNamespace(
            position_store=_PositionStore([position]),
            intent_store=intent_store,
            order_router=SimpleNamespace(broker=broker),
        )
        self.strategy._confirmed_direction = -1
        self.strategy._current_supertrend = 64827.25
        quote = {
            "symbol": "BTCUSD",
            "ltp": 64500,
            "ts": datetime(2026, 7, 19, 11, 55, tzinfo=timezone.utc).timestamp(),  # 17:25 IST
        }
        marker = object()
        with patch.object(self.strategy, "_exit_intent", return_value=marker) as exit_fn:
            result = self.strategy.on_quote(quote, ctx)
        self.assertEqual(result, [marker])
        self.assertTrue(broker.cancelled)
        self.assertEqual(intent_store.updated[0][0], "sl1")
        self.assertEqual(
            self.strategy._pending_transition.reason, "expiry_rollover"
        )
        self.assertEqual(self.strategy._pending_transition.min_dte, 1)
        self.assertEqual(self.strategy._pending_transition.direction, -1)
        self.assertAlmostEqual(self.strategy._current_supertrend, 64827.25)
        exit_fn.assert_called_once()
        self.assertIn(datetime(2026, 7, 19).date(), self.strategy._rollover_dates)


if __name__ == "__main__":
    unittest.main()
