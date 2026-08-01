"""
Per-strategy defaults: symbols, live/backtest venue settings, eval mode, Delta flags.

Profiles are generated from ``core/strategies/**/strategy.yaml``.
Regenerate: ``python -m tools.strategy_manifest generate``
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional

from core.strategies._generated.profiles import STRATEGY_PROFILES as _GENERATED_PROFILES
from core.strategies.registry import STRATEGY_MAP

STRATEGY_PROFILES: Dict[str, Dict[str, Any]] = dict(_GENERATED_PROFILES)


def get_strategy_profile(strategy_name: str) -> Dict[str, Any]:
    return deepcopy(STRATEGY_PROFILES.get(str(strategy_name), {}))


def _symbols_from_strategy_class(strategy_name: str) -> List[str]:
    cfg = STRATEGY_MAP.get(strategy_name)
    if not cfg:
        return []
    inst = cfg["strategy"]()
    allowed = getattr(inst, "underlying_symbols", None) or []
    return [str(s).strip().upper() for s in allowed if str(s).strip()]


def symbols_for_strategy(strategy_name: str) -> Optional[List[str]]:
    profile = STRATEGY_PROFILES.get(str(strategy_name), {})
    if "symbols" in profile:
        raw = profile["symbols"]
        if raw is None:
            return None
        return [str(s).strip().upper() for s in raw if str(s).strip()]
    from_class = _symbols_from_strategy_class(strategy_name)
    return from_class or None


def collect_engine_symbols(strategy_names: List[str]) -> Optional[List[str]]:
    """Union of strategy symbols; ``None`` when universe-driven (e.g. IPO)."""
    out: List[str] = []
    universe = False
    for name in strategy_names:
        syms = symbols_for_strategy(name)
        if syms is None:
            universe = True
            continue
        for sym in syms:
            if sym not in out:
                out.append(sym)
    if universe and not out:
        return None
    return out or None


def _merge_live_dicts(dicts: List[Optional[Dict[str, Any]]]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for block in dicts:
        if not isinstance(block, dict):
            continue
        for key, value in block.items():
            if key not in merged:
                merged[key] = value
            elif key == "rsi" and str(value).upper() == "YES":
                merged[key] = "YES"
            elif isinstance(merged.get(key), dict) and isinstance(value, dict):
                merged[key] = {**merged[key], **value}
    return merged


def _merge_backtest_dicts(
    primary: Dict[str, Any], overrides: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    base = dict(primary or {})
    if isinstance(overrides, dict):
        base.update(overrides)
    return base


def build_strategy_eval_map(
    strategy_names: List[str], job_override: Optional[Dict[str, str]] = None
) -> Dict[str, str]:
    if isinstance(job_override, dict) and job_override:
        return dict(job_override)
    out: Dict[str, str] = {}
    for name in strategy_names:
        em = STRATEGY_PROFILES.get(name, {}).get("eval_mode")
        if em:
            out[name] = str(em)
    return out


def resolve_engine_job(job: dict) -> dict:
    """
    Merge engine job with strategy profiles.

    Engine job keeps: engine_id, venue, run_mode, enabled, capital, risk limits,
    telegram, strategies, and optional overrides (symbols, backtest dates, delta_*, etc.).
    """
    strategies = list(job.get("strategies") or [])
    if not strategies and job.get("name"):
        strategies = [str(job["name"])]
    if not strategies:
        raise ValueError(
            f"Engine job {job.get('engine_id')!r} must list at least one strategy."
        )

    primary = str(strategies[0])
    primary_profile = get_strategy_profile(primary)
    resolved = dict(job)
    resolved["strategies"] = strategies

    if "symbols" not in job:
        resolved["symbols"] = collect_engine_symbols(strategies)

    if "exchange" not in job:
        resolved["exchange"] = primary_profile.get("exchange", "NSE")

    if "live" not in job:
        live_blocks = [get_strategy_profile(n).get("live") for n in strategies]
        resolved["live"] = _merge_live_dicts(live_blocks)
    elif isinstance(job.get("live"), dict):
        base = _merge_live_dicts([get_strategy_profile(n).get("live") for n in strategies])
        base.update(job["live"])
        resolved["live"] = base

    profile_bt = dict(primary_profile.get("backtest") or {})
    if "backtest" not in job:
        resolved["backtest"] = profile_bt
    else:
        resolved["backtest"] = _merge_backtest_dicts(profile_bt, job.get("backtest"))

    if "strategy_eval" not in job:
        eval_map = build_strategy_eval_map(strategies)
        if eval_map:
            resolved["strategy_eval"] = eval_map

    venue = str(job.get("venue", "DHAN")).upper()
    if venue == "DELTA":
        delta_block = dict(primary_profile.get("delta") or {})
        if "delta_india" not in job and "india" in delta_block:
            resolved["delta_india"] = bool(delta_block["india"])
        if "delta_testnet" not in job and "testnet" in delta_block:
            resolved["delta_testnet"] = bool(delta_block["testnet"])
        if "delta_leverage" not in job and "leverage" in delta_block:
            resolved["delta_leverage"] = delta_block["leverage"]

    return resolved
