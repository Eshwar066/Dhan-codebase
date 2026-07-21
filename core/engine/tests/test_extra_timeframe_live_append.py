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

    def test_evaluate_parallel_includes_extra_timeframe_owner(self):
        """4h BarClosed must evaluate DOS (extra_timeframes), not only primary TF==4h."""
        eng = LiveEngine.__new__(LiveEngine)
        dos = SimpleNamespace(
            name="DirectionalOptionSelling",
            timeframe="60",
            extra_timeframes=["4h", "1d"],
            applies_to_symbol=lambda s: s == "BTCUSD",
            should_evaluate=lambda _c: True,
            eval_signal_log_message=None,
            get_warmup_period=lambda: 5,
        )
        eng.strategies = [dos]
        eng.strategy = dos
        eng.strategy_eval_modes = {}
        eng.strategy_timeout_seconds = 0.2
        eng.engine_logger = None
        eng._is_scheduled_strategy = lambda *_a, **_k: False
        eng._strategy_task_queues = {"DirectionalOptionSelling": MagicMock()}
        eng._ensure_strategy_worker = MagicMock()
        eng._recent_candles_for_strategy = MagicMock(return_value=[])
        eng._safe_queue_put = MagicMock(return_value=False)
        eng._enrich_candle_for_strategy = MagicMock(side_effect=lambda s, c, **k: dict(c))

        results = eng._evaluate_strategies_parallel(
            {"symbol": "BTCUSD", "timeframe": "4h", "close": 1},
            timeframe="4h",
            already_enriched=True,
        )
        eng._ensure_strategy_worker.assert_called_once_with(dos)
        eng._safe_queue_put.assert_called_once()
        self.assertEqual(results, [])

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

    def test_restore_strategies_after_reconcile_all_strategies(self):
        """Non-primary strategies (e.g. DOS) must receive restore + ctx."""
        eng = LiveEngine.__new__(LiveEngine)
        primary = SimpleNamespace(name="BTCZeroDTE")
        dos_calls = []

        def dos_restore(pm, intent_store=None, ctx=None):
            dos_calls.append({"pm": pm, "intent_store": intent_store, "ctx": ctx})

        dos = SimpleNamespace(
            name="DirectionalOptionSelling",
            restore_state_on_startup=dos_restore,
        )
        eng.strategies = [primary, dos]
        eng.strategy = primary
        eng.position_manager = SimpleNamespace(positions={})
        eng.order_router = object()
        eng.engine_logger = None

        intent_store = object()
        eng._restore_strategies_after_reconcile(intent_store)

        self.assertEqual(len(dos_calls), 1)
        self.assertIs(dos_calls[0]["ctx"].order_router, eng.order_router)
        self.assertIs(dos_calls[0]["pm"], eng.position_manager)
        self.assertIs(dos_calls[0]["intent_store"], intent_store)


if __name__ == "__main__":
    unittest.main()
