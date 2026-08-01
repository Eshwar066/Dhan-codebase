"""Unit tests for 4H liquidity zones + Gautham 1m sweep entry."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd

from core.strategies.crypto.LiquiditySweepStrategy.four_hour_liquidity import (
    FourHourLiquidityBook,
)
from core.strategies.crypto.LiquiditySweepStrategy.gautham_liquidity_sweep import (
    GauthamLiquiditySweep,
)
from core.strategies.crypto.LiquiditySweepStrategy.LiquiditySweepStrategy import (
    LiquiditySweepStrategy,
)


def _c(
    *,
    symbol="BTCUSD",
    o=100.0,
    h=110.0,
    l=90.0,
    c=105.0,
    ts="2026-07-22T10:00:00Z",
    timeframe="1",
    bucket=None,
    **extra,
):
    out = {
        "symbol": symbol,
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "timestamp": ts,
        "timeframe": timeframe,
        "bucket_ts": bucket if bucket is not None else 1,
        "exchange": "DELTA",
    }
    out.update(extra)
    return out


def _seed_swing_high_120(book: FourHourLiquidityBook, symbol: str = "BTCUSD") -> None:
    """5×4H bars → confirmed swing high at 120 (left=2, right=2)."""
    bars = [
        (100, 105, 98, 102, "2026-07-21T00:00:00Z", "2026-07-21 05:30"),
        (102, 108, 100, 104, "2026-07-21T04:00:00Z", "2026-07-21 09:30"),
        (104, 120, 103, 110, "2026-07-21T08:00:00Z", "2026-07-21 13:30"),  # swing
        (110, 115, 105, 108, "2026-07-21T12:00:00Z", "2026-07-21 17:30"),
        (108, 112, 104, 106, "2026-07-21T16:00:00Z", "2026-07-21 21:30"),
    ]
    for o, h, l, c, ts, ist in bars:
        book.on_4h_close(
            symbol,
            _c(
                o=o,
                h=h,
                l=l,
                c=c,
                timeframe="4h",
                ts=ts,
                candle_timestamp_ist=ist,
            ),
        )



class TestFourHourLiquidityBook(unittest.TestCase):
    def test_prev_4h_zones_and_1m_high_sweep(self):
        book = FourHourLiquidityBook(persist=False)
        book.on_4h_close(
            "BTCUSD",
            _c(o=100, h=120, l=95, c=110, timeframe="4h", ts="2026-07-22T08:00:00Z"),
        )
        snap = book.snapshot("BTCUSD")
        self.assertIn(120.0, snap["highs"])
        self.assertIn(95.0, snap["lows"])

        # Wick above 120, close back below → SHORT
        hit = book.detect_1m_sweep(
            "BTCUSD",
            _c(o=118, h=121, l=117, c=119, ts="2026-07-22T10:01:00Z"),
        )
        self.assertIsNotNone(hit)
        side, zone = hit
        self.assertEqual(side, "SHORT")
        self.assertEqual(zone.price, 120.0)

    def test_1m_low_sweep(self):
        book = FourHourLiquidityBook(persist=False)
        book.on_4h_close(
            "BTCUSD",
            _c(o=100, h=120, l=95, c=110, timeframe="4h"),
        )
        hit = book.detect_1m_sweep(
            "BTCUSD",
            _c(o=97, h=98, l=94, c=96),
        )
        self.assertIsNotNone(hit)
        side, zone = hit
        self.assertEqual(side, "LONG")
        self.assertEqual(zone.price, 95.0)

    def test_weekend_4h_bars_not_used_as_levels(self):
        """Sat/Sun 4H OHLC must not become prev_4h or swing_4h levels (IST)."""
        book = FourHourLiquidityBook(persist=False)
        # Friday 2026-07-24
        book.on_4h_close(
            "BTCUSD",
            _c(
                o=100,
                h=110,
                l=90,
                c=105,
                timeframe="4h",
                ts="2026-07-24T08:00:00Z",
                candle_timestamp_ist="2026-07-24 13:30",
            ),
        )
        snap = book.snapshot("BTCUSD")
        self.assertIn(110.0, snap["highs"])
        self.assertIn(90.0, snap["lows"])

        # Saturday extreme high — must not become a level; keep Fri as prev_4h.
        # OHLC chosen so it does not also sweep Friday's levels.
        book.on_4h_close(
            "BTCUSD",
            _c(
                o=105,
                h=150,
                l=91,
                c=140,
                timeframe="4h",
                ts="2026-07-25T08:00:00Z",
                candle_timestamp_ist="2026-07-25 13:30",
            ),
        )
        snap = book.snapshot("BTCUSD")
        self.assertNotIn(150.0, snap["highs"])
        self.assertIn(110.0, snap["highs"])
        self.assertIn(90.0, snap["lows"])
        st = book._state("BTCUSD")
        self.assertTrue(
            all("2026-07-25" not in z.bar_key for z in st.high_zones + st.low_zones)
        )

        # Sunday extreme low — same rule
        book.on_4h_close(
            "BTCUSD",
            _c(
                o=140,
                h=145,
                l=60,
                c=70,
                timeframe="4h",
                ts="2026-07-26T08:00:00Z",
                candle_timestamp_ist="2026-07-26 13:30",
            ),
        )
        snap = book.snapshot("BTCUSD")
        self.assertNotIn(60.0, snap["lows"])
        self.assertNotIn(145.0, snap["highs"])
        st = book._state("BTCUSD")
        self.assertTrue(
            all(
                "2026-07-25" not in z.bar_key and "2026-07-26" not in z.bar_key
                for z in st.high_zones + st.low_zones
            )
        )

    def test_mark_consumed_removes_zone(self):
        book = FourHourLiquidityBook(persist=False)
        book.on_4h_close(
            "BTCUSD",
            _c(o=100, h=120, l=95, c=110, timeframe="4h"),
        )
        hit = book.detect_1m_sweep(
            "BTCUSD",
            _c(o=118, h=121, l=117, c=119),
        )
        self.assertIsNotNone(hit)
        _, zone = hit
        book.mark_consumed("BTCUSD", zone)
        again = book.detect_1m_sweep(
            "BTCUSD",
            _c(o=118, h=121, l=117, c=119, ts="2026-07-22T10:02:00Z"),
        )
        self.assertIsNone(again)

    def test_4h_bar_marks_prior_high_swept(self):
        book = FourHourLiquidityBook(persist=False)
        # Build enough bars for a confirmed swing high at 100.
        # indices: 0.. need left=2,right=2 around the swing.
        seq = [
            _c(o=90, h=95, l=88, c=92, timeframe="4h", ts="2026-07-01T00:00:00Z",
               candle_timestamp_ist="2026-07-01 05:30"),
            _c(o=92, h=96, l=90, c=94, timeframe="4h", ts="2026-07-01T04:00:00Z",
               candle_timestamp_ist="2026-07-01 09:30"),
            _c(o=94, h=100, l=93, c=98, timeframe="4h", ts="2026-07-01T08:00:00Z",
               candle_timestamp_ist="2026-07-01 13:30"),  # swing high 100
            _c(o=98, h=99, l=95, c=96, timeframe="4h", ts="2026-07-01T12:00:00Z",
               candle_timestamp_ist="2026-07-01 17:30"),
            _c(o=96, h=97, l=94, c=95, timeframe="4h", ts="2026-07-01T16:00:00Z",
               candle_timestamp_ist="2026-07-01 21:30"),
        ]
        for c in seq:
            book.on_4h_close("BTCUSD", c)
        self.assertIn(100.0, book.snapshot("BTCUSD")["highs"])
        # Later bar sweeps 100: wick above, close back below.
        book.on_4h_close(
            "BTCUSD",
            _c(
                o=95,
                h=102,
                l=90,
                c=93,
                timeframe="4h",
                ts="2026-07-02T00:00:00Z",
                candle_timestamp_ist="2026-07-02 05:30",
            ),
        )
        self.assertNotIn(100.0, book.snapshot("BTCUSD")["highs"])
        st = book._state("BTCUSD")
        self.assertIn("high:100.0", st.consumed)
        rec = st.consumed_detail["high:100.0"]
        self.assertEqual(rec.swept_at, "2026-07-02 05:30")

    def test_zones_sorted_recent_first_and_consumed_10d(self):
        import json
        import os
        import tempfile

        from core.strategies.crypto.LiquiditySweepStrategy.four_hour_liquidity import (
            ConsumedRecord,
            LiquidityZone,
        )

        book = FourHourLiquidityBook(persist=False)
        book.on_4h_close(
            "BTCUSD",
            _c(
                o=100,
                h=110,
                l=90,
                c=105,
                timeframe="4h",
                ts="2026-08-01T00:00:00Z",
                candle_timestamp_ist="2026-08-01 05:30",
            ),
        )
        st = book._state("BTCUSD")
        st.high_zones = [
            LiquidityZone(
                price=1.0, side="high", source="swing_4h", bar_key="2026-07-01 05:30",
                open=1, high=1, low=1, close=1,
            ),
            LiquidityZone(
                price=2.0, side="high", source="swing_4h", bar_key="2026-07-28 05:30",
                open=2, high=2, low=2, close=2,
            ),
        ]
        st.high_zones = book._sort_zones_recent_first(st.high_zones)
        self.assertEqual([z.price for z in st.high_zones], [2.0, 1.0])

        old = LiquidityZone(
            price=50.0, side="high", source="swing_4h", bar_key="2026-06-01 05:30",
            open=50, high=50, low=50, close=50,
        )
        recent = LiquidityZone(
            price=60.0, side="high", source="swing_4h", bar_key="2026-07-28 05:30",
            open=60, high=60, low=60, close=60,
        )
        st.consumed.add("high:50.0")
        st.consumed.add("high:60.0")
        st.consumed_detail["high:50.0"] = ConsumedRecord(zone=old, swept_at="2026-06-02 05:30")
        st.consumed_detail["high:60.0"] = ConsumedRecord(
            zone=recent, swept_at="2026-07-29 05:30"
        )
        kept = book._consumed_records_last_days("BTCUSD", as_of="2026-08-01 05:30")
        self.assertEqual([r.zone.price for r in kept], [60.0])

        with tempfile.TemporaryDirectory() as td:
            active = os.path.join(td, "active.json")
            jsonl = os.path.join(td, "zones.jsonl")
            book2 = FourHourLiquidityBook(
                persist=True, jsonl_path=jsonl, active_path=active
            )
            book2._by_symbol["BTCUSD"] = st
            book2.set_persist_source("test")
            book2.flush_persist(as_of="2026-08-01 05:30")
            raw = json.load(open(active))
            cons = raw["symbols"]["BTCUSD"]["consumed"]
            self.assertEqual(len(cons), 1)
            self.assertEqual(cons[0]["price"], 60.0)
            self.assertEqual(cons[0]["swept_at"], "2026-07-29 05:30")
            hi_keys = [h["bar_key"] for h in raw["symbols"]["BTCUSD"]["highs"]]
            self.assertEqual(hi_keys, sorted(hi_keys, reverse=True))

    def test_persist_and_load_active_reference(self):
        import json
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            jsonl = os.path.join(td, "liquidity_zones.jsonl")
            active = os.path.join(td, "liquidity_zones_active.json")
            book = FourHourLiquidityBook(
                persist=True, jsonl_path=jsonl, active_path=active
            )
            book.set_persist_source("backtest_rebuild")
            book.on_4h_close(
                "BTCUSD",
                _c(o=100, h=120, l=95, c=110, timeframe="4h", ts="2026-07-22T08:00:00Z"),
            )
            self.assertTrue(os.path.isfile(jsonl))
            self.assertTrue(os.path.isfile(active))
            live = FourHourLiquidityBook(
                persist=False, jsonl_path=jsonl, active_path=active
            )
            self.assertEqual(live.load_active_reference(), 1)
            snap = live.snapshot("BTCUSD")
            self.assertIn(120.0, snap["highs"])
            self.assertIn(95.0, snap["lows"])
            with open(active, "r", encoding="utf-8") as f:
                raw = json.load(f)
            hi0 = raw["symbols"]["BTCUSD"]["highs"][0]
            self.assertIn("candle", hi0)
            self.assertEqual(hi0["candle"]["high"], 120.0)
            self.assertEqual(hi0["candle"]["low"], 95.0)
            self.assertEqual(hi0["candle"]["timeframe"], "4h")
            self.assertEqual(hi0["candle"]["candle_timestamp_ist"], hi0["bar_key"])


class TestGauthamFourHourSweep(unittest.TestCase):
    def _ctx(self):
        store = MagicMock()
        store.get_open_positions.return_value = []
        return SimpleNamespace(position_store=store)

    def test_short_entry_on_swing_sweep_inside_zone(self):
        book = FourHourLiquidityBook(persist=False)
        _seed_swing_high_120(book)
        # Confirm swing is present (not only prev_4h of last bar)
        hi_zones = book._state("BTCUSD").high_zones
        self.assertTrue(any(z.price == 120.0 and z.source == "swing_4h" for z in hi_zones))

        g = GauthamLiquiditySweep(zones=book)
        ctx = self._ctx()

        # Sweep swing high 120 (H>120, C<120) → SHORT; SL = candle high
        sig = g.evaluate(
            _c(
                o=119,
                h=121,
                l=118,
                c=118.5,
                ts="2026-07-22T10:00:00+00:00",
                candle_timestamp_ist="2026-07-22 15:30",
            ),
            ctx,
            strategy_name="LiquiditySweepStrategy",
        )
        self.assertIsNotNone(sig)
        self.assertEqual(sig.side, "SHORT")
        self.assertEqual(sig.stop_price, 121.0)
        self.assertAlmostEqual(sig.entry_price, 118.5)
        self.assertEqual(sig.zone_price, 120.0)
        self.assertEqual(sig.zone_side, "high")
        self.assertEqual(sig.zone_source, "swing_4h")
        self.assertEqual(sig.zone_bar_key, "2026-07-21 13:30")
        self.assertEqual(sig.sweep_bar_key, "2026-07-22 15:30")

    def test_prev_4h_sweep_does_not_enter_in_swing_mode(self):
        book = FourHourLiquidityBook(persist=False)
        # Single bar → only prev_4h high=120, no confirmed swing yet
        book.on_4h_close(
            "BTCUSD",
            _c(
                o=100,
                h=120,
                l=95,
                c=110,
                timeframe="4h",
                ts="2026-07-22T04:00:00Z",
                candle_timestamp_ist="2026-07-22 09:30",
            ),
        )
        g = GauthamLiquiditySweep(zones=book, enable_swing_mode=True)
        ctx = self._ctx()
        sig = g.evaluate(
            _c(
                o=119,
                h=121,
                l=118,
                c=118.5,
                ts="2026-07-22T10:00:00+00:00",
                candle_timestamp_ist="2026-07-22 15:30",
            ),
            ctx,
            strategy_name="LiquiditySweepStrategy",
        )
        self.assertIsNone(sig)

    def test_prev_4h_sweep_enters_when_swing_mode_off(self):
        book = FourHourLiquidityBook(persist=False)
        book.on_4h_close(
            "BTCUSD",
            _c(
                o=100,
                h=120,
                l=95,
                c=110,
                timeframe="4h",
                ts="2026-07-22T04:00:00Z",
                candle_timestamp_ist="2026-07-22 09:30",
            ),
        )
        g = GauthamLiquiditySweep(zones=book, enable_swing_mode=False)
        ctx = self._ctx()
        sig = g.evaluate(
            _c(
                o=119,
                h=121,
                l=118,
                c=118.5,
                ts="2026-07-22T10:00:00+00:00",
                candle_timestamp_ist="2026-07-22 15:30",
            ),
            ctx,
            strategy_name="LiquiditySweepStrategy",
        )
        self.assertIsNotNone(sig)
        self.assertEqual(sig.side, "SHORT")
        self.assertEqual(sig.zone_source, "prev_4h")
        self.assertEqual(sig.zone_price, 120.0)

    def test_no_entry_without_4h_zones(self):
        g = GauthamLiquiditySweep()
        ctx = self._ctx()
        sig = g.evaluate(
            _c(
                o=119,
                h=121,
                l=118,
                c=118.5,
                ts="2026-07-22T10:00:00+00:00",
                candle_timestamp_ist="2026-07-22 15:30",
            ),
            ctx,
            strategy_name="LiquiditySweepStrategy",
        )
        self.assertIsNone(sig)

    def test_low_entries_disabled_skips_long_setup(self):
        book = FourHourLiquidityBook(persist=False)
        _seed_swing_high_120(book)
        g = GauthamLiquiditySweep(
            zones=book, enable_high_entries=True, enable_low_entries=False
        )
        ctx = self._ctx()
        # Low sweep (prev_4h only here) ignored; also low entries disabled
        self.assertIsNone(
            g.evaluate(
                _c(
                    o=97,
                    h=98,
                    l=94,
                    c=96,
                    ts="2026-07-22T10:00:00+00:00",
                    candle_timestamp_ist="2026-07-22 15:30",
                ),
                ctx,
                strategy_name="LiquiditySweepStrategy",
            )
        )
        # Swing high sweep still enters SHORT
        sig = g.evaluate(
            _c(
                o=119,
                h=121,
                l=118,
                c=118.5,
                ts="2026-07-22T10:01:00+00:00",
                candle_timestamp_ist="2026-07-22 15:31",
            ),
            ctx,
            strategy_name="LiquiditySweepStrategy",
        )
        self.assertIsNotNone(sig)
        self.assertEqual(sig.side, "SHORT")
        self.assertEqual(sig.zone_source, "swing_4h")
        self.assertEqual(sig.stop_price, 121.0)

    def test_high_entries_disabled_skips_short_detect(self):
        book = FourHourLiquidityBook(persist=False)
        book.on_4h_close(
            "BTCUSD",
            _c(o=100, h=120, l=95, c=110, timeframe="4h"),
        )
        hit = book.detect_1m_sweep(
            "BTCUSD",
            _c(o=118, h=121, l=117, c=119),
            enable_high=False,
            enable_low=True,
        )
        self.assertIsNone(hit)
        hit_low = book.detect_1m_sweep(
            "BTCUSD",
            _c(o=97, h=98, l=94, c=96),
            enable_high=False,
            enable_low=True,
        )
        self.assertIsNotNone(hit_low)
        self.assertEqual(hit_low[0], "LONG")


class TestParentFourHourRouting(unittest.TestCase):
    def _bare(self):
        s = LiquiditySweepStrategy.__new__(LiquiditySweepStrategy)
        s._meta_by_structure_id = {}
        s._evaluated_bar_keys = set()
        s._zones = FourHourLiquidityBook(persist=False)
        s._zones_hydrated = set()
        s._4h_hist_rows = {}
        s._4h_applied_count = {}
        s.enable_high_entries = True
        s.enable_low_entries = True
        s.enable_swing_mode = True
        s._gautham = GauthamLiquiditySweep(
            zones=s._zones,
            enable_high_entries=True,
            enable_low_entries=True,
            enable_swing_mode=True,
        )
        s._substrategies = {"GauthamLiquiditySweep": s._gautham}
        s.enabled_substrategies = ["GauthamLiquiditySweep"]
        s.name = "LiquiditySweepStrategy"
        return s

    def test_4h_candle_updates_zones_no_entry(self):
        s = self._bare()
        out = LiquiditySweepStrategy.on_candle(
            s,
            _c(
                o=100,
                h=120,
                l=95,
                c=110,
                timeframe="4h",
                bucket=1000,
                ts="2026-07-22T08:00:00Z",
            ),
            SimpleNamespace(),
        )
        self.assertIsNone(out)
        snap = s._zones.snapshot("BTCUSD")
        self.assertIn(120.0, snap["highs"])

    def test_should_evaluate_keys_include_timeframe(self):
        s = self._bare()
        c1 = _c(timeframe="1", bucket=10)
        c4 = _c(timeframe="4h", bucket=10)
        self.assertTrue(s.should_evaluate(c1))
        self.assertTrue(s.should_evaluate(c4))
        self.assertFalse(s.should_evaluate(c1))

    def test_ensure_zones_as_of_from_history_rows(self):
        s = self._bare()
        s._4h_hist_rows["BTCUSD"] = [
            {
                "timestamp": pd.Timestamp("2026-07-22T00:00:00Z"),
                "open": 100.0,
                "high": 120.0,
                "low": 95.0,
                "close": 110.0,
            },
            {
                "timestamp": pd.Timestamp("2026-07-22T04:00:00Z"),
                "open": 110.0,
                "high": 130.0,
                "low": 108.0,
                "close": 125.0,
            },
        ]
        # Before first 4h close (open+4h) → no zones
        s._ensure_zones_as_of("BTCUSD", "2026-07-22T03:00:00Z")
        self.assertEqual(s._zones.snapshot("BTCUSD")["highs"], [])
        # After first bar closed, before second
        s._ensure_zones_as_of("BTCUSD", "2026-07-22T04:30:00Z")
        self.assertIn(120.0, s._zones.snapshot("BTCUSD")["highs"])
        self.assertNotIn(130.0, s._zones.snapshot("BTCUSD")["highs"])
        # After second closed
        s._ensure_zones_as_of("BTCUSD", "2026-07-22T08:30:00Z")
        self.assertIn(130.0, s._zones.snapshot("BTCUSD")["highs"])


if __name__ == "__main__":
    unittest.main()
