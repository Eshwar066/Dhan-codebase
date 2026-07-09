"""Resolve strategy.yaml subscriptions for live engine bus wiring."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set


def _strategy_id(strategy: Any) -> str:
    return str(getattr(strategy, "name", "") or "").strip()


def get_subscription_table() -> Dict[str, Dict[str, Any]]:
    try:
        from core.strategies._generated.subscriptions import (
            GENERATED_STRATEGY_SUBSCRIPTIONS,
        )

        return dict(GENERATED_STRATEGY_SUBSCRIPTIONS)
    except Exception:
        return {}


def resolve_strategy_subscriptions(
    strategy: Any,
    table: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Return resolved subscriptions dict for one strategy (empty if unknown)."""
    sid = _strategy_id(strategy)
    if not sid:
        return {}
    table = table if table is not None else get_subscription_table()
    raw = table.get(sid)
    if isinstance(raw, dict):
        return dict(raw)
    # Fallback when generated table missing: infer from runtime attrs
    eval_mode = str(getattr(strategy, "eval_mode", "") or "live_feed").strip()
    timeframe = getattr(strategy, "timeframe", None)
    symbols = list(getattr(strategy, "underlying_symbols", None) or [])
    has_gtt = bool(getattr(strategy, "gtt_fallback", None))
    live_feed = eval_mode != "scheduled"
    tfs = [str(timeframe)] if timeframe else []
    return {
        "BarClosed": {"enabled": live_feed, "timeframes": tfs, "symbols": symbols},
        "ScheduledSlot": {"enabled": not live_feed, "symbols": symbols},
        "QuoteUpdated": {"enabled": has_gtt, "symbols": symbols},
        "IntentCreated": {"enabled": True},
        "IntentFilled": {"enabled": True},
        "PositionClosed": {"enabled": True},
        "FeedDisconnected": {"enabled": True},
        "FeedRecovered": {"enabled": True},
    }


def event_enabled(subs: Dict[str, Any], event_name: str) -> bool:
    entry = subs.get(event_name)
    if not isinstance(entry, dict):
        return False
    return bool(entry.get("enabled"))


def collect_enabled_events(
    strategies: Iterable[Any],
    table: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Set[str]:
    """Union of enabled event names across loaded strategies."""
    table = table if table is not None else get_subscription_table()
    enabled: Set[str] = set()
    for strategy in strategies:
        subs = resolve_strategy_subscriptions(strategy, table)
        for name, entry in subs.items():
            if isinstance(entry, dict) and entry.get("enabled"):
                enabled.add(str(name))
    return enabled


def bar_closed_filter_for_strategies(
    strategies: Iterable[Any],
    table: Optional[Dict[str, Dict[str, Any]]] = None,
):
    """
    Build an EventBus filter_fn for BarClosed.

    Passes when any loaded strategy that subscribed to BarClosed matches
    timeframe (if declared) and symbol (if declared). Empty filter lists
    mean "any".
    """
    table = table if table is not None else get_subscription_table()
    specs: List[Dict[str, Any]] = []
    for strategy in strategies:
        subs = resolve_strategy_subscriptions(strategy, table)
        entry = subs.get("BarClosed")
        if not isinstance(entry, dict) or not entry.get("enabled"):
            continue
        specs.append(
            {
                "timeframes": {
                    str(t).strip() for t in (entry.get("timeframes") or []) if str(t).strip()
                },
                "symbols": {
                    str(s).strip().upper()
                    for s in (entry.get("symbols") or [])
                    if str(s).strip()
                },
            }
        )

    if not specs:
        return lambda _event: False

    def _filter(event) -> bool:
        payload = getattr(event, "payload", None) or {}
        tf = str(payload.get("timeframe") or "").strip()
        sym = str(payload.get("symbol") or "").strip().upper()
        for spec in specs:
            tfs = spec["timeframes"]
            syms = spec["symbols"]
            if tfs and tf and tf not in tfs:
                continue
            if syms and sym and sym not in syms:
                continue
            return True
        return False

    return _filter
