from datetime import datetime, timezone
from types import SimpleNamespace
import time
import unittest
from unittest.mock import MagicMock, patch

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
        # Default: allow entries in _build_entry; keep snapshot empty so HTF
        # filter stubs do not auto-fire in unrelated tests.
        self._htf_allow = patch.object(
            self.strategy, "_htf_entry_allowed", return_value=True
        )
        self._htf_snap = patch.object(
            self.strategy, "_htf_snapshot", return_value=None
        )
        self._htf_allow.start()
        self._htf_snap.start()
        self.addCleanup(self._htf_allow.stop)
        self.addCleanup(self._htf_snap.stop)

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

    def test_live_selection_skips_strikes_inside_spot_gate(self):
        """|strike−spot| < 400 skipped; fall through to next eligible CE."""
        products = [
            {"symbol": "C-BTC-65400-270726", "strike_price": 65400},  # ~133 from spot
            {"symbol": "C-BTC-65500-270726", "strike_price": 65500},  # ~233
            {"symbol": "C-BTC-65700-270726", "strike_price": 65700},  # ~433 OK
            {"symbol": "C-BTC-65800-270726", "strike_price": 65800},  # farther
        ]
        source = _LiveSource(
            products,
            {
                "C-BTC-65400-270726": _ticker(141),
                "C-BTC-65500-270726": _ticker(100),
                "C-BTC-65700-270726": _ticker(55),
                "C-BTC-65800-270726": _ticker(40),
            },
        )
        candle = {
            "symbol": "BTCUSD",
            "timestamp": datetime(2026, 7, 27, 4, 0, tzinfo=timezone.utc),
            "close": 65267.5,
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
                65354.57,
                min_dte=0,
                min_strike_distance=0,
                min_premium=20,
                min_strike_spot_distance=400,
            )
        self.assertIsNotNone(selected)
        self.assertEqual(selected[0], 65700)
        self.assertEqual(selected[3], "270726")

    def test_live_selection_weekly_deeper_otm_skips_nearest(self):
        """otm_skip=1 → OTM2 (skip nearest eligible outside ST)."""
        products = [
            {"symbol": "P-BTC-65500-310726", "strike_price": 65500},  # OTM1
            {"symbol": "P-BTC-65400-310726", "strike_price": 65400},  # OTM2
            {"symbol": "P-BTC-65300-310726", "strike_price": 65300},  # OTM3
            {"symbol": "P-BTC-65700-310726", "strike_price": 65700},  # ITM vs spot
        ]
        source = _LiveSource(
            products,
            {
                "P-BTC-65500-310726": _ticker(200),
                "P-BTC-65400-310726": _ticker(180),
                "P-BTC-65300-310726": _ticker(160),
                "P-BTC-65700-310726": _ticker(220),
            },
        )
        candle = {
            "symbol": "BTCUSD",
            "timestamp": datetime(2026, 7, 23, 6, 0, tzinfo=timezone.utc),
            "close": 65600,
        }
        with patch(
            "core.strategies.crypto.DirectionalOptionSelling."
            "DirectionalOptionSelling._delta_source_from_ctx",
            return_value=source,
        ):
            nearest = self.strategy._select_live_contract(
                candle,
                SimpleNamespace(),
                "PE",
                65650,
                min_dte=0,
                min_strike_distance=0,
                otm_skip=0,
            )
            deeper = self.strategy._select_live_contract(
                candle,
                SimpleNamespace(),
                "PE",
                65650,
                min_dte=0,
                min_strike_distance=0,
                otm_skip=1,
            )
        self.assertIsNotNone(nearest)
        self.assertEqual(nearest[0], 65500)
        self.assertIsNotNone(deeper)
        self.assertEqual(deeper[0], 65400)

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
        """1H flip with 1D+4H green should open daily even if SL-reentry is armed."""
        ctx = SimpleNamespace(position_store=_PositionStore())
        self.strategy._confirmed_direction = -1
        self.strategy._current_supertrend = 64616.31
        self.strategy._arm_sl_reentry(
            -1, datetime(2026, 7, 20, 3, 45, tzinfo=timezone.utc)
        )
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
                    self.strategy,
                    "_refresh_htf_state",
                    return_value={"4h": (1, 64300.0), "1d": (1, 64000.0)},
                ):
                    with patch.object(
                        self.strategy, "_build_entry", return_value=marker
                    ) as build:
                        result = self.strategy.on_candle(candle, ctx)
        daily_calls = [
            c for c in build.call_args_list if c.kwargs.get("sleeve") == "daily"
        ]
        self.assertEqual(len(daily_calls), 1)
        self.assertEqual(daily_calls[0].kwargs["reason"], "one_h_signal")
        self.assertIn(marker, result or [])

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
        """1H flip enters daily only when 1D+4H match that 1H direction."""
        ctx = SimpleNamespace(position_store=_PositionStore())
        bullish = {
            "symbol": "BTCUSD",
            "timestamp": datetime(2026, 7, 17, 6, 0, tzinfo=timezone.utc),
            "close": 118800,
            "supertrend": 118000,
            "supertrend_direction": 1,
        }
        with patch.object(
            self.strategy,
            "_refresh_htf_state",
            return_value={"4h": (1, 118000.0), "1d": (-1, 117000.0)},
        ):
            self.assertIsNone(self.strategy.on_candle(bullish, ctx))
        bearish = {
            **bullish,
            "timestamp": datetime(2026, 7, 17, 7, 0, tzinfo=timezone.utc),
            "close": 117800,
            "supertrend_direction": -1,
        }
        marker = object()
        with patch.object(
            self.strategy,
            "_refresh_htf_state",
            return_value={"4h": (-1, 118200.0), "1d": (-1, 117000.0)},
        ):
            with patch.object(
                self.strategy, "_build_entry", return_value=marker
            ) as build:
                result = self.strategy.on_candle(bearish, ctx)
        # Weekly + daily both want -1 when HTF is fully bearish on a 1H flip.
        self.assertIn(marker, result or [])
        daily_calls = [
            c for c in build.call_args_list if c.kwargs.get("sleeve") == "daily"
        ]
        self.assertEqual(len(daily_calls), 1)
        self.assertEqual(daily_calls[0].args[2], -1)
        self.assertEqual(daily_calls[0].kwargs["reason"], "one_h_signal")

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
        """4H flip against an open daily sleeve exits that sleeve."""
        from core.strategies.crypto.DirectionalOptionSelling.DirectionalOptionSelling import (
            _PositionMeta,
        )

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
        self.strategy._meta_by_structure_id[position.structure_id] = _PositionMeta(
            symbol="BTCUSD",
            direction=-1,
            option_type="CE",
            supertrend=64616.31,
            strike=64800,
            expiry="200726",
            entry_premium=272,
            entry_reason="one_h_signal",
            sleeve="daily",
        )
        confirmed = {
            "symbol": "BTCUSD",
            "timestamp": datetime(2026, 7, 19, 16, 0, tzinfo=timezone.utc),
            "close": 64700.0,
            "supertrend": 64616.31,
            "supertrend_direction": 1,
        }
        marker = object()
        with patch.object(self.strategy, "_bar_is_fully_closed", return_value=True):
            with patch.object(
                self.strategy,
                "_refresh_htf_state",
                return_value={"4h": (1, 64600.0), "1d": (1, 64000.0)},
            ):
                with patch.object(
                    self.strategy, "_begin_transition", return_value=marker
                ) as begin:
                    with patch.object(
                        self.strategy, "_build_entry", return_value=None
                    ):
                        result = self.strategy.on_candle(confirmed, ctx)
        self.assertEqual(result, [marker])
        self.assertEqual(begin.call_args.kwargs["reason"], "one_h_reversal")
        self.assertEqual(begin.call_args.kwargs["sleeve"], "daily")
        self.assertEqual(self.strategy._confirmed_direction, 1)

    def test_trail_sl_levels_follow_supertrend(self):
        self.assertEqual(self.strategy._trail_sl_level(1, 118000), 117900)
        self.assertEqual(self.strategy._trail_sl_level(-1, 118000), 118100)
        self.assertEqual(self.strategy._force_exit_level(1, 118000), 117700)
        self.assertEqual(self.strategy._force_exit_level(-1, 118000), 118300)

    def test_trail_sl_clamped_ce_below_strike_pe_above(self):
        """ST±100 kept when valid; otherwise clamp CE < strike / PE > strike."""
        s = self.strategy
        # CE: ST+100 already below strike → keep ST±100.
        self.assertEqual(
            s._trail_sl_level(-1, 65000, strike=65500, option_type="CE"),
            65100,
        )
        # CE: ST+100 would be >= strike → clamp to strike-1.
        self.assertEqual(
            s._trail_sl_level(-1, 65450, strike=65500, option_type="CE"),
            65499,
        )
        # PE: ST-100 already above strike → keep ST±100.
        self.assertEqual(
            s._trail_sl_level(1, 66000, strike=65500, option_type="PE"),
            65900,
        )
        # PE: ST-100 would be <= strike → clamp to strike+1.
        self.assertEqual(
            s._trail_sl_level(1, 65550, strike=65500, option_type="PE"),
            65501,
        )

    def test_morning_pe_sl_clamped_above_strike_64800(self):
        """Live bug: ST=64813.39 → ST-100=64713.39 was placed below PE strike 64800."""
        level = self.strategy._trail_sl_level(
            1, 64813.39, strike=64800.0, option_type="PE"
        )
        self.assertEqual(level, 64801.0)
        self.assertGreater(level, 64800.0)

    def test_morning_entry_filled_arms_premium_sl_2x(self):
        instrument = SimpleNamespace(
            option_type="PE",
            expiry="240726",
            strike=64800,
            trading_symbol="P-BTC-64800-240726",
            lot_size=1,
        )
        from core.strategies.crypto.DirectionalOptionSelling.DirectionalOptionSelling import (
            SL_MODE_PREMIUM,
            _PositionMeta,
        )

        sid = "DirectionalOptionSelling:BTCUSD:morning:2026-07-24:PE:2f73a05b"
        self.strategy._meta_by_structure_id[sid] = _PositionMeta(
            symbol="BTCUSD",
            direction=1,
            option_type="PE",
            supertrend=64813.39,
            strike=64800.0,
            expiry="240726",
            entry_premium=34.0,
            entry_reason="sl_reentry_flip",
            sleeve="morning",
        )
        intents = self.strategy.on_main_entry_filled(
            ctx=SimpleNamespace(position_store=_PositionStore()),
            structure_id=sid,
            instrument=instrument,
            qty=1,
            intent_id="e8a27d76",
            price=34.0,
            candle_ts=datetime(2026, 7, 24, 4, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(len(intents), 1)
        sl = intents[0]
        self.assertEqual(sl.trigger_price, 68.0)  # 2× entry premium
        self.assertEqual(sl.metadata_extras["stop_trigger_method"], "mark_price")
        self.assertEqual(sl.metadata_extras["sl_mode"], SL_MODE_PREMIUM)
        self.assertEqual(
            self.strategy._meta_by_structure_id[sid].sl_mode, SL_MODE_PREMIUM
        )

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

    def test_weekly_force_exit_ignores_1h_supertrend(self):
        """Regression: weekly ST±300 must use 4H ST, not flipped 1H ST."""
        from core.strategies.crypto.DirectionalOptionSelling.DirectionalOptionSelling import (
            _PositionMeta,
        )

        instrument = SimpleNamespace(
            option_type="PE",
            expiry="240726",
            strike=64000,
            trading_symbol="P-BTC-64000-240726",
        )
        sid = "DirectionalOptionSelling:BTCUSD:weekly:2026-07-21:PE:f4fa3a09"
        position = SimpleNamespace(
            tag="MAIN",
            net_qty=-2,
            structure_id=sid,
            instrument=instrument,
            intent_id="e1",
            avg_price=303,
        )
        ctx = SimpleNamespace(
            position_store=_PositionStore([position]),
            intent_store=None,
            order_router=None,
        )
        self.strategy._meta_by_structure_id[sid] = _PositionMeta(
            symbol="BTCUSD",
            direction=1,
            option_type="PE",
            supertrend=65659.07,
            strike=64000,
            expiry="240726",
            entry_premium=303,
            entry_reason="weekly_htf_aligned",
            sleeve="weekly",
        )
        # 1H flipped bearish with high ST (the bug path); live 4H still bullish.
        self.strategy._current_supertrend = 66827.33
        self.strategy._confirmed_direction = -1
        self.strategy._current_4h_supertrend = 65659.07
        self.strategy._confirmed_4h_direction = 1

        # Spot below bogus 1H force (66827-300=66527) but above real 4H force (65359).
        candle = {
            "symbol": "BTCUSD",
            "timestamp": datetime(2026, 7, 21, 19, 0, tzinfo=timezone.utc),
            "open": 66300,
            "high": 66400,
            "low": 66065,
            "close": 66188,
        }
        self.assertFalse(self.strategy.should_exit(position, candle, ctx))

        quote = {
            "symbol": "BTCUSD",
            "ltp": 66065,
            "ts": datetime(2026, 7, 21, 19, 0, tzinfo=timezone.utc).timestamp(),
        }
        self.assertIsNone(self.strategy.on_quote(quote, ctx))

        # Only when spot breaches 4H ST-300 should weekly force-exit.
        quote_hit = {
            "symbol": "BTCUSD",
            "ltp": 65359.07,
            "ts": datetime(2026, 7, 21, 19, 1, tzinfo=timezone.utc).timestamp(),
        }
        marker = object()
        with patch.object(self.strategy, "_exit_intent", return_value=marker):
            result = self.strategy.on_quote(quote_hit, ctx)
        self.assertEqual(result, [marker])

    def test_risk_supertrend_weekly_never_falls_back_to_1h(self):
        s = DirectionalOptionSelling()
        s._current_supertrend = 66827.33
        s._current_4h_supertrend = None
        from core.strategies.crypto.DirectionalOptionSelling.DirectionalOptionSelling import (
            _PositionMeta,
        )

        meta = _PositionMeta(
            symbol="BTCUSD",
            direction=1,
            option_type="PE",
            supertrend=65659.07,
            strike=64000,
            expiry="240726",
            entry_premium=303,
            entry_reason="weekly_htf_aligned",
            sleeve="weekly",
        )
        self.assertAlmostEqual(s._risk_supertrend_for_sleeve("weekly", meta), 65659.07)
        s._current_4h_supertrend = 65659.07
        self.assertAlmostEqual(s._risk_supertrend_for_sleeve("weekly", meta), 65659.07)
        # Daily still uses 1H.
        self.assertAlmostEqual(s._risk_supertrend_for_sleeve("daily", meta), 66827.33)

    def test_same_direction_supertrend_modifies_broker_sl(self):
        from core.strategies.crypto.DirectionalOptionSelling.DirectionalOptionSelling import (
            _PositionMeta,
        )

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
        from core.strategies.crypto.DirectionalOptionSelling.constants import (
            SL_MODE_INDEX,
        )

        self.strategy._meta_by_structure_id[position.structure_id] = _PositionMeta(
            symbol="BTCUSD",
            direction=1,
            option_type="PE",
            supertrend=118000,
            strike=118000,
            expiry="180726",
            entry_premium=350,
            entry_reason="weekly_htf_aligned",
            sleeve="weekly",
            sl_mode=SL_MODE_INDEX,
        )
        candle = {
            "symbol": "BTCUSD",
            "timestamp": datetime(2026, 7, 17, 7, 0, tzinfo=timezone.utc),
            "close": 118500,
            "supertrend": 118050,
            "supertrend_direction": 1,
            "supertrend_4h": 118200,
        }
        self.strategy._current_4h_supertrend = 118200.0
        with patch.object(
            self.strategy,
            "_refresh_htf_state",
            return_value={"4h": (1, 118200.0), "1d": (1, 117500.0)},
        ):
            with patch.object(
                self.strategy, "_modify_broker_trail_sl", return_value=True
            ) as modify:
                with patch.object(self.strategy, "_build_entry", return_value=None):
                    self.assertIsNone(self.strategy.on_candle(candle, ctx))
        self.assertEqual(self.strategy._current_supertrend, 118050)
        self.assertEqual(modify.call_args.kwargs["supertrend"], 118200)
        self.assertEqual(modify.call_args.kwargs["direction"], 1)

    def test_weekly_trail_does_not_fall_back_to_1h_st(self):
        """Weekly sleeve must ignore 1H ST when 4H reference is missing."""
        from core.strategies.crypto.DirectionalOptionSelling.DirectionalOptionSelling import (
            _PositionMeta,
        )

        instrument = SimpleNamespace(
            option_type="PE",
            expiry="240726",
            strike=64000,
            trading_symbol="P-BTC-64000-240726",
            lot_size=1,
            product_id=99,
        )
        position = SimpleNamespace(
            tag="MAIN",
            net_qty=-2,
            structure_id="DirectionalOptionSelling:BTCUSD:weekly:2026-07-21:PE:f4fa3a09",
            instrument=instrument,
            intent_id="entry1",
            avg_price=303,
        )
        ctx = SimpleNamespace(
            position_store=_PositionStore([position]),
            intent_store=None,
            order_router=SimpleNamespace(broker=SimpleNamespace()),
        )
        self.strategy._confirmed_direction = 1
        self.strategy._current_supertrend = 65059.55
        self.strategy._current_4h_supertrend = None
        from core.strategies.crypto.DirectionalOptionSelling.constants import (
            SL_MODE_INDEX,
        )

        self.strategy._meta_by_structure_id[position.structure_id] = _PositionMeta(
            symbol="BTCUSD",
            direction=1,
            option_type="PE",
            supertrend=64497.31,
            strike=64000,
            expiry="240726",
            entry_premium=303,
            entry_reason="weekly_htf_aligned",
            sleeve="weekly",
            sl_mode=SL_MODE_INDEX,
        )
        candle = {
            "symbol": "BTCUSD",
            "timestamp": datetime(2026, 7, 21, 8, 0, tzinfo=timezone.utc),
            "close": 65500,
            "supertrend": 65059.55,
            "supertrend_direction": 1,
        }
        with patch.object(self.strategy, "_refresh_htf_state", return_value=None):
            with patch.object(
                self.strategy, "_hydrate_4h_from_history", return_value=None
            ):
                with patch.object(
                    self.strategy, "_htf_supertrend", return_value=None
                ):
                    with patch.object(
                        self.strategy, "_modify_broker_trail_sl", return_value=True
                    ) as modify:
                        with patch.object(
                            self.strategy, "_build_entry", return_value=None
                        ):
                            self.strategy.on_candle(candle, ctx)
        modify.assert_not_called()
        self.assertAlmostEqual(
            self.strategy._meta_by_structure_id[position.structure_id].supertrend,
            64497.31,
        )

    def test_trail_sl_modify_fail_keeps_meta_and_retries(self):
        """ST move + broker modify False → ERROR path, meta stays, pending retry works."""
        from core.strategies.crypto.DirectionalOptionSelling.DirectionalOptionSelling import (
            TRAIL_SL_PENDING_RETRY_GAP_SEC,
            _PositionMeta,
        )

        instrument = SimpleNamespace(
            option_type="PE",
            expiry="240726",
            strike=64000,
            trading_symbol="P-BTC-64000-240726",
            lot_size=1,
            product_id=99,
        )
        position = SimpleNamespace(
            tag="MAIN",
            net_qty=-2,
            structure_id="DirectionalOptionSelling:BTCUSD:weekly:trail-retry",
            instrument=instrument,
            intent_id="entry1",
            avg_price=303,
        )
        update_fn = MagicMock(side_effect=[False, False, False, True])
        broker = SimpleNamespace(
            find_bracket_leg_order_id=lambda *_a, **_k: "oid-1",
            update_order_stop_price=update_fn,
        )
        ctx = SimpleNamespace(
            position_store=_PositionStore([position]),
            intent_store=None,
            order_router=SimpleNamespace(broker=broker),
        )
        from core.strategies.crypto.DirectionalOptionSelling.constants import (
            SL_MODE_INDEX,
        )

        sid = position.structure_id
        self.strategy._confirmed_direction = 1
        self.strategy._current_supertrend = 65000
        self.strategy._current_4h_supertrend = 64896.29
        self.strategy._meta_by_structure_id[sid] = _PositionMeta(
            symbol="BTCUSD",
            direction=1,
            option_type="PE",
            supertrend=64497.31,
            strike=64000,
            expiry="240726",
            entry_premium=303,
            entry_reason="weekly_htf_aligned",
            sleeve="weekly",
            sl_mode=SL_MODE_INDEX,
        )
        candle = {
            "symbol": "BTCUSD",
            "timestamp": datetime(2026, 7, 21, 8, 0, tzinfo=timezone.utc),
            "close": 65500,
            "supertrend": 65000,
            "supertrend_direction": 1,
            "supertrend_4h": 64896.29,
        }
        with patch.object(
            self.strategy,
            "_refresh_htf_state",
            return_value={"4h": (1, 64896.29), "1d": (1, 64000.0)},
        ):
            with patch.object(self.strategy, "_build_entry", return_value=None):
                self.strategy.on_candle(candle, ctx)

        # Immediate attempts exhausted; meta must stay at old ST until broker accepts.
        self.assertEqual(update_fn.call_count, 3)
        self.assertAlmostEqual(
            self.strategy._meta_by_structure_id[sid].supertrend, 64497.31
        )
        self.assertIn(sid, self.strategy._pending_trail_retries)
        pending = self.strategy._pending_trail_retries[sid]
        self.assertAlmostEqual(pending.target_supertrend, 64896.29)

        # Force pending gap elapsed and retry once more — 4th broker call succeeds.
        pending.last_attempt_mono = (
            time.monotonic() - float(TRAIL_SL_PENDING_RETRY_GAP_SEC) - 1.0
        )
        self.strategy._retry_pending_trail_sl(ctx)
        self.assertEqual(update_fn.call_count, 4)
        self.assertNotIn(sid, self.strategy._pending_trail_retries)
        self.assertAlmostEqual(
            self.strategy._meta_by_structure_id[sid].supertrend, 64896.29
        )

    def test_htf_prefers_indicator_history_over_rest(self):
        from datetime import timezone as tz

        s = DirectionalOptionSelling()
        as_of = pd.Timestamp("2026-07-21 14:00:00", tz="UTC")
        rows = [
            {
                "timestamp": datetime(2026, 7, 21, 0, 0, tzinfo=tz.utc),
                "indicators": {
                    "supertrend": 64497.31,
                    "supertrend_direction": 1.0,
                },
            },
            {
                "timestamp": datetime(2026, 7, 21, 4, 0, tzinfo=tz.utc),
                "indicators": {
                    "supertrend": 64896.29,
                    "supertrend_direction": 1.0,
                },
            },
            # Forming bar (not yet closed at as_of=14:00 if bar_sec=4h from 08:00)
            {
                "timestamp": datetime(2026, 7, 21, 12, 0, tzinfo=tz.utc),
                "indicators": {
                    "supertrend": 65332.39,
                    "supertrend_direction": 1.0,
                },
            },
        ]
        with patch(
            "core.strategies.crypto.DirectionalOptionSelling.htf.ind_hist.load_indicator_history_rows",
            return_value=rows,
        ):
            # 4h bars: 00:00 closes 04:00, 04:00 closes 08:00, 12:00 closes 16:00
            # as_of 14:00 → last closed is 04:00 bar (closed 08:00) wait
            # bar open 04:00 + 4h = 08:00 <= 14:00 ✓
            # bar open 12:00 + 4h = 16:00 > 14:00 ✗
            snap = s._latest_closed_st_from_indicator_history("4h", as_of)
        self.assertIsNotNone(snap)
        self.assertEqual(snap[0], 1)
        self.assertAlmostEqual(snap[1], 64896.29)

    def test_on_main_entry_filled_arms_premium_sl_2x(self):
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
            SL_MODE_PREMIUM,
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
        self.assertEqual(sl.trigger_price, 700.0)  # 2× entry
        self.assertEqual(sl.price, 700.0)  # cover LIMIT >= trigger
        self.assertEqual(sl.metadata_extras["stop_trigger_method"], "mark_price")
        self.assertEqual(sl.metadata_extras["sl_mode"], SL_MODE_PREMIUM)
        self.assertEqual(sl.metadata_extras["direction"], 1)

    def test_index_sl_ce_clamped_below_strike(self):
        """Index-mode CE: when ST+100 crosses strike, MAIN_SL clamps to strike-1."""
        instrument = SimpleNamespace(
            option_type="CE",
            expiry="240726",
            strike=65500,
            trading_symbol="C-BTC-65500-240726",
            lot_size=1,
        )
        from core.strategies.crypto.DirectionalOptionSelling.constants import (
            SL_MODE_INDEX,
        )

        sl = self.strategy._build_main_sl_intent(
            instrument=instrument,
            qty=1,
            structure_id="sid-ce-index",
            parent_intent_id=None,
            candle_ts=datetime(2026, 7, 23, 15, 0, tzinfo=timezone.utc),
            direction=-1,
            supertrend=65450,  # ST+100 = 65550 >= strike
            option_limit=147,
            strike=65500,
            option_type="CE",
            sl_mode=SL_MODE_INDEX,
            entry_premium=147,
        )
        self.assertEqual(sl.tag, "MAIN_SL")
        self.assertEqual(sl.trigger_price, 65499)
        self.assertLess(sl.trigger_price, 65500)
        self.assertEqual(sl.metadata_extras["stop_trigger_method"], "spot_price")

    def test_premium_sl_switches_to_index_when_green_and_st_favorable(self):
        """CE short: mark < entry and ST falls → cancel premium SL, arm spot ST SL."""
        from core.strategies.crypto.DirectionalOptionSelling.constants import (
            SL_MODE_INDEX,
            SL_MODE_PREMIUM,
        )
        from core.strategies.crypto.DirectionalOptionSelling.DirectionalOptionSelling import (
            _PositionMeta,
        )

        instrument = SimpleNamespace(
            option_type="CE",
            expiry="240726",
            strike=65500,
            trading_symbol="C-BTC-65500-240726",
            lot_size=1,
            product_id=11,
        )
        position = SimpleNamespace(
            tag="MAIN",
            net_qty=-1,
            structure_id="DirectionalOptionSelling:BTCUSD:daily:ce-switch",
            instrument=instrument,
            intent_id="entry1",
            avg_price=20,
        )
        ctx = SimpleNamespace(
            position_store=_PositionStore([position]),
            intent_store=None,
            order_router=SimpleNamespace(broker=SimpleNamespace()),
        )
        sid = position.structure_id
        self.strategy._meta_by_structure_id[sid] = _PositionMeta(
            symbol="BTCUSD",
            direction=-1,
            option_type="CE",
            supertrend=66000.0,
            strike=65500,
            expiry="240726",
            entry_premium=20.0,
            entry_reason="one_h_signal",
            sleeve="daily",
            sl_mode=SL_MODE_PREMIUM,
        )
        with patch.object(
            self.strategy, "_live_option_mark_price", return_value=15.0
        ):
            with patch.object(
                self.strategy, "_cancel_resting_main_sl", return_value=True
            ):
                with patch.object(
                    self.strategy, "_live_option_limit_price", return_value=16.0
                ):
                    intents = self.strategy._trail_open_sleeves(
                        ctx,
                        {
                            "close": 65000.0,
                            "timestamp": datetime(
                                2026, 7, 23, 10, 0, tzinfo=timezone.utc
                            ),
                        },
                        one_h_st=65000.0,
                        previous_st=66000.0,
                        source="test",
                    )
        self.assertEqual(len(intents), 1)
        sl = intents[0]
        self.assertEqual(sl.tag, "MAIN_SL")
        self.assertEqual(sl.metadata_extras["stop_trigger_method"], "spot_price")
        self.assertEqual(sl.metadata_extras["sl_mode"], SL_MODE_INDEX)
        # ST 65000 + 100 = 65100, CE clamp keeps SL < strike → 65100 ok
        self.assertEqual(sl.trigger_price, 65100.0)
        self.assertEqual(
            self.strategy._meta_by_structure_id[sid].sl_mode, SL_MODE_INDEX
        )

    def test_premium_sl_stays_when_still_red(self):
        from core.strategies.crypto.DirectionalOptionSelling.constants import (
            SL_MODE_PREMIUM,
        )
        from core.strategies.crypto.DirectionalOptionSelling.DirectionalOptionSelling import (
            _PositionMeta,
        )

        instrument = SimpleNamespace(
            option_type="CE",
            expiry="240726",
            strike=65500,
            trading_symbol="C-BTC-65500-240726",
            lot_size=1,
        )
        position = SimpleNamespace(
            tag="MAIN",
            net_qty=-1,
            structure_id="DirectionalOptionSelling:BTCUSD:daily:ce-red",
            instrument=instrument,
            intent_id="entry1",
            avg_price=20,
        )
        ctx = SimpleNamespace(
            position_store=_PositionStore([position]),
            intent_store=None,
            order_router=SimpleNamespace(broker=SimpleNamespace()),
        )
        sid = position.structure_id
        self.strategy._meta_by_structure_id[sid] = _PositionMeta(
            symbol="BTCUSD",
            direction=-1,
            option_type="CE",
            supertrend=66000.0,
            strike=65500,
            expiry="240726",
            entry_premium=20.0,
            entry_reason="one_h_signal",
            sleeve="daily",
            sl_mode=SL_MODE_PREMIUM,
        )
        with patch.object(
            self.strategy, "_live_option_mark_price", return_value=25.0
        ):
            intents = self.strategy._trail_open_sleeves(
                ctx,
                {
                    "close": 65000.0,
                    "timestamp": datetime(2026, 7, 23, 10, 0, tzinfo=timezone.utc),
                },
                one_h_st=65000.0,
                previous_st=66000.0,
                source="test",
            )
        self.assertEqual(intents, [])
        self.assertEqual(
            self.strategy._meta_by_structure_id[sid].sl_mode, SL_MODE_PREMIUM
        )

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
            with patch.object(
                self.strategy,
                "_refresh_htf_state",
                return_value=None,
            ):
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
            with patch.object(
                self.strategy,
                "_refresh_htf_state",
                return_value=None,
            ):
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

    def test_morning_1725_flats_without_next_expiry_roll(self):
        """Morning 0DTE at 17:25 must EXIT flat — no pending rollover re-entry."""
        from core.strategies.crypto.DirectionalOptionSelling.DirectionalOptionSelling import (
            _PositionMeta,
        )

        instrument = SimpleNamespace(
            option_type="PE",
            expiry="220726",
            strike=64000,
            trading_symbol="P-BTC-64000-220726",
            product_id=99,
        )
        position = SimpleNamespace(
            tag="MAIN",
            net_qty=-10,
            structure_id="DirectionalOptionSelling:BTCUSD:morning:2026-07-22:PE:abc123",
            instrument=instrument,
            intent_id="m-entry",
            avg_price=40,
            strategy="DirectionalOptionSelling",
        )
        self.strategy._meta_by_structure_id[position.structure_id] = _PositionMeta(
            symbol="BTCUSD",
            direction=1,
            option_type="PE",
            supertrend=65000.0,
            strike=64000.0,
            expiry="220726",
            entry_premium=40.0,
            entry_reason="morning_830",
            sleeve="morning",
        )
        ctx = SimpleNamespace(
            position_store=_PositionStore([position]),
            intent_store=None,
            order_router=None,
        )
        self.strategy._confirmed_direction = 1
        self.strategy._current_supertrend = 65000.0
        quote = {
            "symbol": "BTCUSD",
            "ltp": 65100,
            "ts": datetime(2026, 7, 22, 11, 55, tzinfo=timezone.utc).timestamp(),  # 17:25 IST
        }
        marker = object()
        with patch.object(self.strategy, "_cancel_resting_main_sl", return_value=True):
            with patch.object(
                self.strategy, "_exit_intent", return_value=marker
            ) as exit_fn:
                result = self.strategy.on_quote(quote, ctx)
        self.assertEqual(result, [marker])
        self.assertIsNone(self.strategy._pending_transition)
        exit_fn.assert_called_once()
        self.assertEqual(exit_fn.call_args.args[3], "morning_0dte_flat")
        self.assertIn(datetime(2026, 7, 22).date(), self.strategy._rollover_dates)

    def test_htf_entry_allowed_requires_1d_and_4h_match(self):
        s = DirectionalOptionSelling()
        candle = {
            "symbol": "BTCUSD",
            "timestamp": datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc),
            "close": 65000,
        }
        ctx = SimpleNamespace()
        with patch.object(
            s,
            "_htf_snapshot",
            return_value={"4h": (1, 64000.0), "1d": (1, 63000.0)},
        ):
            self.assertTrue(s._htf_entry_allowed(1, ctx, candle))
            self.assertFalse(s._htf_entry_allowed(-1, ctx, candle))
        with patch.object(
            s,
            "_htf_snapshot",
            return_value={"4h": (-1, 66000.0), "1d": (1, 63000.0)},
        ):
            self.assertFalse(s._htf_entry_allowed(1, ctx, candle))
            self.assertFalse(s._htf_entry_allowed(-1, ctx, candle))
        with patch.object(
            s,
            "_htf_snapshot",
            return_value={"4h": (-1, 66000.0), "1d": (-1, 67000.0)},
        ):
            self.assertTrue(s._htf_entry_allowed(-1, ctx, candle))

    def test_build_entry_blocked_when_htf_misaligned(self):
        self.strategy._current_supertrend = 64000.0
        candle = {
            "symbol": "BTCUSD",
            "timestamp": datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc),
            "close": 65000,
            "supertrend": 64000,
        }
        ctx = SimpleNamespace(position_store=_PositionStore())
        with patch.object(self.strategy, "_htf_entry_allowed", return_value=False):
            with patch.object(self.strategy, "_select_contract") as select:
                self.assertIsNone(
                    self.strategy._build_entry(
                        candle, ctx, 1, reason="supertrend_reversal"
                    )
                )
                select.assert_not_called()

    def test_flat_htf_aligned_does_not_enter_weekly_or_daily_on_1h(self):
        """Weekly waits for 4H close; daily waits for a 1H ST flip."""
        self.strategy._confirmed_direction = 1
        self.strategy._current_supertrend = 64000.0
        candle = {
            "symbol": "BTCUSD",
            "timestamp": datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc),
            "close": 65000,
            "supertrend": 64000,
            "supertrend_direction": 1,
        }
        ctx = SimpleNamespace(position_store=_PositionStore())
        marker = object()
        with patch.object(
            self.strategy,
            "_refresh_htf_state",
            return_value={"4h": (1, 63500.0), "1d": (1, 62000.0)},
        ):
            with patch.object(
                self.strategy, "_bar_is_fully_closed", return_value=True
            ):
                with patch.object(
                    self.strategy, "_build_entry", return_value=marker
                ) as build:
                    result = self.strategy.on_candle(candle, ctx)
        weekly_calls = [
            c for c in build.call_args_list if c.kwargs.get("sleeve") == "weekly"
        ]
        daily_calls = [
            c for c in build.call_args_list if c.kwargs.get("sleeve") == "daily"
        ]
        self.assertFalse(weekly_calls)
        self.assertFalse(daily_calls)
        self.assertIsNone(result)

    def test_weekly_enters_only_on_4h_close(self):
        """Aligned HTF on closed 4H opens weekly; same state on 1H does not."""
        ctx = SimpleNamespace(position_store=_PositionStore())
        self.strategy._confirmed_direction = 1
        self.strategy._current_supertrend = 65000.0
        self.strategy._confirmed_4h_direction = 1
        self.strategy._confirmed_1d_direction = 1
        self.strategy._current_4h_supertrend = 64700.0
        marker = object()
        h1 = {
            "symbol": "BTCUSD",
            "timeframe": "60",
            "timestamp": datetime(2026, 7, 27, 14, 0, tzinfo=timezone.utc),
            "close": 65000,
            "supertrend": 65000,
            "supertrend_direction": 1,
        }
        h4 = {
            "symbol": "BTCUSD",
            "timeframe": "4h",
            "timestamp": datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc),
            "close": 65000,
            "supertrend": 64700,
            "supertrend_direction": 1,
            "supertrend_4h": 64700,
        }
        with patch.object(self.strategy, "_bar_is_fully_closed", return_value=True):
            with patch.object(
                self.strategy,
                "_refresh_htf_state",
                return_value={"4h": (1, 64700.0), "1d": (1, 63500.0)},
            ):
                with patch.object(
                    self.strategy, "_trail_open_sleeves", return_value=[]
                ):
                    with patch.object(
                        self.strategy, "_build_entry", return_value=marker
                    ) as build:
                        self.assertIsNone(self.strategy.on_candle(h1, ctx))
                        self.assertFalse(
                            any(
                                c.kwargs.get("sleeve") == "weekly"
                                for c in build.call_args_list
                            )
                        )
                        result = self.strategy.on_candle(h4, ctx)
        weekly_calls = [
            c for c in build.call_args_list if c.kwargs.get("sleeve") == "weekly"
        ]
        self.assertEqual(len(weekly_calls), 1)
        self.assertEqual(weekly_calls[0].kwargs["reason"], "weekly_htf_aligned")
        self.assertIn(marker, result or [])

    def test_weekly_expiry_shifts_when_dte_le_2(self):
        s = DirectionalOptionSelling()
        # Wednesday 2026-07-15 → this week's Friday is 17 Jul (DTE=2) → shift to 24 Jul.
        candle = {
            "symbol": "BTCUSD",
            "timestamp": datetime(2026, 7, 15, 6, 0, tzinfo=timezone.utc),
            "close": 65000,
        }
        ctx = SimpleNamespace()
        code = s._weekly_expiry_for_entry(candle, ctx)
        self.assertEqual(code, "240726")
        self.assertEqual(ctx.selected_expiry, "240726")

    def test_dual_sleeve_weekly_and_daily_can_both_enter(self):
        """1H flip opens daily; closed 4H with HTF align opens weekly."""
        ctx = SimpleNamespace(position_store=_PositionStore())
        self.strategy._confirmed_direction = -1
        self.strategy._current_supertrend = 64000.0
        h1 = {
            "symbol": "BTCUSD",
            "timeframe": "60",
            "timestamp": datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc),
            "close": 65000,
            "supertrend": 64000,
            "supertrend_direction": 1,
        }
        h4 = {
            "symbol": "BTCUSD",
            "timeframe": "4h",
            "timestamp": datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc),
            "close": 65000,
            "supertrend": 63500,
            "supertrend_direction": 1,
            "supertrend_4h": 63500,
        }
        weekly_marker = object()
        daily_marker = object()

        def _build(candle, ctx, direction, **kwargs):
            if kwargs.get("sleeve") == "weekly":
                return weekly_marker
            return daily_marker

        with patch.object(
            self.strategy,
            "_refresh_htf_state",
            return_value={"4h": (1, 63500.0), "1d": (1, 62000.0)},
        ):
            with patch.object(
                self.strategy, "_bar_is_fully_closed", return_value=True
            ):
                with patch.object(
                    self.strategy, "_trail_open_sleeves", return_value=[]
                ):
                    with patch.object(
                        self.strategy, "_build_entry", side_effect=_build
                    ) as build:
                        r1 = self.strategy.on_candle(h1, ctx)
                        r4 = self.strategy.on_candle(h4, ctx)
        self.assertEqual(r1, [daily_marker])
        self.assertEqual(r4, [weekly_marker])
        sleeves = [c.kwargs.get("sleeve") for c in build.call_args_list]
        self.assertEqual(sleeves, ["daily", "weekly"])
        self.assertEqual(build.call_args_list[0].kwargs["reason"], "one_h_signal")
        self.assertEqual(build.call_args_list[1].kwargs["reason"], "weekly_htf_aligned")

    def test_latest_closed_st_from_df(self):
        s = DirectionalOptionSelling()
        rows = []
        start = pd.Timestamp("2026-07-01", tz="UTC")
        price = 60000.0
        direction = 1
        for i in range(40):
            o = price
            c = price + (80 if direction > 0 else -80)
            h = max(o, c) + 50
            l = min(o, c) - 50
            rows.append(
                {
                    "timestamp": start + pd.Timedelta(hours=4 * i),
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": 1,
                }
            )
            price = c
        df = pd.DataFrame(rows)
        as_of = start + pd.Timedelta(hours=4 * 39 + 4)  # last bar closed
        snap = s._latest_closed_st_from_df(
            df, timeframe="4h", as_of_utc=as_of
        )
        self.assertIsNotNone(snap)
        direction, st, bar_open = snap
        self.assertIn(direction, (1, -1))
        self.assertGreater(st, 0)
        self.assertEqual(bar_open, start + pd.Timedelta(hours=4 * 39))


    def test_daily_blocked_when_htf_not_both_green(self):
        s = DirectionalOptionSelling()
        candle = {
            "symbol": "BTCUSD",
            "timestamp": datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc),
            "close": 65000,
        }
        ctx = SimpleNamespace()
        with patch.object(
            s,
            "_htf_snapshot",
            return_value={"4h": (1, 64000.0), "1d": (-1, 63000.0)},
        ):
            self.assertFalse(s._daily_htf_aligned(1, ctx, candle))
        with patch.object(
            s,
            "_htf_snapshot",
            return_value={"4h": (1, 64000.0), "1d": (1, 63000.0)},
        ):
            self.assertTrue(s._daily_htf_aligned(1, ctx, candle))
            self.assertFalse(s._daily_htf_aligned(-1, ctx, candle))

    def test_sleeve_inferred_from_structure_id(self):
        s = DirectionalOptionSelling()
        self.assertEqual(
            s._sleeve_from_structure_id(
                "DirectionalOptionSelling:BTCUSD:weekly:2026-07-21:PE:dc7343a8"
            ),
            "weekly",
        )
        self.assertEqual(
            s._sleeve_from_structure_id(
                "DirectionalOptionSelling:BTCUSD:monthly:2026-07-27:PE:abc12345"
            ),
            "monthly",
        )
        self.assertEqual(
            s._normalize_sleeve("daily", "DirectionalOptionSelling:BTCUSD:weekly:x:PE:abc"),
            "weekly",
        )
        self.assertEqual(
            s._normalize_sleeve(
                "daily", "DirectionalOptionSelling:BTCUSD:monthly:x:CE:def"
            ),
            "monthly",
        )

    def test_entry_qty_lots_monthly_independent(self):
        s = DirectionalOptionSelling()
        self.assertEqual(s._entry_qty_lots("monthly", "BTCUSD"), 50)
        self.assertEqual(s._entry_qty_lots("weekly", "BTCUSD"), 50)
        self.assertEqual(s._entry_qty_lots("monthly", "ETHUSD"), 10)
        self.assertEqual(s._entry_qty_lots("weekly", "ETHUSD"), 10)
        s.order_qty_lots_weekly = 50
        s.order_qty_lots_monthly = 25
        self.assertEqual(s._entry_qty_lots("monthly"), 25)
        self.assertEqual(s._entry_qty_lots("MONTHLY"), 25)
        self.assertEqual(s._entry_qty_lots("weekly"), 50)
        self.assertTrue(s._uses_4h_trail("monthly"))

    def test_monthly_enters_only_on_1d_flip(self):
        """Steady 1D does not enter monthly; 1D flip does."""
        ctx = SimpleNamespace(position_store=_PositionStore())
        self.strategy._confirmed_direction = 1
        self.strategy._current_supertrend = 65000.0
        self.strategy._confirmed_1d_direction = -1
        self.strategy._confirmed_4h_direction = 1
        self.strategy._current_4h_supertrend = 64800.0
        candle = {
            "symbol": "BTCUSD",
            "timestamp": datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc),
            "bucket_ts": datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc).timestamp(),
            "timeframe": "60",
            "close": 65200.0,
            "supertrend": 65000.0,
            "supertrend_direction": 1,
        }
        marker = object()
        with patch.object(self.strategy, "_bar_is_fully_closed", return_value=True):
            with patch.object(
                self.strategy,
                "_refresh_htf_state",
                return_value={"4h": (1, 64800.0), "1d": (-1, 64000.0)},
            ):
                # Same 1D as prev → no monthly.
                with patch.object(
                    self.strategy, "_build_entry", return_value=None
                ) as build:
                    self.strategy.on_candle(candle, ctx)
                monthly_calls = [
                    c
                    for c in build.call_args_list
                    if c.kwargs.get("sleeve") == "monthly"
                ]
                self.assertEqual(monthly_calls, [])

            # Flip 1D -1 → +1
            self.strategy._confirmed_1d_direction = -1
            with patch.object(
                self.strategy,
                "_refresh_htf_state",
                side_effect=lambda *_a, **_k: (
                    setattr(self.strategy, "_confirmed_1d_direction", 1)
                    or {"4h": (1, 64800.0), "1d": (1, 64000.0)}
                ),
            ):
                with patch.object(
                    self.strategy, "_build_entry", return_value=marker
                ) as build:
                    with patch.object(
                        self.strategy, "_open_main_positions", return_value=[]
                    ):
                        result = self.strategy.on_candle(candle, ctx)
        monthly_calls = [
            c for c in build.call_args_list if c.kwargs.get("sleeve") == "monthly"
        ]
        self.assertEqual(len(monthly_calls), 1)
        self.assertEqual(monthly_calls[0].kwargs.get("reason"), "one_d_signal")
        self.assertEqual(monthly_calls[0].args[2], 1)  # direction
        self.assertIn(marker, result or [])

    def test_monthly_expiry_rolls_when_dte_low(self):
        s = DirectionalOptionSelling()
        # 25 Jul 2026 is a Saturday; last Friday July = 31 Jul → DTE=6 < 7 → Aug.
        candle = {
            "timestamp": datetime(2026, 7, 25, 6, 0, tzinfo=timezone.utc),
        }
        ctx = SimpleNamespace()
        with patch.object(s, "monthlyExpiry", return_value="310726"):
            code = s._monthly_expiry_for_entry(candle, ctx)
        # Next month last Friday Aug 2026 = 28 Aug → 280826
        self.assertEqual(code, "280826")
        self.assertEqual(ctx.selected_expiry, "280826")

    def test_fallback_meta_uses_symbol_and_structure_id(self):
        s = DirectionalOptionSelling()
        s._current_4h_supertrend = 64497.31
        s._current_supertrend = 65059.55
        inst = SimpleNamespace(
            trading_symbol="P-BTC-64000-240726",
            option_type="",  # missing after reconcile
            strike=0,
            expiry="",
        )
        pos = SimpleNamespace(
            structure_id="DirectionalOptionSelling:BTCUSD:weekly:2026-07-21:PE:dc7343a8",
            instrument=inst,
            avg_price=384.0,
            tag="MAIN",
            net_qty=-2,
            strategy="DirectionalOptionSelling",
        )
        meta = s._fallback_meta_from_position(pos)
        self.assertIsNotNone(meta)
        self.assertEqual(meta.sleeve, "weekly")
        self.assertEqual(meta.direction, 1)
        self.assertEqual(meta.option_type, "PE")
        self.assertEqual(meta.strike, 64000.0)
        self.assertEqual(meta.expiry, "240726")
        self.assertAlmostEqual(meta.supertrend, 64497.31)

    def test_restore_state_without_strategy_meta(self):
        s = DirectionalOptionSelling()
        s._current_4h_supertrend = 64497.31
        inst = SimpleNamespace(
            trading_symbol="P-BTC-64000-240726",
            option_type="",
            strike=64000.0,
            expiry="240726",
        )
        pos = SimpleNamespace(
            structure_id="DirectionalOptionSelling:BTCUSD:weekly:2026-07-21:PE:dc7343a8",
            instrument=inst,
            avg_price=384.0,
            tag="MAIN",
            net_qty=-2,
            strategy="DirectionalOptionSelling",
        )
        pm = SimpleNamespace(
            positions={"P-BTC-64000-240726": pos},
            get_position_metadata=lambda _sym: {},
        )

        def _hydrate_1h(_candle=None):
            s._confirmed_direction = -1
            s._current_supertrend = 66202.19
            return 66202.19

        with patch.object(s, "_hydrate_1h_from_history", side_effect=_hydrate_1h):
            with patch.object(s, "_hydrate_4h_from_history", return_value=65659.07):
                s.restore_state_on_startup(pm)
        meta = s._meta_by_structure_id[pos.structure_id]
        self.assertEqual(meta.sleeve, "weekly")
        self.assertEqual(meta.direction, 1)
        # 1H signal state from hydrate — not weekly meta (+1).
        self.assertEqual(s._confirmed_direction, -1)
        self.assertAlmostEqual(s._current_supertrend, 66202.19)

    def test_restart_seeds_1h_not_weekly_meta_so_daily_flip_fires(self):
        """Regression: weekly PE restore must not hide a later 1H -1→+1 daily entry."""
        ctx = SimpleNamespace(position_store=_PositionStore())
        # After restart hydrate: last closed 1H was still bearish.
        self.strategy._confirmed_direction = -1
        self.strategy._current_supertrend = 66202.19
        candle = {
            "symbol": "BTCUSD",
            "timestamp": datetime(2026, 7, 22, 16, 0, tzinfo=timezone.utc),  # 21:30 IST open
            "bucket_ts": datetime(2026, 7, 22, 16, 0, tzinfo=timezone.utc).timestamp(),
            "timeframe": "60",
            "close": 66207.0,
            "supertrend": 65625.87,
            "supertrend_direction": 1,
        }
        marker = object()
        with patch.object(self.strategy, "_bar_is_fully_closed", return_value=True):
            with patch.object(
                self.strategy,
                "_refresh_htf_state",
                return_value={"4h": (1, 65659.07), "1d": (1, 63278.86)},
            ):
                with patch.object(
                    self.strategy, "_build_entry", return_value=marker
                ) as build:
                    result = self.strategy.on_candle(candle, ctx)
        daily_calls = [
            c for c in build.call_args_list if c.kwargs.get("sleeve") == "daily"
        ]
        self.assertEqual(len(daily_calls), 1)
        self.assertEqual(daily_calls[0].kwargs["reason"], "one_h_signal")
        self.assertEqual(daily_calls[0].args[2], 1)
        self.assertIn(marker, result or [])

    def test_build_entry_skips_duplicate_trading_symbol(self):
        s = DirectionalOptionSelling()
        # Mis-tagged as daily after restart, but same Friday contract still open.
        open_pos = SimpleNamespace(
            tag="MAIN",
            net_qty=-2,
            structure_id="DirectionalOptionSelling:BTCUSD:daily:2026-07-21:PE:old",
            instrument=SimpleNamespace(
                trading_symbol="P-BTC-64000-240726",
                option_type="PE",
                strike=64000.0,
                expiry="240726",
            ),
            avg_price=384.0,
            strategy="DirectionalOptionSelling",
        )
        ctx = SimpleNamespace(
            position_store=_PositionStore([open_pos]),
            exchange="DELTA",
            instrument_store=SimpleNamespace(
                intent_creation_details=lambda *a, **k: SimpleNamespace()
            ),
        )
        candle = {
            "symbol": "BTCUSD",
            "timestamp": datetime(2026, 7, 21, 5, 0, tzinfo=timezone.utc),
            "close": 65500,
            "supertrend": 65000,
            "supertrend_4h": 64497.31,
        }
        with patch.object(s, "_weekly_htf_aligned", return_value=True):
            with patch.object(s, "_weekly_expiry_for_entry", return_value="240726"):
                with patch.object(
                    s,
                    "_select_contract",
                    return_value=(
                        64000.0,
                        303.0,
                        pd.Series({"symbol": "P-BTC-64000-240726"}),
                        "240726",
                    ),
                ):
                    intent = s._build_entry(
                        candle,
                        ctx,
                        1,
                        reason="weekly_htf_aligned",
                        sleeve="weekly",
                    )
        self.assertIsNone(intent)

    def test_ensure_meta_reasserts_weekly_sleeve_from_sid(self):
        from core.strategies.crypto.DirectionalOptionSelling.DirectionalOptionSelling import (
            _PositionMeta,
        )

        s = DirectionalOptionSelling()
        sid = "DirectionalOptionSelling:BTCUSD:weekly:2026-07-21:PE:dc7343a8"
        # Simulate previously mis-tagged daily fallback already cached.
        s._meta_by_structure_id[sid] = _PositionMeta(
            symbol="BTCUSD",
            direction=-1,
            option_type="CE",
            supertrend=65059.55,
            strike=64000.0,
            expiry="240726",
            entry_premium=384.0,
            entry_reason="restored",
            sleeve="daily",
        )
        pos = SimpleNamespace(structure_id=sid, instrument=None, intent_id=None)
        meta = s._ensure_meta(pos, SimpleNamespace(intent_store=None))
        self.assertEqual(meta.sleeve, "weekly")

    def test_4h_bar_trails_weekly_and_may_enter_when_flat(self):
        """Closed 4H BarClosed trails weekly SL; does not run 1H flip logic."""
        from core.strategies.crypto.DirectionalOptionSelling.DirectionalOptionSelling import (
            _PositionMeta,
        )

        instrument = SimpleNamespace(
            option_type="PE",
            expiry="240726",
            strike=64000,
            trading_symbol="P-BTC-64000-240726",
            product_id=99,
        )
        position = SimpleNamespace(
            tag="MAIN",
            net_qty=-2,
            structure_id="DirectionalOptionSelling:BTCUSD:weekly:trail-4h",
            instrument=instrument,
            intent_id="e1",
            avg_price=303,
        )
        ctx = SimpleNamespace(
            position_store=_PositionStore([position]),
            intent_store=None,
            order_router=SimpleNamespace(broker=SimpleNamespace()),
        )
        from core.strategies.crypto.DirectionalOptionSelling.constants import (
            SL_MODE_INDEX,
        )

        sid = position.structure_id
        self.strategy._meta_by_structure_id[sid] = _PositionMeta(
            symbol="BTCUSD",
            direction=1,
            option_type="PE",
            supertrend=64497.31,
            strike=64000,
            expiry="240726",
            entry_premium=303,
            entry_reason="weekly_htf_aligned",
            sleeve="weekly",
            sl_mode=SL_MODE_INDEX,
        )
        # Stale seed that previously blocked trail after restart.
        self.strategy._current_4h_supertrend = 64497.31
        self.strategy._confirmed_direction = 1
        self.strategy._current_supertrend = 66257.55
        candle = {
            "symbol": "BTCUSD",
            "timeframe": "4h",
            "timestamp": datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc),
            "close": 66655.0,
            "supertrend": 65659.07,
            "supertrend_direction": 1,
            "supertrend_4h": 65659.07,
        }
        with patch.object(
            self.strategy, "_bar_is_fully_closed", return_value=True
        ):
            with patch.object(
                self.strategy,
                "_resolve_weekly_trail_st",
                return_value=65659.07,
            ):
                with patch.object(
                    self.strategy, "_modify_broker_trail_sl", return_value=True
                ) as modify:
                    with patch.object(
                        self.strategy,
                        "_refresh_htf_state",
                        return_value={"4h": (1, 65659.07), "1d": (1, 64000.0)},
                    ):
                        with patch.object(
                            self.strategy, "_build_entry", return_value=object()
                        ) as build:
                            result = self.strategy.on_candle(candle, ctx)
        # Open weekly already → no new ENTRY; trail still runs.
        self.assertIsNone(result)
        build.assert_not_called()
        modify.assert_called_once()
        self.assertAlmostEqual(modify.call_args.kwargs["supertrend"], 65659.07)
        self.assertAlmostEqual(
            self.strategy._meta_by_structure_id[sid].supertrend, 65659.07
        )
        # 1H ST must stay untouched by the 4H trail path.
        self.assertAlmostEqual(self.strategy._current_supertrend, 66257.55)

    def test_restore_does_not_seed_stale_4h_from_meta(self):
        from core.strategies.crypto.DirectionalOptionSelling.DirectionalOptionSelling import (
            _PositionMeta,
        )

        s = DirectionalOptionSelling()
        sid = "DirectionalOptionSelling:BTCUSD:weekly:2026-07-21:PE:f4fa3a09"
        s._meta_by_structure_id[sid] = _PositionMeta(
            symbol="BTCUSD",
            direction=1,
            option_type="PE",
            supertrend=64497.31,
            strike=64000,
            expiry="240726",
            entry_premium=303,
            entry_reason="weekly_htf_aligned",
            sleeve="weekly",
        )
        pos = SimpleNamespace(
            net_qty=-2,
            strategy="DirectionalOptionSelling",
            tag="MAIN",
            structure_id=sid,
            instrument=SimpleNamespace(trading_symbol="P-BTC-64000-240726"),
            intent_id=None,
        )
        pm = SimpleNamespace(
            positions={"P-BTC-64000-240726": pos},
            get_position_metadata=lambda _s: {
                "strategy_meta": {
                    "symbol": "BTCUSD",
                    "direction": 1,
                    "option_type": "PE",
                    "supertrend": 64497.31,
                    "strike": 64000,
                    "expiry": "240726",
                    "entry_premium": 303,
                    "entry_reason": "weekly_htf_aligned",
                    "sleeve": "weekly",
                }
            },
        )
        with patch.object(s, "_hydrate_4h_from_history") as hyd:
            hyd.side_effect = lambda *_a, **_k: (
                setattr(s, "_current_4h_supertrend", 65659.07) or 65659.07
            )
            s.restore_state_on_startup(pm, intent_store=None)
        hyd.assert_called()
        self.assertAlmostEqual(s._current_4h_supertrend, 65659.07)
        # Must not remain stuck at entry meta ST.
        self.assertNotAlmostEqual(s._current_4h_supertrend, 64497.31)

    def test_entry_qty_lots_differs_by_sleeve(self):
        s = DirectionalOptionSelling()
        s.order_qty_lots_weekly = 5
        s.order_qty_lots_daily = 2
        self.assertEqual(s._entry_qty_lots("weekly"), 5)
        self.assertEqual(s._entry_qty_lots("daily"), 2)
        self.assertEqual(s._entry_qty_lots(""), 2)
        self.assertEqual(s._entry_qty_lots("WEEKLY"), 5)

    def test_symbol_config_btc_vs_eth_and_runtime_isolation(self):
        from core.strategies.crypto.DirectionalOptionSelling.constants import (
            symbol_config,
        )

        s = DirectionalOptionSelling()
        self.assertIn("ETHUSD", s.underlying_symbols)
        self.assertEqual(symbol_config("BTCUSD")["option_root"], "BTC")
        self.assertEqual(symbol_config("ETHUSD")["option_root"], "ETH")
        self.assertGreater(
            float(symbol_config("BTCUSD")["min_premium_usd"]),
            float(symbol_config("ETHUSD")["min_premium_usd"]),
        )
        self.assertEqual(s._entry_qty_lots("weekly", "BTCUSD"), 50)
        self.assertEqual(s._entry_qty_lots("weekly", "ETHUSD"), 10)
        self.assertEqual(
            s._trail_sl_level(1, 100.0, symbol="ETHUSD"),
            100.0 - float(symbol_config("ETHUSD")["trail_sl_points"]),
        )
        s._bind_symbol("ETHUSD")
        s._confirmed_direction = 1
        s._bind_symbol("BTCUSD")
        s._confirmed_direction = -1
        s._bind_symbol("ETHUSD")
        self.assertEqual(s._confirmed_direction, 1)
        s._bind_symbol("BTCUSD")
        self.assertEqual(s._confirmed_direction, -1)
        self.assertTrue(s.should_evaluate(
            {
                "symbol": "ETHUSD",
                "timestamp": datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc),
                "bucket_ts": datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc).timestamp(),
                "timeframe": "60",
            }
        ))

    def test_sleeve_entry_enable_flags(self):
        import importlib

        # Module that defines ENABLE_* flags (not the strategy class).
        mod = importlib.import_module(
            "core.strategies.crypto.DirectionalOptionSelling.DirectionalOptionSelling"
        )
        prev_w = mod.ENABLE_WEEKLY_TRADES
        prev_mo = mod.ENABLE_MONTHLY_TRADES
        prev_d = mod.ENABLE_INTRADAY_TRADES
        prev_m = mod.ENABLE_MORNING_0DTE_TRADES
        try:
            mod.ENABLE_WEEKLY_TRADES = True
            mod.ENABLE_MONTHLY_TRADES = True
            mod.ENABLE_INTRADAY_TRADES = True
            mod.ENABLE_MORNING_0DTE_TRADES = True
            self.assertTrue(DirectionalOptionSelling._sleeve_entries_enabled("weekly"))
            self.assertTrue(DirectionalOptionSelling._sleeve_entries_enabled("monthly"))
            self.assertTrue(DirectionalOptionSelling._sleeve_entries_enabled("daily"))
            self.assertTrue(DirectionalOptionSelling._sleeve_entries_enabled("morning"))

            mod.ENABLE_WEEKLY_TRADES = False
            mod.ENABLE_MONTHLY_TRADES = False
            mod.ENABLE_INTRADAY_TRADES = False
            mod.ENABLE_MORNING_0DTE_TRADES = False
            self.assertFalse(DirectionalOptionSelling._sleeve_entries_enabled("weekly"))
            self.assertFalse(DirectionalOptionSelling._sleeve_entries_enabled("monthly"))
            self.assertFalse(DirectionalOptionSelling._sleeve_entries_enabled("daily"))
            self.assertFalse(DirectionalOptionSelling._sleeve_entries_enabled("morning"))
            s = DirectionalOptionSelling()
            with patch.object(s, "_open_main_positions", return_value=[]):
                self.assertIsNone(
                    s._build_entry(
                        {"timestamp": pd.Timestamp("2026-07-21 12:00", tz="Asia/Kolkata")},
                        SimpleNamespace(),
                        1,
                        reason="weekly_htf_aligned",
                        sleeve="weekly",
                    )
                )
                self.assertIsNone(
                    s._build_entry(
                        {"timestamp": pd.Timestamp("2026-07-21 12:00", tz="Asia/Kolkata")},
                        SimpleNamespace(),
                        1,
                        reason="one_d_signal",
                        sleeve="monthly",
                    )
                )
                self.assertIsNone(
                    s._build_entry(
                        {"timestamp": pd.Timestamp("2026-07-21 12:00", tz="Asia/Kolkata")},
                        SimpleNamespace(),
                        1,
                        reason="one_h_signal",
                        sleeve="daily",
                    )
                )
                self.assertIsNone(
                    s._build_entry(
                        {"timestamp": pd.Timestamp("2026-07-22 08:30", tz="Asia/Kolkata")},
                        SimpleNamespace(),
                        1,
                        reason="morning_830",
                        sleeve="morning",
                    )
                )
            # Intraday on / morning off / weekly off / monthly on → daily + monthly.
            mod.ENABLE_WEEKLY_TRADES = False
            mod.ENABLE_MONTHLY_TRADES = True
            mod.ENABLE_INTRADAY_TRADES = True
            mod.ENABLE_MORNING_0DTE_TRADES = False
            self.assertFalse(DirectionalOptionSelling._sleeve_entries_enabled("weekly"))
            self.assertTrue(DirectionalOptionSelling._sleeve_entries_enabled("monthly"))
            self.assertTrue(DirectionalOptionSelling._sleeve_entries_enabled("daily"))
            self.assertFalse(DirectionalOptionSelling._sleeve_entries_enabled("morning"))
            # Morning on alone.
            mod.ENABLE_MORNING_0DTE_TRADES = True
            self.assertTrue(DirectionalOptionSelling._sleeve_entries_enabled("morning"))
        finally:
            mod.ENABLE_WEEKLY_TRADES = prev_w
            mod.ENABLE_MONTHLY_TRADES = prev_mo
            mod.ENABLE_INTRADAY_TRADES = prev_d
            mod.ENABLE_MORNING_0DTE_TRADES = prev_m

    def test_entry_qty_lots_morning(self):
        s = DirectionalOptionSelling()
        s.order_qty_lots_morning = 10
        self.assertEqual(s._entry_qty_lots("morning"), 10)
        self.assertEqual(s._entry_qty_lots("MORNING"), 10)

    def test_is_morning_entry_slot_0830_ist(self):
        s = DirectionalOptionSelling()
        # 60m bucket open 07:30 IST → close 08:30 IST (03:00 UTC open → 03:00+1h).
        # Prefer bucket_ts: open at 02:00 UTC = 07:30 IST, close = 08:30 IST.
        candle = {
            "timestamp": datetime(2026, 7, 22, 2, 0, tzinfo=timezone.utc),
            "bucket_ts": datetime(2026, 7, 22, 2, 0, tzinfo=timezone.utc).timestamp(),
            "timeframe": "60",
        }
        self.assertTrue(s._is_morning_entry_slot(candle))
        other = {
            "timestamp": datetime(2026, 7, 22, 3, 0, tzinfo=timezone.utc),
            "bucket_ts": datetime(2026, 7, 22, 3, 0, tzinfo=timezone.utc).timestamp(),
            "timeframe": "60",
        }
        self.assertFalse(s._is_morning_entry_slot(other))

    def test_morning_entry_fires_at_0830_without_htf(self):
        """08:30 closed bar enters morning sleeve on 1H ST; skips daily HTF filter."""
        ctx = SimpleNamespace(position_store=_PositionStore())
        self.strategy._confirmed_direction = 1
        self.strategy._current_supertrend = 65000.0
        # Bar open 07:30 IST / close 08:30 IST.
        candle = {
            "symbol": "BTCUSD",
            "timestamp": datetime(2026, 7, 22, 2, 0, tzinfo=timezone.utc),
            "bucket_ts": datetime(2026, 7, 22, 2, 0, tzinfo=timezone.utc).timestamp(),
            "timeframe": "60",
            "close": 65100.0,
            "supertrend": 65000.0,
            "supertrend_direction": 1,
        }
        marker = object()
        with patch.object(self.strategy, "_bar_is_fully_closed", return_value=True):
            with patch.object(
                self.strategy,
                "_refresh_htf_state",
                return_value={"4h": (-1, 64000.0), "1d": (-1, 63000.0)},
            ):
                with patch.object(
                    self.strategy, "_build_entry", return_value=marker
                ) as build:
                    with patch.object(
                        self.strategy, "_daily_htf_aligned", return_value=False
                    ) as daily_htf:
                        result = self.strategy.on_candle(candle, ctx)
        morning_calls = [
            c for c in build.call_args_list if c.kwargs.get("sleeve") == "morning"
        ]
        self.assertEqual(len(morning_calls), 1)
        self.assertEqual(morning_calls[0].kwargs["reason"], "morning_830")
        self.assertEqual(morning_calls[0].kwargs["min_dte"], 0)
        self.assertEqual(morning_calls[0].args[2], 1)
        # Morning path must not depend on daily HTF alignment.
        daily_htf.assert_not_called()
        self.assertIn(marker, result or [])
        # Once-per-day: second eval same day does not rebuild.
        with patch.object(self.strategy, "_bar_is_fully_closed", return_value=True):
            with patch.object(
                self.strategy,
                "_refresh_htf_state",
                return_value={"4h": (-1, 64000.0), "1d": (-1, 63000.0)},
            ):
                with patch.object(
                    self.strategy, "_build_entry", return_value=marker
                ) as build2:
                    self.strategy.on_candle(candle, ctx)
        morning2 = [
            c for c in build2.call_args_list if c.kwargs.get("sleeve") == "morning"
        ]
        self.assertEqual(len(morning2), 0)

    def test_morning_build_entry_skips_daily_htf(self):
        from dataclasses import dataclass

        @dataclass
        class _Intent:
            intent_id: str = "i1"
            qty: int = 1

        s = DirectionalOptionSelling()
        s._current_supertrend = 65000.0
        candle = {
            "timestamp": pd.Timestamp("2026-07-22 08:30", tz="Asia/Kolkata"),
            "supertrend": 65000.0,
            "close": 65100.0,
        }
        with patch.object(s, "_open_main_positions", return_value=[]):
            with patch.object(s, "_open_main_has_expiry", return_value=False):
                with patch.object(s, "_daily_htf_aligned") as daily_htf:
                    with patch.object(
                        s,
                        "_select_contract",
                        return_value=(
                            64000.0,
                            200.0,
                            pd.Series({"symbol": "P-BTC-64000-220726"}),
                            "220726",
                        ),
                    ) as select:
                        with patch.object(
                            s,
                            "delta_option_trading_symbol",
                            return_value="P-BTC-64000-220726",
                        ):
                            with patch.object(
                                s, "_open_main_trading_symbols", return_value=set()
                            ):
                                with patch.object(
                                    s,
                                    "map_instrument_to_intent",
                                    return_value=_Intent(),
                                ):
                                    ctx = SimpleNamespace(
                                        exchange="DELTA",
                                        instrument_store=SimpleNamespace(
                                            intent_creation_details=MagicMock(
                                                return_value=SimpleNamespace(
                                                    trading_symbol="P-BTC-64000-220726"
                                                )
                                            )
                                        ),
                                        selected_expiry=None,
                                    )
                                    intent = s._build_entry(
                                        candle,
                                        ctx,
                                        1,
                                        reason="morning_830",
                                        sleeve="morning",
                                    )
        self.assertIsNotNone(intent)
        daily_htf.assert_not_called()
        self.assertEqual(intent.qty, 10)
        self.assertEqual(select.call_args.kwargs.get("target_expiry"), "220726")
        sid = next(iter(s._meta_by_structure_id))
        self.assertEqual(s._meta_by_structure_id[sid].sleeve, "morning")


if __name__ == "__main__":
    unittest.main()
