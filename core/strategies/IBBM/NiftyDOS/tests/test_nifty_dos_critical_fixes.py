"""Regression tests for NiftyDOS critical live-trading fixes."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

from core.strategies.IBBM.NiftyDOS.NiftyDOS import NiftyDOS
from core.strategies.IndiaMktMixins import IST
from run.config import RunMode


class NiftyDosCriticalFixTests(unittest.TestCase):
    def setUp(self):
        self.strategy = NiftyDOS()
        self.strategy._structure_main_entry_price["NiftyDOS:NIFTY:SUPER_BULLISH"] = 90.0
        self.strategy._structure_hedge_entry_price["NiftyDOS:NIFTY:SUPER_BULLISH"] = 5.0
        self.strategy._structure_type["NiftyDOS:NIFTY:SUPER_BULLISH"] = "PUT"

    def test_get_trading_symbol_fallback_uses_filtered2(self):
        df = pd.DataFrame(
            {
                "SEM_CUSTOM_SYMBOL": ["NIFTY-OTHER"],
                "SEM_TRADING_SYMBOL": ["NIFTY25SEP24000PE"],
                "SEM_EXPIRY_DATE": [pd.Timestamp("2025-09-25")],
                "SEM_OPTION_TYPE": ["PE"],
                "SEM_STRIKE_PRICE": [24000.0],
                "SEM_SMST_SECURITY_ID": [12345],
                "SEM_LOT_UNITS": [65],
            }
        )
        sym, sec_id, lot = self.strategy.get_trading_symbol_from_instrument_df(
            df, 24000, "PE", date(2025, 9, 25)
        )
        self.assertEqual(sym, "NIFTY25SEP24000PE")
        self.assertEqual(sec_id, 12345)
        self.assertEqual(lot, 65)

    def test_on_position_exit_keeps_tracking_and_sl_flag_for_sl(self):
        sid = "NiftyDOS:NIFTY:SUPER_BULLISH"
        self.strategy._sl_hit_structure[sid] = "PUT"
        pos = SimpleNamespace(
            tag="MAIN",
            net_qty=-65,
            structure_id=sid,
            instrument=SimpleNamespace(
                strike=24000,
                option_type="PE",
                expiry=date(2025, 9, 25),
            ),
        )
        candle = {"symbol": "NIFTY", "timestamp": datetime(2025, 9, 15, 10, 0)}
        ctx = SimpleNamespace(position_store=SimpleNamespace(get_hedge_for=lambda _p: None))

        intents = self.strategy.on_position_exit(pos, candle, ctx)
        self.assertTrue(intents)
        self.assertIn(sid, self.strategy._structure_main_entry_price)
        self.assertIn(sid, self.strategy._pending_exit_structure_ids)
        self.assertIn(sid, self.strategy._sl_hit_structure)
        self.assertNotIn(sid, self.strategy._reentry_after_close)

    def test_on_position_exit_queues_tp_reentry_after_close(self):
        sid = "NiftyDOS:NIFTY:SUPER_BULLISH"
        self.strategy._tp_hit_pending[sid] = "PUT"
        pos = SimpleNamespace(
            tag="MAIN",
            net_qty=-65,
            structure_id=sid,
            instrument=SimpleNamespace(
                strike=24000,
                option_type="PE",
                expiry=date(2025, 9, 25),
            ),
        )
        candle = {"symbol": "NIFTY", "timestamp": datetime(2025, 9, 15, 10, 0)}
        ctx = SimpleNamespace(position_store=SimpleNamespace(get_hedge_for=lambda _p: None))

        self.strategy.on_position_exit(pos, candle, ctx)
        self.assertIn(sid, self.strategy._reentry_after_close)
        self.assertEqual(self.strategy._reentry_after_close[sid]["reason"], "TP")
        self.assertIn(sid, self.strategy._structure_main_entry_price)

    def test_finalize_pending_exits_clears_tracking_when_flat(self):
        sid = "NiftyDOS:NIFTY:SUPER_BULLISH"
        self.strategy._pending_exit_structure_ids.add(sid)
        self.strategy._sl_hit_structure[sid] = "PUT"
        candle = {"symbol": "NIFTY", "timestamp": datetime(2025, 9, 15, 10, 0)}
        ctx = SimpleNamespace(
            position_store=SimpleNamespace(
                get_open_positions=MagicMock(return_value=[])
            )
        )

        self.strategy._finalize_pending_exits(candle, ctx)
        self.assertNotIn(sid, self.strategy._pending_exit_structure_ids)
        self.assertNotIn(sid, self.strategy._structure_main_entry_price)
        self.assertIn(sid, self.strategy._sl_hit_structure)

    def test_pending_reentries_skip_sl_reason(self):
        sid = "NiftyDOS:NIFTY:SUPER_BULLISH"
        self.strategy._reentry_after_close[sid] = {
            "type": "PUT",
            "reason": "SL",
            "original_strike": 24000,
            "original_option_type": "PE",
        }
        candle = {"symbol": "NIFTY", "timestamp": datetime(2025, 9, 15, 10, 0)}
        ctx = SimpleNamespace(
            position_store=SimpleNamespace(
                get_open_positions=MagicMock(return_value=[])
            )
        )

        with patch.object(self.strategy, "_attempt_sl_reentry") as sl_mock:
            out = self.strategy._check_and_execute_pending_reentries(candle, ctx)
        sl_mock.assert_not_called()
        self.assertIsNone(out)

    def test_on_candle_rollover_is_disabled(self):
        out = self.strategy.on_candle_rollover([], {"timestamp": datetime(2025, 9, 15)}, None)
        self.assertEqual(out, [])

    def test_is_945am_with_bucket_ts_and_utc_naive_timestamp(self):
        """Live engine: bucket_ts=9:15 IST open, timestamp=03:45 UTC naive."""
        bucket = int(pd.Timestamp("2026-09-15 09:15:00", tz=IST).timestamp())
        candle = {
            "timestamp": datetime(2026, 9, 15, 3, 45),
            "bucket_ts": bucket,
            "timeframe": "30",
        }
        self.assertTrue(self.strategy._is_915am(candle))
        self.assertTrue(self.strategy._is_945am(candle))

    def test_is_945am_false_when_timestamp_misread_as_ist(self):
        """Old bug: localizing UTC naive timestamp as IST shifted close to 4:15."""
        bucket = int(pd.Timestamp("2026-09-15 09:15:00", tz=IST).timestamp())
        candle = {
            "timestamp": datetime(2026, 9, 15, 3, 45),
            "bucket_ts": bucket,
            "timeframe": "30",
        }
        close_ts = self.strategy._candle_close_ts_ist(candle)
        self.assertEqual(close_ts.hour, 9)
        self.assertEqual(close_ts.minute, 45)

    def test_is_945am_fallback_when_timestamp_is_close_time(self):
        candle = {
            "timestamp": datetime(2026, 9, 15, 4, 15),
            "timeframe": "30",
        }
        ts_ist = pd.Timestamp(candle["timestamp"]).tz_localize("UTC").tz_convert(IST)
        self.assertEqual(ts_ist.hour, 9)
        self.assertEqual(ts_ist.minute, 45)
        self.assertTrue(self.strategy._is_945am(candle))

    def test_is_945am_accepts_close_within_3min_buffer(self):
        """Delayed feed may stamp close between 9:46–9:48 IST."""
        for utc_minute, ist_minute in ((16, 46), (17, 47), (18, 48)):
            candle = {
                "timestamp": datetime(2026, 9, 15, 4, utc_minute),
                "timeframe": "30",
            }
            self.assertTrue(
                self.strategy._is_945am(candle),
                f"expected 9:{ist_minute:02d} IST close in 9:45 entry window",
            )

    def test_is_945am_rejects_close_after_buffer(self):
        candle = {
            "timestamp": datetime(2026, 9, 15, 4, 19),  # 9:49 IST
            "timeframe": "30",
        }
        self.assertFalse(self.strategy._is_945am(candle))

    def test_is_945am_rejects_second_30m_bar(self):
        bucket = int(pd.Timestamp("2026-09-15 09:45:00", tz=IST).timestamp())
        candle = {
            "timestamp": datetime(2026, 9, 15, 4, 45),
            "bucket_ts": bucket,
            "timeframe": "30",
        }
        self.assertFalse(self.strategy._is_945am(candle))

    def test_candle_ts_ist_is_timezone_aware(self):
        bucket = int(pd.Timestamp("2026-09-15 09:15:00", tz=IST).timestamp())
        candle = {
            "timestamp": datetime(2026, 9, 15, 3, 45),
            "bucket_ts": bucket,
            "timeframe": "30",
        }
        ts = self.strategy._candle_ts_ist(candle)
        self.assertIsNotNone(ts.tzinfo)
        self.assertEqual(
            pd.Timestamp(ts).tz_convert(IST).hour,
            9,
        )
        self.assertEqual(pd.Timestamp(ts).tz_convert(IST).minute, 15)

    def test_create_order_intent_coerces_utc_naive_to_ist(self):
        inst = SimpleNamespace(lot_size=65, trading_symbol="NIFTY-PE", custom_symbol="NIFTY")
        with patch.object(
            NiftyDOS.__bases__[0],
            "create_order_intent",
            return_value=SimpleNamespace(candle_ts=None),
        ) as mock_super:
            self.strategy.create_order_intent(
                inst=inst,
                side="SELL",
                qty=1,
                price=90.0,
                order_type="LIMIT",
                strategy=self.strategy.name,
                candle_ts=datetime(2026, 9, 15, 3, 45),
                structure_id="sid",
                tag="MAIN",
                symbol="NIFTY",
                action="ENTRY",
            )
        passed_ts = mock_super.call_args.kwargs["candle_ts"]
        self.assertIsNotNone(pd.Timestamp(passed_ts).tzinfo)

    def test_sync_tracking_log_handles_missing_hedge_entry(self):
        pos = SimpleNamespace(
            strategy="NiftyDOS",
            tag="MAIN",
            structure_id="NiftyDOS:NIFTY:SUPER_BULLISH",
            net_qty=-65,
            avg_price=90.0,
            instrument=SimpleNamespace(
                option_type="PE",
                trading_symbol="NIFTY-PE",
            ),
        )
        ctx = SimpleNamespace(
            symbol="NIFTY",
            position_store=SimpleNamespace(
                get_open_positions=MagicMock(return_value=[pos]),
                get_hedge_for=MagicMock(return_value=None),
            ),
        )

        restored = self.strategy.sync_tracking_from_broker(ctx)
        self.assertEqual(restored, 1)

    @staticmethod
    def _candle_30m(open_h, open_m, bullish: bool):
        bucket = int(pd.Timestamp(f"2026-09-15 {open_h:02d}:{open_m:02d}:00", tz=IST).timestamp())
        return {
            "symbol": "NIFTY",
            "timeframe": "30",
            "bucket_ts": bucket,
            "timestamp": datetime(2026, 9, 15, open_h, open_m),
            "supertrend_is_bullish": bullish,
            "close": 25000.0,
        }

    @patch("core.strategies.IBBM.NiftyDOS.NiftyDOS.RUN_MODE", RunMode.BACKTEST)
    @patch.object(NiftyDOS, "_is_event_no_trade_day", return_value=False)
    def test_should_evaluate_false_when_supertrend_unchanged(self, _event_mock):
        strategy = NiftyDOS()
        c1 = self._candle_30m(10, 15, True)
        self.assertFalse(strategy.should_evaluate(c1))
        self.assertIsNone(strategy.eval_signal_log_message(c1))

        c2 = self._candle_30m(10, 45, True)
        self.assertFalse(strategy.should_evaluate(c2))
        self.assertIsNone(strategy.eval_signal_log_message(c2))

    @patch("core.strategies.IBBM.NiftyDOS.NiftyDOS.RUN_MODE", RunMode.BACKTEST)
    @patch.object(NiftyDOS, "_is_event_no_trade_day", return_value=False)
    def test_should_evaluate_true_on_supertrend_flip(self, _event_mock):
        strategy = NiftyDOS()
        strategy.should_evaluate(self._candle_30m(10, 15, True))
        flip_candle = self._candle_30m(10, 45, False)
        self.assertTrue(strategy.should_evaluate(flip_candle))
        msg = strategy.eval_signal_log_message(flip_candle)
        self.assertIsNotNone(msg)
        self.assertIn("ST_FLIP", msg)

    @patch("core.strategies.IBBM.NiftyDOS.NiftyDOS.RUN_MODE", RunMode.BACKTEST)
    @patch.object(NiftyDOS, "_is_event_no_trade_day", return_value=False)
    def test_should_evaluate_true_at_945_entry(self, _event_mock):
        strategy = NiftyDOS()
        candle = self._candle_30m(9, 15, True)
        self.assertTrue(strategy.should_evaluate(candle))
        msg = strategy.eval_signal_log_message(candle)
        self.assertIn("9:45_ENTRY", msg or "")

    @patch("core.strategies.IBBM.NiftyDOS.NiftyDOS.RUN_MODE", RunMode.BACKTEST)
    @patch.object(NiftyDOS, "_is_event_no_trade_day", return_value=False)
    def test_should_evaluate_true_for_sl_reentry(self, _event_mock):
        strategy = NiftyDOS()
        strategy._sl_hit_structure["NiftyDOS:NIFTY:SUPER_BULLISH"] = "PUT"
        candle = self._candle_30m(11, 15, True)
        self.assertTrue(strategy.should_evaluate(candle))
        self.assertIn("SL_REENTRY", strategy.eval_signal_log_message(candle) or "")

    @patch("core.strategies.IBBM.NiftyDOS.NiftyDOS.RUN_MODE", RunMode.BACKTEST)
    @patch.object(NiftyDOS, "_is_event_no_trade_day", return_value=False)
    def test_should_evaluate_5min_only_for_monitoring_or_reentry(self, _event_mock):
        strategy = NiftyDOS()
        candle = {"symbol": "NIFTY", "timeframe": "5", "timestamp": datetime(2026, 9, 15, 10, 5)}
        self.assertFalse(strategy.should_evaluate(candle))

        strategy._structure_main_entry_price["sid"] = 90.0
        self.assertTrue(strategy.should_evaluate(candle))
        self.assertIsNone(strategy.eval_signal_log_message(candle))

    def test_structure_flat_ignores_other_strategy_positions(self):
        strategy = NiftyDOS()
        sid = "NiftyDOS:NIFTY:SUPER_BULLISH"
        other_main = SimpleNamespace(
            strategy="Leaps",
            tag="MAIN",
            structure_id="Leaps:NIFTY:RSI",
            net_qty=-65,
            instrument=SimpleNamespace(custom_symbol="NIFTY"),
        )
        candle = {"symbol": "NIFTY", "timestamp": datetime(2026, 9, 15, 10, 0)}
        ctx = SimpleNamespace(
            position_store=SimpleNamespace(
                get_open_positions=MagicMock(return_value=[other_main])
            )
        )
        self.assertTrue(strategy._is_structure_flat_at_broker(sid, candle, ctx))

    def test_structure_still_open_only_for_same_strategy(self):
        strategy = NiftyDOS()
        sid = "NiftyDOS:NIFTY:SUPER_BULLISH"
        own_main = SimpleNamespace(
            strategy="NiftyDOS",
            tag="MAIN",
            structure_id=sid,
            net_qty=-65,
            instrument=SimpleNamespace(custom_symbol="NIFTY"),
        )
        candle = {"symbol": "NIFTY", "timestamp": datetime(2026, 9, 15, 10, 0)}
        ctx = SimpleNamespace(
            position_store=SimpleNamespace(
                get_open_positions=MagicMock(return_value=[own_main])
            )
        )
        self.assertTrue(strategy._structure_still_open_at_broker(sid, candle, ctx))

    def test_has_open_main_ignores_other_strategies(self):
        strategy = NiftyDOS()
        other_main = SimpleNamespace(
            strategy="Leaps",
            tag="MAIN",
            structure_id="Leaps:NIFTY:RSI",
            net_qty=-65,
            instrument=SimpleNamespace(custom_symbol="NIFTY"),
        )
        candle = {"symbol": "NIFTY", "timestamp": datetime(2026, 9, 15, 10, 0)}
        ctx = SimpleNamespace(
            position_store=SimpleNamespace(
                get_open_positions=MagicMock(return_value=[other_main])
            )
        )
        self.assertFalse(strategy._has_open_main_for_strategy(candle, ctx))

    @patch("core.strategies.IBBM.NiftyDOS.NiftyDOS.RUN_MODE", RunMode.LIVE)
    def test_build_entry_intents_sets_metadata_on_frozen_intent(self):
        strategy = NiftyDOS()
        candle = {
            "symbol": "NIFTY",
            "timestamp": datetime(2026, 9, 17, 3, 45),
            "bucket_ts": 1789616700,
            "close": 23252.3,
            "timeframe": "30",
        }
        inst = SimpleNamespace(
            trading_symbol="NIFTY25SEP23000PE",
            custom_symbol="NIFTY-23000-PE",
            strike=23000,
            option_type="PE",
            expiry=date(2026, 9, 24),
        )
        ctx = SimpleNamespace(
            exchange="NSE",
            instrument_store=SimpleNamespace(
                intent_creation_details=MagicMock(return_value=inst)
            ),
            position_store=SimpleNamespace(
                has_open_structure=MagicMock(return_value=False)
            ),
            intent_store=SimpleNamespace(
                has_pending_intent=MagicMock(return_value=False),
                has_entry_for_structure=MagicMock(return_value=False),
            ),
        )
        row = pd.Series({"PE_LTP": 95.0})
        with patch.object(
            strategy,
            "find_strike_in_premium_range",
            return_value=(23000, 95.0, row),
        ), patch.object(
            strategy,
            "_resolve_main_expiry",
            return_value=date(2026, 9, 24),
        ), patch.object(
            strategy,
            "create_hedge_intent",
        ) as hedge_mock:
            def _fake_hedge(parent_sell_intent, candle, ctx):
                return strategy.map_instrument_to_intent(
                    inst=inst,
                    strike_row=row,
                    strategy=strategy.name,
                    side="BUY",
                    structure_id=parent_sell_intent.structure_id,
                    candle_ts=strategy._candle_ts_ist(candle),
                    tag="HEDGE",
                    symbol=candle["symbol"],
                    action="ENTRY",
                    parent_intent_id=parent_sell_intent.intent_id,
                )

            hedge_mock.side_effect = _fake_hedge
            out = strategy._build_entry_intents(
                candle,
                ctx,
                "PUT",
                structure_id="NiftyDOS:NIFTY:SUPER_BULLISH_945",
                regime="SUPER_BULLISH_945",
            )

        self.assertIsNotNone(out)
        self.assertEqual(len(out), 2)
        sell_intent, hedge_intent = out[1], out[0]
        self.assertIsNotNone(sell_intent.metadata_extras)
        self.assertEqual(hedge_intent.metadata_extras, sell_intent.metadata_extras)
        self.assertEqual(sell_intent.metadata_extras["regime"], "SUPER_BULLISH_945")
        self.assertEqual(sell_intent.metadata_extras["structure_type"], "PUT")


class TestChainFetchGuard(unittest.TestCase):
    def test_rejects_stale_cache_when_next_weekly_differs(self):
        strategy = NiftyDOS()
        ctx = SimpleNamespace(selected_expiry=date(2026, 9, 29))
        stale = {
            "expiry": date(2026, 9, 22),
            "chain": pd.DataFrame({"Strike Price": [23000], "PE LTP": [30.0]}),
        }
        self.assertFalse(
            strategy._may_use_cached_chain_fallback("NEXT_WEEKLY", stale, ctx)
        )

    def test_allows_stale_cache_when_expiry_matches(self):
        strategy = NiftyDOS()
        ctx = SimpleNamespace(selected_expiry=date(2026, 9, 29))
        chain = {
            "expiry": date(2026, 9, 29),
            "chain": pd.DataFrame({"Strike Price": [23000], "PE LTP": [95.0]}),
        }
        self.assertTrue(
            strategy._may_use_cached_chain_fallback("NEXT_WEEKLY", chain, ctx)
        )

    def test_log_entry_skipped_writes_engine_event(self):
        strategy = NiftyDOS()
        strategy._last_chain_fetch_requested_expiry = date(2026, 9, 29)
        strategy._last_chain_fetch_response_expiry = date(2026, 9, 22)
        engine_logger = MagicMock()
        ctx = SimpleNamespace(
            order_router=SimpleNamespace(engine_logger=engine_logger)
        )
        strategy._log_entry_skipped(ctx, "no OTM strike", option_type="PUT")
        engine_logger.log.assert_called_once()
        args = engine_logger.log.call_args
        self.assertEqual(args[0][0], "entry_skipped")
        self.assertIn("requested_expiry=2026-09-29", args[0][1])
        self.assertIn("chain_expiry=2026-09-22", args[0][1])
        self.assertEqual(args[1]["requested_expiry"], "2026-09-29")
        self.assertEqual(args[1]["chain_expiry"], "2026-09-22")


class TestExitExpiry(unittest.TestCase):
    def test_csv_hint_prefers_saved_expiry_over_compact_symbol(self):
        from core.orderExecution.position_manager import PositionManager

        expiry, lookup = PositionManager._contract_hint_from_open_row(
            {
                "strategy_meta": (
                    '{"expiry": "2026-10-13", '
                    '"custom_symbol": "NIFTY 13 OCT 22350 PUT"}'
                )
            },
            "NIFTY-Oct2026-22350-PE",
        )
        self.assertEqual(expiry, "2026-10-13")
        self.assertEqual(lookup, "NIFTY 13 OCT 22350 PUT")

    def test_exit_rebinds_monthly_symbol_to_saved_weekly_expiry(self):
        strategy = NiftyDOS()
        weekly = SimpleNamespace(
            trading_symbol="NIFTY-Oct2026-22350-PE",
            custom_symbol="NIFTY 13 OCT 22350 PUT",
            exchange="NSE",
            expiry=date(2026, 10, 13),
            option_type="PE",
            strike=22350,
        )
        monthly = SimpleNamespace(
            trading_symbol="NIFTY-Oct2026-22350-PE",
            custom_symbol="NIFTY 27 OCT 22350 PUT",
            exchange="NSE",
            expiry=date(2026, 10, 27),
            option_type="PE",
            strike=22350,
        )
        store = MagicMock()
        store.intent_creation_details.return_value = weekly
        pos = SimpleNamespace(instrument=monthly, net_qty=-65, structure_id="sid", tag="MAIN")
        ctx = SimpleNamespace(
            instrument_store=store,
            exchange="NSE",
            position_store=SimpleNamespace(
                get_position_metadata=lambda _s: {
                    "strategy_meta": {
                        "expiry": "2026-10-13",
                        "custom_symbol": "NIFTY 13 OCT 22350 PUT",
                    }
                },
                get_hedge_for=lambda _p: None,
            ),
        )
        rebound = strategy._exit_instrument(pos, ctx)
        self.assertIs(rebound, weekly)
        store.intent_creation_details.assert_called_once()
        self.assertEqual(store.intent_creation_details.call_args[0][2], "2026-10-13")


class TestStructureSlCapital(unittest.TestCase):
    def test_sl_is_3_5_percent_of_margin_per_lot_not_unit_qty(self):
        strategy = NiftyDOS()
        strategy.margin_per_lot = 50000
        strategy.put_sl_pct = 3.5
        strategy.put_tp_pct = 3.7
        sid = "NiftyDOS:NIFTY:SUPER_BULLISH_945"
        strategy._structure_type[sid] = "PUT"
        strategy._structure_main_entry_price[sid] = 84.95
        strategy._structure_hedge_entry_price[sid] = 23.55
        main = SimpleNamespace(
            tag="MAIN",
            structure_id=sid,
            net_qty=-65,
            avg_price=84.95,
            instrument=SimpleNamespace(
                trading_symbol="NIFTY-Oct2026-22350-PE",
                lot_size=1,
                strike=22350,
                option_type="PE",
                expiry=date(2026, 10, 13),
                instrument_id=111,
            ),
        )
        hedge = SimpleNamespace(
            tag="HEDGE",
            structure_id=sid,
            net_qty=65,
            avg_price=23.55,
            instrument=SimpleNamespace(
                trading_symbol="NIFTY-Oct2026-21850-PE",
                lot_size=1,
                strike=21850,
                option_type="PE",
                instrument_id=222,
            ),
        )
        ctx = SimpleNamespace(position_store=SimpleNamespace(get_hedge_for=lambda _p: hedge))

        capital = strategy._get_structure_capital(sid, main, ctx)
        self.assertEqual(capital, 50000)
        self.assertAlmostEqual(capital * 3.5 / 100.0, 1750)

        # Loss of 1800 on the short leg crosses the 1750 stop. Mark 112.65:
        # (84.95 - 112.65) * 65 = -1800.50, hedge unchanged so hedge pnl 0.
        with patch.object(
            strategy,
            "_get_current_premium",
            side_effect=lambda pos, candle, ctx: 112.65 if pos is main else 23.55,
        ):
            self.assertEqual(strategy._check_tp_sl(main, {"symbol": "NIFTY"}, ctx), "SL")

        with patch.object(
            strategy,
            "_get_current_premium",
            side_effect=lambda pos, candle, ctx: 90.0 if pos is main else 23.55,
        ):
            # (84.95 - 90) * 65 = -328.25, inside the 1750 stop
            self.assertIsNone(strategy._check_tp_sl(main, {"symbol": "NIFTY"}, ctx))


class TestStructurePnl(unittest.TestCase):
    def test_pnl_uses_fills_and_live_ltp_not_signal_quote(self):
        strategy = NiftyDOS()
        sid = "NiftyDOS:NIFTY:SUPER_BULLISH_945"
        strategy._structure_main_entry_price[sid] = 87.15
        strategy._structure_hedge_entry_price[sid] = 0.0
        strategy._last_option_chain = {
            "chain": pd.DataFrame(
                {
                    "Strike Price": [22350.0, 21850.0],
                    "PE Ask": [87.10, 24.10],
                    "PE LTP": [99.0, 30.0],
                }
            )
        }
        main = SimpleNamespace(
            structure_id=sid,
            net_qty=-65,
            avg_price=84.95,
            instrument=SimpleNamespace(
                strike=22350,
                option_type="PE",
                expiry=date(2026, 10, 13),
                instrument_id=111,
            ),
        )
        hedge = SimpleNamespace(
            structure_id=sid,
            net_qty=65,
            avg_price=23.55,
            instrument=SimpleNamespace(
                strike=21850,
                option_type="PE",
                expiry=date(2026, 10, 13),
                instrument_id=222,
            ),
        )
        feed = MagicMock()
        feed.ltp.return_value = {
            "status": "success",
            "data": {
                "NSE_FNO": {
                    "111": {"last_price": 80.0},
                    "222": {"last_price": 20.0},
                }
            },
        }
        broker = SimpleNamespace(api=SimpleNamespace(_source=SimpleNamespace(_marketfeed=feed)))
        ctx = SimpleNamespace(
            order_router=SimpleNamespace(broker=broker),
            option_chain_service=MagicMock(),
            position_store=SimpleNamespace(get_hedge_for=lambda _p: hedge),
        )

        with patch("core.strategies.IBBM.NiftyDOS.NiftyDOS.RUN_MODE", RunMode.LIVE):
            pnl = strategy._calculate_structure_pnl(main, hedge, {"symbol": "NIFTY"}, ctx)

        # short (84.95 - 80) * 65 + long (20 - 23.55) * 65
        self.assertAlmostEqual(pnl, (84.95 - 80.0) * 65 + (20.0 - 23.55) * 65)
        self.assertEqual(strategy._structure_main_entry_price[sid], 84.95)
        self.assertEqual(strategy._structure_hedge_entry_price[sid], 23.55)
        ctx.option_chain_service.get_chain.assert_not_called()
        self.assertEqual(feed.ltp.call_count, 2)


class TestMarginAndTelegram(unittest.TestCase):
    def test_5min_monitor_does_not_repeat_945_signal(self):
        strategy = NiftyDOS()
        strategy._pending_eval_reason = "9:45_ENTRY"
        strategy._structure_main_entry_price["sid"] = 84.95
        candle = {
            "symbol": "NIFTY",
            "timeframe": "5",
            "timestamp": datetime(2026, 10, 5, 10, 5),
            "close": 22600,
        }
        self.assertIsNone(strategy.eval_signal_log_message(candle))

    def test_5min_capital_uses_locked_margin_not_api(self):
        strategy = NiftyDOS()
        sid = "NiftyDOS:NIFTY:SUPER_BULLISH_945"
        strategy._structure_margin_used[sid] = 60870.94
        main = SimpleNamespace(
            net_qty=-65,
            instrument=SimpleNamespace(
                trading_symbol="NIFTY-Oct2026-22350-PE",
                lot_size=1,
            ),
        )
        tradehull = SimpleNamespace(margin_calculator_multi=MagicMock())
        ctx = SimpleNamespace(
            order_router=SimpleNamespace(
                broker=SimpleNamespace(
                    api=SimpleNamespace(_source=SimpleNamespace(tsl=tradehull))
                )
            )
        )
        with patch.object(strategy, "calculate_margin_dhan") as quote:
            capital = strategy._get_structure_capital(sid, main, ctx)
        self.assertEqual(capital, 60870.94)
        quote.assert_not_called()
        tradehull.margin_calculator_multi.assert_not_called()

    def test_margin_api_runs_once_when_entry_is_built(self):
        strategy = NiftyDOS()
        inst = lambda sym, strike: SimpleNamespace(
            trading_symbol=sym,
            lot_size=1,
            strike=strike,
            option_type="PE",
            expiry=date(2026, 10, 13),
        )
        sell = SimpleNamespace(qty=1, price=84.95, instrument=inst("NIFTY-Oct2026-22350-PE", 22350))
        hedge = SimpleNamespace(qty=1, price=23.55, instrument=inst("NIFTY-Oct2026-21850-PE", 21850))
        tradehull = SimpleNamespace(margin_calculator_multi=MagicMock(), Dhan=None)
        ctx = SimpleNamespace(
            order_router=SimpleNamespace(
                broker=SimpleNamespace(
                    api=SimpleNamespace(_source=SimpleNamespace(tsl=tradehull))
                )
            )
        )
        with patch.object(
            strategy, "calculate_margin_dhan", return_value={"final_margin": 60870.94}
        ) as quote:
            first = strategy._quote_structure_margin_once("sid", sell, hedge, ctx)
            second = strategy._quote_structure_margin_once("sid", sell, hedge, ctx)
        self.assertEqual(first, 60870.94)
        self.assertEqual(second, 60870.94)
        quote.assert_called_once()
        self.assertEqual(quote.call_args.kwargs["main_qty"], 65)
        self.assertEqual(quote.call_args.kwargs["hedge_qty"], 65)


if __name__ == "__main__":
    unittest.main()
