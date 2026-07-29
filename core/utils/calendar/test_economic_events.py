"""Unit tests for Delta economic event blackout calendar + OMS guard."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, time, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.orderExecution.risk_manager import RiskManager
from core.utils.calendar.economic_events import (
    EconomicEvent,
    EventBlackoutGuard,
    EventCalendarService,
    active_events,
    is_blackout_active,
    load_events_from_json,
    merge_events,
)
from core.utils.calendar.fetch_economic_calendar import (
    classify_event_title,
    parse_bea_schedule_html,
    parse_fomc_calendar_html,
)


def _utc(y, m, d, hh=12, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def _event(name: str, when: datetime, **kwargs) -> EconomicEvent:
    return EconomicEvent(
        event=name,
        time=when,
        impact=kwargs.get("impact", "HIGH"),
        currency=kwargs.get("currency", "USD"),
        source=kwargs.get("source", "manual"),
        event_key=kwargs.get("event_key"),
    )


class TestWindowMath(unittest.TestCase):
    def test_inside_plus_minus_60(self):
        when = _utc(2026, 8, 12, 12, 30)
        events = [_event("US CPI", when)]
        now = when - timedelta(minutes=30)
        active, hit = is_blackout_active(events, now, minutes_before=60, minutes_after=60)
        self.assertTrue(active)
        self.assertEqual(hit.event, "US CPI")
        now2 = when + timedelta(minutes=59)
        self.assertTrue(is_blackout_active(events, now2)[0])

    def test_outside_window(self):
        when = _utc(2026, 8, 12, 12, 30)
        events = [_event("US CPI", when)]
        before = when - timedelta(minutes=61)
        after = when + timedelta(minutes=61)
        self.assertFalse(is_blackout_active(events, before)[0])
        self.assertFalse(is_blackout_active(events, after)[0])

    def test_non_high_ignored(self):
        when = _utc(2026, 8, 12, 12, 30)
        events = [_event("US Retail Sales", when, impact="MEDIUM")]
        self.assertFalse(is_blackout_active(events, when)[0])
        self.assertEqual(active_events(events, when), [])


class TestMergeOverride(unittest.TestCase):
    def test_yaml_wins_same_identity(self):
        when = _utc(2026, 9, 17, 18, 0)
        cache = [_event("FOMC Rate Decision", when, source="fed")]
        yaml_ev = [_event("FOMC Rate Decision", when, source="manual")]
        merged = merge_events(cache, yaml_ev)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].source, "manual")

    def test_yaml_adds_extra(self):
        cache = [_event("US CPI", _utc(2026, 8, 12, 12, 30), source="bls")]
        yaml_ev = [_event("US NFP", _utc(2026, 8, 7, 12, 30), source="manual")]
        merged = merge_events(cache, yaml_ev)
        self.assertEqual(len(merged), 2)

    def test_service_loads_yaml_over_json(self):
        when = _utc(2026, 9, 17, 18, 0)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache.json"
            yaml_path = root / "manual.yaml"
            cache.write_text(
                json.dumps(
                    {
                        "events": [
                            {
                                "event": "FOMC Rate Decision",
                                "time": "2026-09-17T18:00:00Z",
                                "impact": "HIGH",
                                "currency": "USD",
                                "source": "fed",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            yaml_path.write_text(
                "\n".join(
                    [
                        "enabled: true",
                        "blackout_minutes_before: 45",
                        "blackout_minutes_after: 45",
                        "events:",
                        "  - event: FOMC Rate Decision",
                        '    time: "2026-09-17T18:00:00Z"',
                        "    impact: HIGH",
                        "    currency: USD",
                    ]
                ),
                encoding="utf-8",
            )
            svc = EventCalendarService(
                cache_json=cache,
                manual_yaml=yaml_path,
                base_dir=root,
            )
            self.assertEqual(svc.minutes_before, 45)
            self.assertEqual(len(svc.events), 1)
            self.assertEqual(svc.events[0].source, "manual")
            active, _ = svc.is_blackout_active(when)
            self.assertTrue(active)
            # 50 minutes before with 45m window → inactive
            self.assertFalse(svc.is_blackout_active(when - timedelta(minutes=50))[0])


class TestFetcherHelpers(unittest.TestCase):
    def test_classify_titles(self):
        self.assertEqual(classify_event_title("Consumer Price Index")[0], "CPI")
        self.assertEqual(classify_event_title("Employment Situation")[0], "NFP")
        self.assertEqual(classify_event_title("Gross Domestic Product")[0], "GDP")
        self.assertIsNone(classify_event_title("Jobless Claims"))

    def test_parse_fomc_html_fixture(self):
        html = """
        <html><body>
        <h4>2026 FOMC Meetings</h4>
        <p>January 27-28 Press Conference</p>
        <p>March 17-18* Press Conference</p>
        <h4>2027 FOMC Meetings</h4>
        <p>January 26-27</p>
        </body></html>
        """
        events = parse_fomc_calendar_html(html, years=(2026,))
        # 2 meetings * (decision + press) = 4
        self.assertEqual(len(events), 4)
        self.assertTrue(all(e.event_key == "FOMC" for e in events))
        self.assertTrue(all(e.source == "fed" for e in events))

    def test_parse_bea_html_fixture(self):
        html = """
        Clear Year 2026 Release
        July 30 8:30 AM News GDP (Advance Estimate), 2nd Quarter 2026
        July 31 8:30 AM News Personal Income and Outlays, June 2026
        August 26 8:30 AM News GDP (Second Estimate) and Corporate Profits, 2nd Quarter 2026
        September 30 8:30 AM News GDP by County and Personal Income by County, 2025
        """
        events = parse_bea_schedule_html(html)
        keys = {e.event_key for e in events}
        self.assertEqual(keys, {"GDP", "PCE"})
        self.assertTrue(any(e.event == "US GDP" for e in events))
        self.assertTrue(any(e.event == "US PCE" for e in events))
        # County GDP filtered out
        self.assertEqual(sum(1 for e in events if e.event_key == "GDP"), 2)


class TestShortDteRules(unittest.TestCase):
    def setUp(self):
        # FOMC decision 18:00Z = 23:30 IST on 2026-07-29
        self.fomc = _event(
            "FOMC Rate Decision",
            _utc(2026, 7, 29, 18, 0),
            source="fed",
            event_key="FOMC",
        )
        self.calendar = EventCalendarService.__new__(EventCalendarService)
        self.calendar.enabled = True
        self.calendar.minutes_before = 60
        self.calendar.minutes_after = 60
        self.calendar.events = [self.fomc]
        self.calendar.short_dte_rules_enabled = True
        self.calendar.zero_dte_cutoff_ist = time(17, 30)
        self.calendar.block_1dte_until_event_done = True
        self.guard = EventBlackoutGuard(self.calendar, venue="DELTA")

    def _intent(self, expiry: str, action="ENTRY"):
        return SimpleNamespace(
            action=action,
            instrument=SimpleNamespace(
                trading_symbol="C-BTC-1",
                lot_size=1,
                contract_multiplier=1,
                contract_key="C-BTC-1",
                instrument_type="OP",
                option_type="CE",
                expiry=expiry,
            ),
            side="SELL",
            qty=1,
            price=5.0,
            strategy="DirectionalOptionSelling",
            structure_id=None,
            tag="MAIN",
            intent_id="t1",
            metadata_extras={},
        )

    def test_0dte_allowed_before_cutoff(self):
        # 16:00 IST = 10:30 UTC
        now = _utc(2026, 7, 29, 10, 30)
        blocked, reason = self.guard.should_block_entry(
            self._intent("290726"), now=now
        )
        self.assertFalse(blocked, reason)

    def test_0dte_blocked_after_530_ist(self):
        # 17:30 IST = 12:00 UTC
        now = _utc(2026, 7, 29, 12, 0)
        blocked, reason = self.guard.should_block_entry(
            self._intent("290726"), now=now
        )
        self.assertTrue(blocked)
        self.assertIn("0DTE", reason)

    def test_1dte_blocked_until_event_done(self):
        # 18:00 IST = 12:30 UTC — after DOS rollover, still before FOMC
        now = _utc(2026, 7, 29, 12, 30)
        blocked, reason = self.guard.should_block_entry(
            self._intent("300726"), now=now
        )
        self.assertTrue(blocked)
        self.assertIn("1DTE", reason)

    def test_weekly_dte_allowed_outside_pm_window(self):
        now = _utc(2026, 7, 29, 12, 30)
        # expiry 7 days out
        blocked, reason = self.guard.should_block_entry(
            self._intent("050826"), now=now
        )
        self.assertFalse(blocked, reason)

    def test_all_entry_blocked_inside_pm_window(self):
        # 17:30 UTC = inside ±60m of 18:00Z FOMC
        now = _utc(2026, 7, 29, 17, 30)
        blocked, reason = self.guard.should_block_entry(
            self._intent("050826"), now=now
        )
        self.assertTrue(blocked)
        self.assertIn("blackout", reason.lower())

    def test_1dte_allowed_after_event_done(self):
        # FOMC + 60m = 19:00Z; check 19:01Z
        now = _utc(2026, 7, 29, 19, 1)
        blocked, reason = self.guard.should_block_entry(
            self._intent("300726"), now=now
        )
        self.assertFalse(blocked, reason)


class TestRiskManagerBlackout(unittest.TestCase):
    def setUp(self):
        self.when = _utc(2026, 8, 12, 12, 30)
        calendar = EventCalendarService.__new__(EventCalendarService)
        calendar.enabled = True
        calendar.minutes_before = 60
        calendar.minutes_after = 60
        calendar.events = [_event("US CPI", self.when, source="bls")]
        calendar.cache_json = Path("/tmp/x")
        calendar.manual_yaml = Path("/tmp/y")
        self.guard = EventBlackoutGuard(calendar, venue="DELTA")
        # Freeze "now" via monkeypatch on guard path: wrap calendar check with fixed now.
        self._orig = self.guard.calendar.is_blackout_active

        def _fixed(now=None):
            return self._orig(self.when)

        self.guard.calendar.is_blackout_active = _fixed  # type: ignore[method-assign]

        self.pm = MagicMock()
        self.pm.has_open_structure.return_value = False
        self.pm.get_qty.return_value = 0
        self.pm.get_open_positions.return_value = []
        self.pm.total_exposure.return_value = 0.0

        self.rm = RiskManager(
            position_manager=self.pm,
            max_open_positions=20,
            cooldown_seconds=0,
            event_blackout_guard=self.guard,
        )
        # Patch open count helper
        self.rm._open_positions_count = lambda strategy=None: 0  # type: ignore

    def _intent(self, action="ENTRY"):
        return SimpleNamespace(
            action=action,
            instrument=SimpleNamespace(
                trading_symbol="C-BTC-1",
                lot_size=1,
                contract_multiplier=1,
                contract_key="C-BTC-1",
                instrument_type="OP",
                option_type="CE",
            ),
            side="SELL",
            qty=1,
            price=5.0,
            strategy="DirectionalOptionSelling",
            structure_id=None,
            tag="MAIN",
            intent_id="t1",
        )

    def test_entry_blocked_during_blackout(self):
        self.assertFalse(self.rm.allow_intent(self._intent("ENTRY"), {}))

    def test_force_exit_allowed_during_blackout(self):
        self.assertTrue(self.rm.allow_intent(self._intent("FORCE_EXIT"), {}))

    def test_exit_allowed_during_blackout(self):
        self.assertTrue(self.rm.allow_intent(self._intent("EXIT"), {}))


class TestEntryPauseReasons(unittest.TestCase):
    def test_includes_economic_event_blackout(self):
        from core.engine.live_engine import LiveEngine

        when = _utc(2026, 8, 12, 12, 30)
        calendar = EventCalendarService.__new__(EventCalendarService)
        calendar.enabled = True
        calendar.minutes_before = 60
        calendar.minutes_after = 60
        calendar.events = [_event("US CPI", when)]
        guard = EventBlackoutGuard(calendar, venue="DELTA")
        orig = guard.calendar.is_blackout_active

        def _fixed(now=None):
            return orig(when)

        guard.calendar.is_blackout_active = _fixed  # type: ignore[method-assign]

        engine = LiveEngine.__new__(LiveEngine)
        engine._entries_paused_feed_stale = False
        engine._entries_paused_order_mismatch = False
        engine._entries_paused_memory = False
        engine._entries_paused_latency = False
        engine.venue = "DELTA"
        engine._event_blackout_guard = guard

        reasons = LiveEngine._entry_pause_reasons(engine)
        self.assertIn("economic_event_blackout", reasons)

    def test_non_delta_skips_blackout_reason(self):
        from core.engine.live_engine import LiveEngine

        when = _utc(2026, 8, 12, 12, 30)
        calendar = EventCalendarService.__new__(EventCalendarService)
        calendar.enabled = True
        calendar.minutes_before = 60
        calendar.minutes_after = 60
        calendar.events = [_event("US CPI", when)]
        guard = EventBlackoutGuard(calendar, venue="DELTA")

        engine = LiveEngine.__new__(LiveEngine)
        engine._entries_paused_feed_stale = False
        engine._entries_paused_order_mismatch = False
        engine._entries_paused_memory = False
        engine._entries_paused_latency = False
        engine.venue = "DHAN"
        engine._event_blackout_guard = guard

        reasons = LiveEngine._entry_pause_reasons(engine)
        self.assertNotIn("economic_event_blackout", reasons)


class TestLoadJsonFixture(unittest.TestCase):
    def test_load_events_from_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "event": "US CPI",
                            "time": "2026-08-12T12:30:00Z",
                            "impact": "HIGH",
                            "currency": "USD",
                            "source": "bls",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            events = load_events_from_json(path)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].event, "US CPI")


if __name__ == "__main__":
    unittest.main()
