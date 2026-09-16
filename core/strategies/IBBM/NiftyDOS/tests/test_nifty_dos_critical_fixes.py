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


if __name__ == "__main__":
    unittest.main()
