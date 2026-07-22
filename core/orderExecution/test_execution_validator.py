"""Unit tests for Delta OMS ExecutionValidator."""

from __future__ import annotations

import time
import unittest
from types import SimpleNamespace

from core.orderExecution.execution_validator import (
    ExecutionValidator,
    ExecutionValidatorConfig,
    MarketSnapshot,
    config_from_mapping,
    planned_sl_trigger_from_intent,
    snapshot_from_ticker,
)


def _intent(**kwargs):
    defaults = dict(
        action="ENTRY",
        tag="MAIN",
        side="SELL",
        symbol="BTCUSD",
        price=5.0,
        trigger_price=None,
        metadata_extras={},
        instrument=SimpleNamespace(trading_symbol="C-BTC-100000-220726"),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestSnapshotHelpers(unittest.TestCase):
    def test_snapshot_from_ticker(self):
        snap = snapshot_from_ticker(
            "C-BTC-1",
            {"mark_price": 6.0, "last_price": 5.5, "timestamp": time.time()},
            bid=5.0,
            ask=5.2,
        )
        self.assertEqual(snap.bid, 5.0)
        self.assertEqual(snap.ask, 5.2)
        self.assertEqual(snap.mark, 6.0)
        self.assertEqual(snap.ltp, 5.5)


class TestPlannedSl(unittest.TestCase):
    def test_explicit_planned_sl(self):
        intent = _intent(metadata_extras={"planned_sl_trigger": 10.0, "entry_premium": 5.0})
        self.assertEqual(planned_sl_trigger_from_intent(intent), 10.0)

    def test_requires_sl_premium_mult_stamp(self):
        intent = _intent(metadata_extras={"entry_premium": 5.0})
        self.assertIsNone(planned_sl_trigger_from_intent(intent))

    def test_sl_premium_mult_estimates(self):
        intent = _intent(
            metadata_extras={"entry_premium": 5.0, "sl_premium_mult": 2.0}
        )
        self.assertEqual(planned_sl_trigger_from_intent(intent), 10.0)

    def test_infer_from_default(self):
        intent = _intent(metadata_extras={"entry_premium": 5.0})
        self.assertEqual(
            planned_sl_trigger_from_intent(
                intent, infer_from_default_mult=True, default_sl_premium_mult=2.0
            ),
            10.0,
        )


class TestValidateEntry(unittest.TestCase):
    def setUp(self):
        self.cfg = ExecutionValidatorConfig(
            enabled=True,
            venue="DELTA",
            max_spread_pct=0.10,
            max_mark_mid_pct=0.50,
            require_bid_ask=True,
            require_mark=True,
            max_quote_age_sec=60.0,
        )
        self.v = ExecutionValidator(self.cfg)

    def _snap(self, **kwargs):
        base = dict(
            symbol="C-BTC-1",
            bid=4.9,
            ask=5.1,
            mark=5.0,
            ltp=5.0,
            ts=time.time(),
        )
        base.update(kwargs)
        return MarketSnapshot(**base)

    def test_accepts_sane_book(self):
        intent = _intent(
            metadata_extras={
                "entry_premium": 5.0,
                "sl_premium_mult": 2.0,
                "planned_sl_trigger": 10.0,
            }
        )
        result = self.v.validate_entry(intent, snapshot=self._snap())
        self.assertTrue(result.ok, result)

    def test_rejects_wide_spread(self):
        intent = _intent()
        result = self.v.validate_entry(
            intent, snapshot=self._snap(bid=5.0, ask=6.0, mark=5.5)
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "spread_too_wide")

    def test_rejects_mark_mid_divergence(self):
        intent = _intent()
        # mid=5.0, mark=20 → 300% divergence
        result = self.v.validate_entry(
            intent, snapshot=self._snap(bid=4.9, ask=5.1, mark=20.0)
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "mark_mid_divergence")

    def test_rejects_entry_when_planned_sl_through_mark(self):
        # Classic: sell ~5, planned SL 10, mark already 20
        intent = _intent(
            metadata_extras={
                "entry_premium": 5.0,
                "sl_premium_mult": 2.0,
                "planned_sl_trigger": 10.0,
            }
        )
        # Keep mark near mid so divergence gate does not fire first.
        # Use a looser mark/mid for this case.
        self.v.config.max_mark_mid_pct = 5.0
        result = self.v.validate_entry(
            intent, snapshot=self._snap(bid=4.9, ask=5.1, mark=20.0)
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "invalid_stop_vs_mark")

    def test_dos_spot_stop_skips_premium_sl_gate(self):
        intent = _intent(
            metadata_extras={
                "entry_premium": 5.0,
                "stop_trigger_method": "spot_price",
            }
        )
        self.v.config.max_mark_mid_pct = 5.0
        result = self.v.validate_entry(
            intent, snapshot=self._snap(bid=4.9, ask=5.1, mark=20.0)
        )
        # No planned premium SL stamped → accept (spot SL strategy).
        self.assertTrue(result.ok, result)

    def test_missing_bid_ask(self):
        intent = _intent()
        result = self.v.validate_entry(
            intent, snapshot=self._snap(bid=None, ask=None, mark=5.0)
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "missing_bid_ask")

    def test_missing_mark_falls_back_to_mid(self):
        intent = _intent(
            metadata_extras={"stop_trigger_method": "spot_price"}
        )
        result = self.v.validate_entry(
            intent, snapshot=self._snap(bid=1100.0, ask=1109.0, mark=None)
        )
        self.assertTrue(result.ok, result)
        self.assertEqual(result.details.get("mark_source"), "mid_fallback")
        self.assertAlmostEqual(result.details.get("mark"), 1104.5)

    def test_missing_mark_hard_reject_when_fallback_disabled(self):
        self.v.config.allow_mark_fallback_to_mid = False
        intent = _intent()
        result = self.v.validate_entry(
            intent, snapshot=self._snap(bid=1100.0, ask=1109.0, mark=None)
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "missing_mark")


class TestValidateStop(unittest.TestCase):
    def setUp(self):
        self.v = ExecutionValidator(
            ExecutionValidatorConfig(enabled=True, venue="DELTA")
        )

    def test_rejects_buy_stop_at_or_below_mark(self):
        intent = _intent(
            action="FORCE_EXIT",
            tag="MAIN_SL",
            side="BUY",
            trigger_price=10.0,
            price=10.0,
        )
        snap = MarketSnapshot(
            symbol="C-BTC-1", bid=19.0, ask=21.0, mark=20.0, ts=time.time()
        )
        result = self.v.validate_stop(intent, snapshot=snap)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "invalid_stop_vs_mark")

    def test_accepts_buy_stop_above_mark(self):
        intent = _intent(
            action="FORCE_EXIT",
            tag="MAIN_SL",
            side="BUY",
            trigger_price=25.0,
            price=25.0,
        )
        snap = MarketSnapshot(
            symbol="C-BTC-1", bid=19.0, ask=21.0, mark=20.0, ts=time.time()
        )
        result = self.v.validate_stop(intent, snapshot=snap)
        self.assertTrue(result.ok, result)

    def test_spot_stop_skips_mark_gate(self):
        intent = _intent(
            action="FORCE_EXIT",
            tag="MAIN_SL",
            side="BUY",
            trigger_price=95000.0,
            price=300.0,
            metadata_extras={"stop_trigger_method": "spot_price"},
        )
        snap = MarketSnapshot(
            symbol="C-BTC-1", bid=290.0, ask=310.0, mark=300.0, ts=time.time()
        )
        result = self.v.validate_stop(intent, snapshot=snap)
        self.assertTrue(result.ok, result)


