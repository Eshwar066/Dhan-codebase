"""Hedge rollover target date: weekend + NSE holiday adjustment."""

from datetime import date

from core.utils.session.session_manager import SessionManager


def test_rollover_18th_weekday_unchanged():
    # March 18, 2026 is Wednesday
    assert SessionManager.hedge_rollover_target_date(2026, 3) == date(2026, 3, 18)


def test_rollover_18th_sunday_moves_to_friday():
    # Jan 18, 2026 is Sunday → Friday Jan 16
    assert SessionManager.hedge_rollover_target_date(2026, 1) == date(2026, 1, 16)


def test_rollover_holiday_moves_to_prior_session():
    # Holi 2026-03-06 (Friday) → roll on Thursday Mar 5
    assert SessionManager.hedge_rollover_target_date(
        2026, 3, rollover_day=6
    ) == date(2026, 3, 5)


def test_rollover_independence_day_weekend_and_holiday():
    # Aug 15, 2026 is Saturday + NSE holiday → Aug 14 (Friday)
    assert SessionManager.hedge_rollover_target_date(
        2026, 8, rollover_day=15
    ) == date(2026, 8, 14)
