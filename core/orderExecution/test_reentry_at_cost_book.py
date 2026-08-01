"""Tests for OMS ReentryAtCostBook."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.orderExecution.reentry_at_cost_book import (
    ReentryAtCostBook,
    _next_structure_id,
    resolve_reentry_policy,
)


def test_next_structure_id():
    assert _next_structure_id("BTCZeroDTE:BTCUSD:2026-07-20:CE", 1).endswith(":R1")
    assert _next_structure_id("BTCZeroDTE:BTCUSD:2026-07-20:CE:R1", 2).endswith(":R2")


def test_resolve_policy_from_strategy_and_meta():
    strategy = SimpleNamespace(
        reentry_at_cost={
            "enabled": True,
            "max_reentries": 2,
            "poll_interval_sec": 300,
            "min_premium": 0.1,
        }
    )
    p = resolve_reentry_policy(strategy, {"reentry_at_cost": {"max_reentries": 1}})
    assert p["enabled"] is True
    assert p["max_reentries"] == 1
    assert resolve_reentry_policy(SimpleNamespace(), None) is None


def test_arm_place_and_stop(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    router = MagicMock()
    router._logs_root = tmp_path / "logs"
    router.position_manager = SimpleNamespace(positions={})
    router.intent_store = SimpleNamespace(has_pending_intent=lambda **k: False)
    router.process_intent = MagicMock(return_value={"ok": True})

    book = ReentryAtCostBook(router, persist_path=str(tmp_path / "reentry.json"))
    book.set_premium_fn(lambda *a, **k: 10.0)

    strategy = SimpleNamespace(
        name="BTCZeroDTE",
        reentry_at_cost={"enabled": True, "max_reentries": 1, "min_premium": 0.1},
        underlying_symbols=["BTCUSD"],
        reentry_at_cost_allowed=lambda meta: True,
    )
    inst = SimpleNamespace(
        trading_symbol="C-BTC-65000-210726",
        strike=65000.0,
        expiry="210726",
        option_type="CE",
        exchange="DELTA",
    )
    meta = {
        "strategy_meta": {
            "strategy": "BTCZeroDTE",
            "symbol": "BTCUSD",
            "entry_premium": 14.0,
            "reentry_count": 0,
            "entry_group": "E1",
            "option_type": "CE",
            "qty_lots": 10,
            "reentry_at_cost": {"enabled": True, "max_reentries": 1},
        },
        "reentry_at_cost": {"enabled": True, "max_reentries": 1},
    }
    assert book.maybe_arm_from_main_sl(
        strategy=strategy,
        instrument=inst,
        structure_id="BTCZeroDTE:BTCUSD:2026-07-20:CE",
        metadata_extras=meta,
        qty=10,
        side="BUY",
        price=27.0,
    )
    assert book.has_pending()
    path = Path(book._persist_path)
    assert path.is_file()
    payload = json.loads(path.read_text())
    assert payload["watches"]

    # Force poll due
    for w in book._watches.values():
        w.last_poll_ts = 0.0
        w.poll_interval_sec = 0
    # Resolve instrument
    book._instrument_store = SimpleNamespace(
        intent_creation_details=lambda *a, **k: inst
    )
    book._router.instrument_store = book._instrument_store
    placed = book.tick()
    assert placed == 1
    assert not book.has_pending()
    assert router.process_intent.called

    # Re-arm then stop on open
    assert book.maybe_arm_from_main_sl(
        strategy=strategy,
        instrument=inst,
        structure_id="BTCZeroDTE:BTCUSD:2026-07-20:CE",
        metadata_extras=meta,
        qty=10,
        side="BUY",
        price=27.0,
    )
    book.on_position_opened(instrument=inst, strategy_id="BTCZeroDTE")
    assert not book.has_pending()


def test_premium_above_cost_waits(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    router = MagicMock()
    router._logs_root = tmp_path / "logs"
    router.position_manager = SimpleNamespace(positions={})
    router.intent_store = SimpleNamespace(has_pending_intent=lambda **k: False)
    router.process_intent = MagicMock(return_value={"ok": True})
    book = ReentryAtCostBook(router, persist_path=str(tmp_path / "reentry2.json"))
    book.set_premium_fn(lambda *a, **k: 20.0)  # above cost 14
    strategy = SimpleNamespace(
        name="BTCZeroDTE",
        reentry_at_cost={"enabled": True, "max_reentries": 1},
        underlying_symbols=["BTCUSD"],
        reentry_at_cost_allowed=lambda meta: True,
    )
    inst = SimpleNamespace(
        trading_symbol="C-BTC-65000-210726",
        strike=65000.0,
        expiry="210726",
        option_type="CE",
        exchange="DELTA",
    )
    meta = {
        "strategy_meta": {
            "symbol": "BTCUSD",
            "entry_premium": 14.0,
            "reentry_count": 0,
            "reentry_at_cost": {"enabled": True},
        },
        "reentry_at_cost": {"enabled": True},
    }
    book.maybe_arm_from_main_sl(
        strategy=strategy,
        instrument=inst,
        structure_id="sid",
        metadata_extras=meta,
        qty=10,
        side="BUY",
    )
    for w in book._watches.values():
        w.last_poll_ts = 0.0
        w.poll_interval_sec = 0
    assert book.tick() == 0
    assert book.has_pending()
    assert not router.process_intent.called
