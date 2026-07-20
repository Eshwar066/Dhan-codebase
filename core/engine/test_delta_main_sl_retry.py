"""Unit tests for Delta missing-MAIN_SL retry / force-close guard."""

from __future__ import annotations

import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.engine.live_engine import (
    DELTA_MAIN_SL_RETRY_INTERVAL_SEC,
    DELTA_MAIN_SL_RETRY_MAX_ATTEMPTS,
    LiveEngine,
)
from run.config import RunMode


class _FakePos:
    def __init__(self, *, net_qty, structure_id, strategy, trading_symbol="C-BTC-100"):
        self.net_qty = net_qty
        self.structure_id = structure_id
        self.strategy = strategy
        self.tag = "MAIN"
        self.avg_price = 10.0
        self.intent_id = "main-1"
        self.instrument = SimpleNamespace(
            trading_symbol=trading_symbol,
            lot_size=1,
            strike=100,
            option_type="CE",
            expiry=None,
        )


class TestDeltaMainSlRetry(unittest.TestCase):
    def _engine(self, *, venue="DELTA"):
        eng = LiveEngine.__new__(LiveEngine)
        eng.venue = venue
        eng.run_mode = RunMode.LIVE
        eng.engine_logger = None
        eng._delta_main_sl_retry = {}
        eng.position_manager = SimpleNamespace(
            positions={},
            get_position_metadata=lambda _s: {},
        )
        eng.order_router = SimpleNamespace(
            intent_store=MagicMock(),
            broker=MagicMock(),
            risk=None,
        )
        eng._resolve_position_ownership_from_intent_store = lambda *_a, **_k: None
        eng._strategy_obj_for_name = MagicMock()
        eng._bracket_leg_satisfied = MagicMock(return_value=False)
        eng._on_pm_main_entry_fill = MagicMock()
        eng._force_close_position_missing_main_sl = MagicMock()
        return eng

    def test_skips_non_delta_venue(self):
        eng = self._engine(venue="DHAN")
        eng.position_manager.positions = {
            "C-BTC-100": _FakePos(net_qty=-1, structure_id="s1", strategy="Dos")
        }
        eng._maybe_retry_delta_missing_main_sl()
        eng._on_pm_main_entry_fill.assert_not_called()

    def test_retries_every_interval_then_force_closes(self):
        eng = self._engine()
        pos = _FakePos(net_qty=-2, structure_id="sid-1", strategy="Dos")
        eng.position_manager.positions = {"C-BTC-100": pos}
        strategy = SimpleNamespace(name="Dos", bracket_leg_tags=["MAIN_SL"])
        eng._strategy_obj_for_name.return_value = strategy

        # Attempt 1 immediate
        eng._maybe_retry_delta_missing_main_sl()
        self.assertEqual(eng._on_pm_main_entry_fill.call_count, 1)
        self.assertEqual(eng._delta_main_sl_retry["sid-1"]["attempts"], 1)

        # Within interval: no second attempt
        eng._maybe_retry_delta_missing_main_sl()
        self.assertEqual(eng._on_pm_main_entry_fill.call_count, 1)

        # Force next due
        eng._delta_main_sl_retry["sid-1"]["next_at"] = time.time() - 1
        eng._maybe_retry_delta_missing_main_sl()
        self.assertEqual(eng._on_pm_main_entry_fill.call_count, 2)
        self.assertEqual(eng._delta_main_sl_retry["sid-1"]["attempts"], 2)

        # Exhaust retries
        eng._delta_main_sl_retry["sid-1"]["attempts"] = DELTA_MAIN_SL_RETRY_MAX_ATTEMPTS
        eng._delta_main_sl_retry["sid-1"]["next_at"] = time.time() - 1
        eng._maybe_retry_delta_missing_main_sl()
        eng._force_close_position_missing_main_sl.assert_called_once()
        self.assertEqual(
            eng._on_pm_main_entry_fill.call_count,
            2,
            "must not place SL after max attempts",
        )

    def test_clears_state_when_sl_present(self):
        eng = self._engine()
        pos = _FakePos(net_qty=-1, structure_id="sid-2", strategy="Dos")
        eng.position_manager.positions = {"C-BTC-100": pos}
        eng._strategy_obj_for_name.return_value = SimpleNamespace(
            name="Dos", bracket_leg_tags=["MAIN_SL"]
        )
        eng._delta_main_sl_retry["sid-2"] = {
            "attempts": 3,
            "next_at": time.time() + DELTA_MAIN_SL_RETRY_INTERVAL_SEC,
        }
        eng._bracket_leg_satisfied.return_value = True
        eng._maybe_retry_delta_missing_main_sl()
        self.assertNotIn("sid-2", eng._delta_main_sl_retry)
        eng._on_pm_main_entry_fill.assert_not_called()


if __name__ == "__main__":
    unittest.main()
