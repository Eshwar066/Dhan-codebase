"""Decision rules for MagicalLines (no option-chain I/O)."""

from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace

import pandas as pd

from core.strategies.IndiaMktMixins import IST
from core.strategies.MagicalLines.MagicalLines import MagicalLines


def _candle(day: str, hhmm: str, close: float, symbol: str = "NIFTY") -> dict:
    ts = pd.Timestamp(f"{day} {hhmm}:00", tz=IST)
    return {
        "symbol": symbol,
        "timestamp": ts,
        "open": close,
        "close": close,
    }


class MagicalLinesRuleTests(unittest.TestCase):
    def setUp(self):
        self.strategy = MagicalLines()

    def test_magical_line_and_strike(self):
        self.assertAlmostEqual(self.strategy.magical_line(10000, "SHORT_PE"), 9975.0)
        self.assertAlmostEqual(self.strategy.magical_line(10000, "SHORT_CE"), 10025.0)
        self.assertEqual(self.strategy.strike_near(10040), 10050)
        self.assertEqual(self.strategy.calculate_hedge_strike(25000, "PE"), 24500)
        self.assertEqual(self.strategy.calculate_hedge_strike(25000, "CE"), 25500)

    def test_flat_book_follows_daily_colour(self):
        day = "2026-06-02"
        candle = _candle(day, "15:15", 25000)
        self.strategy._session_open[("NIFTY", date(2026, 6, 2))] = 24900
        self.assertEqual(self.strategy._entry_plan(candle, None, []), ("SHORT_PE", 1))
        self.strategy._session_open[("NIFTY", date(2026, 6, 2))] = 25100
        self.assertEqual(self.strategy._entry_plan(candle, None, []), ("SHORT_CE", 1))

    def test_second_line_only_three_percent_beyond_first_and_same_colour(self):
        day = date(2026, 6, 3)
        candle = _candle("2026-06-03", "15:15", 10400)
        self.strategy._session_open[("NIFTY", day)] = 10300  # green
        first = SimpleNamespace(
            level=1,
            entry_date=date(2026, 6, 1),
            magical_line=10000.0,
            direction="SHORT_PE",
            symbol="NIFTY",
        )
        self.assertEqual(
            self.strategy._entry_plan(candle, None, [first]),
            ("SHORT_PE", 2),
        )
        # Still inside ±3% of spot.
        near = SimpleNamespace(
            level=1,
            entry_date=date(2026, 6, 1),
            magical_line=10300.0,
            direction="SHORT_PE",
            symbol="NIFTY",
        )
        self.assertIsNone(self.strategy._entry_plan(candle, None, [near]))
        # 3% up, but today's candle is red → do not add a put.
        self.strategy._session_open[("NIFTY", day)] = 10500
        self.assertIsNone(self.strategy._entry_plan(candle, None, [first]))

    def test_buffer_holds_small_cross_and_half_percent_exits_immediately(self):
        ml = 10000.0
        meta = SimpleNamespace(
            direction="SHORT_PE",
            magical_line=ml,
            entry_date=date(2026, 6, 1),
            symbol="NIFTY",
        )
        sid = "MagicalLines:NIFTY:L1:SHORT_PE:2026-06-01:10000.00:abc123"
        self.strategy._meta_by_structure_id[sid] = meta
        position = SimpleNamespace(
            tag="MAIN",
            structure_id=sid,
            instrument=SimpleNamespace(expiry=date(2026, 6, 30)),
        )

        # Same session, 0.3% through the line: not a next-day reverse, not a 0.5% stop.
        same_day = _candle("2026-06-01", "15:15", ml * (1 - 0.003))
        self.assertIsNone(self.strategy._exit_reason(position, same_day, None))

        # Next day, inside the 0.2% buffer.
        buffered = _candle("2026-06-02", "15:15", ml * (1 - 0.001))
        self.assertIsNone(self.strategy._exit_reason(position, buffered, None))

        # Next day, through the buffer but under 0.5% → reverse at the decision bar.
        crossed = _candle("2026-06-02", "15:15", ml * (1 - 0.003))
        self.assertEqual(self.strategy._exit_reason(position, crossed, None), "REVERSAL")

        # 0.3% through on a mid-session 30m bar is not the daily reverse.
        mid = _candle("2026-06-02", "12:15", ml * (1 - 0.003))
        self.assertIsNone(self.strategy._exit_reason(position, mid, None))

        # 0.6% through the line on any 30m bar → immediate exit.
        stopped = _candle("2026-06-02", "12:15", ml * (1 - 0.006))
        self.assertEqual(self.strategy._exit_reason(position, stopped, None), "ADVERSE")

    def test_expiry_week_exits_before_the_stop(self):
        meta = SimpleNamespace(
            direction="SHORT_CE",
            magical_line=10000.0,
            entry_date=date(2026, 6, 1),
            symbol="NIFTY",
        )
        sid = "MagicalLines:NIFTY:L1:SHORT_CE:2026-06-01:10000.00:abc123"
        self.strategy._meta_by_structure_id[sid] = meta
        position = SimpleNamespace(
            tag="MAIN",
            structure_id=sid,
            instrument=SimpleNamespace(expiry=date(2026, 6, 30)),
        )
        candle = _candle("2026-06-23", "10:15", 10000)
        self.assertEqual(self.strategy._exit_reason(position, candle, None), "EXPIRY_WEEK")

    def test_structure_id_round_trip(self):
        from core.strategies.MagicalLines.MagicalLines import _MlMeta

        meta = _MlMeta(
            symbol="NIFTY",
            entry_date=date(2026, 6, 2),
            magical_line=24875.5,
            direction="SHORT_PE",
            level=2,
            option_type="PE",
        )
        parsed = self.strategy._meta_from_structure_id(self.strategy._structure_id(meta))
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.level, 2)
        self.assertEqual(parsed.direction, "SHORT_PE")
        self.assertEqual(parsed.entry_date, date(2026, 6, 2))
        self.assertAlmostEqual(parsed.magical_line, 24875.5)


if __name__ == "__main__":
    unittest.main()