class TestVenueAndConfig(unittest.TestCase):
    def test_dhan_skipped(self):
        v = ExecutionValidator(ExecutionValidatorConfig(enabled=True, venue="DELTA"))
        intent = _intent()
        result = v.validate_intent(intent, venue="DHAN")
        self.assertTrue(result.ok)
        self.assertTrue(result.details.get("skipped"))

    def test_config_from_mapping(self):
        cfg = config_from_mapping(
            {"enabled": True, "max_mark_mid_pct": 0.25, "venue": "delta"}
        )
        self.assertEqual(cfg.venue, "DELTA")
        self.assertEqual(cfg.max_mark_mid_pct, 0.25)


class TestOrderRouterRejectPath(unittest.TestCase):
    def test_validate_intent_execution_rejects(self):
        from core.orderExecution.order_router import OrderRouter

        class _DummyStore:
            def update(self, *a, **k):
                return None

        router = OrderRouter.__new__(OrderRouter)
        router.venue = "DELTA"
        router.engine_logger = None
        router.intent_store = _DummyStore()
        router.strategy_id = "test"
        router._log_oms_step = lambda *a, **k: None
        router._set_order_state = lambda *a, **k: None
        router.on_invalid_stop = None

        snap = MarketSnapshot(
            symbol="C-BTC-1",
            bid=4.9,
            ask=5.1,
            mark=20.0,
            ts=time.time(),
        )
        cfg = ExecutionValidatorConfig(
            enabled=True,
            venue="DELTA",
            max_mark_mid_pct=5.0,  # isolate stop-vs-mark
            max_spread_pct=0.5,
        )
        router.execution_validator = ExecutionValidator(
            cfg, snapshot_provider=lambda _s: snap
        )
        intent = _intent(
            intent_id="i1",
            metadata_extras={
                "entry_premium": 5.0,
                "sl_premium_mult": 2.0,
                "planned_sl_trigger": 10.0,
            },
        )
        reject = router._validate_intent_execution(intent, exec_price=5.0)
        self.assertIsNotNone(reject)
        self.assertFalse(reject["ok"])
        self.assertFalse(reject["retryable"])
        self.assertEqual(reject["reason"], "invalid_stop_vs_mark")


if __name__ == "__main__":
    unittest.main()
