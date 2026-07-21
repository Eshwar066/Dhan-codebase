"""Tests for extra_timeframes live_append routing (e.g. DOS 60 + 4h/1d)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.engine.indicator_manager import IndicatorManager
from core.engine.live_engine import LiveEngine


class TestExtraTimeframeLiveAppend(unittest.TestCase):
    def test_strategy_owns_primary_and_extra(self):
        s = SimpleNamespace(timeframe="60", extra_timeframes=["4h", "1d"])
        self.assertTrue(IndicatorManager._strategy_owns_timeframe(s, "60"))
        self.assertTrue(IndicatorManager._strategy_owns_timeframe(s, "4h"))
        self.assertTrue(IndicatorManager._strategy_owns_timeframe(s, "1d"))
        self.assertFalse(IndicatorManager._strategy_owns_timeframe(s, "5"))

    def test_resolve_enrich_timeframe_prefers_owned_bar_tf(self):
        s = SimpleNamespace(timeframe="60", extra_timeframes=["4h", "1d"])
        self.assertEqual(
            IndicatorManager._resolve_enrich_timeframe(s, {}, "4h"),
            "4h",
        )
        self.assertEqual(
            IndicatorManager._resolve_enrich_timeframe(s, {"timeframe": "1d"}, None),
            "1d",
        )
        self.assertEqual(
            IndicatorManager._resolve_enrich_timeframe(s, {}, "5"),
            "60",
        )
        self.assertEqual(
            IndicatorManager._resolve_enrich_timeframe(s, {}, None),
            "60",
        )

    def test_timeframe_to_seconds_handles_4h_and_1d(self):
        self.assertEqual(IndicatorManager._timeframe_to_seconds("4h"), 14400)
        self.assertEqual(IndicatorManager._timeframe_to_seconds("1d"), 86400)
        self.assertEqual(IndicatorManager._timeframe_to_seconds("60"), 3600)

    def test_candle_strategy_for_matches_extra_timeframes(self):
        eng = LiveEngine.__new__(LiveEngine)
        dos = SimpleNamespace(
            name="DirectionalOptionSelling",
            timeframe="60",
            extra_timeframes=["4h", "1d"],
            applies_to_symbol=lambda s: s == "BTCUSD",
        )
        other = SimpleNamespace(
            name="Other",
            timeframe="5",
            extra_timeframes=[],
            applies_to_symbol=lambda s: s == "BTCUSD",
        )
        eng.strategies = [dos, other]
        eng.strategy = dos
        eng.strategy_eval_modes = {}
        eng._is_scheduled_strategy = lambda *_a, **_k: False

        self.assertIs(eng._candle_strategy_for("BTCUSD", "60"), dos)
        self.assertIs(eng._candle_strategy_for("BTCUSD", "4h"), dos)
        self.assertIs(eng._candle_strategy_for("BTCUSD", "1d"), dos)
        self.assertIs(eng._candle_strategy_for("BTCUSD", "5"), other)

    def test_enrich_skips_unowned_explicit_timeframe(self):
        mgr = IndicatorManager(MagicMock())
        strategy = SimpleNamespace(timeframe="60", extra_timeframes=[], name="X")
        out = mgr.enrich_candle_for_strategy(
            strategy,
            {"symbol": "BTCUSD", "close": 1},
            candle_bucket_fn=lambda c: None,
            timeframe="4h",
        )
        self.assertEqual(out.get("close"), 1)

    def test_enrich_passes_extra_tf_into_append_path(self):
        import pandas as pd

        mgr = IndicatorManager(MagicMock())
        strategy = SimpleNamespace(
            name="DirectionalOptionSelling",
            timeframe="60",
            extra_timeframes=["4h", "1d"],
            supertrend_length=16,
            supertrend_factor=1.5,
            prepare_indicators=lambda df: df,
            persisted_indicator_keys=lambda: [
                "supertrend",
                "supertrend_direction",
            ],
            get_warmup_period=lambda: 0,
        )
        ts = pd.Timestamp("2026-07-20 12:00:00", tz="UTC")
        base_df = pd.DataFrame(
            [
                {
                    "timestamp": ts,
                    "open": 1.0,
                    "high": 1.0,
                    "low": 1.0,
                    "close": 1.0,
                    "volume": 0,
                    "symbol": "BTCUSD",
                    "exchange": "DELTA",
                    "supertrend": 1.0,
                    "supertrend_direction": 1.0,
                }
            ]
        )
        mgr._base_candle_state["BTCUSD|4h"] = {
            "df": base_df,
            "window": 50,
            "last_bucket": None,
            "update_seq": 0,
            "continuity_checked": True,
            "delta_resanitized": True,
        }
        mgr._rsi_seeded_streams.add(("BTCUSD", "4h"))
        mgr._live_exchange = "DELTA"

        candle = {
            "symbol": "BTCUSD",
            "exchange": "DELTA",
            "timestamp": ts + pd.Timedelta(hours=4),
            "bucket_ts": int((ts + pd.Timedelta(hours=4)).timestamp()),
            "open": 2.0,
            "high": 2.0,
            "low": 2.0,
            "close": 2.0,
            "volume": 0,
        }

        with patch.object(mgr, "_append_rsi_history_log") as append_mock, patch.object(
            mgr, "_finalize_delta_base_df"
        ), patch.object(
            mgr, "_sanitize_delta_ohlc_row", side_effect=lambda row, **_k: row
        ), patch.object(
            mgr, "_compute_supertrend_columns", side_effect=lambda df, **_k: df
        ):
            mgr.enrich_candle_for_strategy(
                strategy,
                candle,
                candle_bucket_fn=lambda c: c.get("bucket_ts"),
                allow_live_persist=True,
                timeframe="4h",
            )
            self.assertTrue(append_mock.called)
            self.assertEqual(append_mock.call_args.kwargs["tf"], "4h")


if __name__ == "__main__":
    unittest.main()
