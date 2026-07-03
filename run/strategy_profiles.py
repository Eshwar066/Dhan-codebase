"""
Per-strategy defaults: symbols, live/backtest venue settings, eval mode, Delta flags.

Engine jobs in ``run/config.py`` list only which strategies run together; this module
supplies strategy-level settings merged by ``resolve_engine_job``.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional

from core.strategies.registry import STRATEGY_MAP

# Registry key -> strategy-level profile (not engine/process settings).
STRATEGY_PROFILES: Dict[str, Dict[str, Any]] = {
    "LEAPS_RSI": {
        "symbols": ["NIFTY"],
        "exchange": "NSE",
        "eval_mode": "live_feed",
        "live": {"exchange": "INDEX", "sector": "YES", "rsi": "YES"},
        "backtest": {
            "start_date": "2026-01-01",
            "end_date": "2026-05-24",
            "timeframe": "60",
            "exchange": "INDEX",
            "sector": "YES",
        },
    },
    "BankNiftyBTST": {
        "symbols": ["BANKNIFTY"],
        "exchange": "NSE",
        "eval_mode": "scheduled",
        "live": {"exchange": "INDEX", "sector": "YES"},
        "backtest": {
            "start_date": "2026-01-02",
            "end_date": "2026-02-19",
            "timeframe": "5",
            "exchange": "INDEX",
            "sector": "YES",
        },
    },
    "OIPositionalBuy": {
        "symbols": ["NIFTY"],
        "exchange": "NSE",
        "live": {"exchange": "INDEX", "sector": "YES"},
        "backtest": {
            "start_date": "2026-04-01",
            "end_date": "2026-04-28",
            "timeframe": "15",
            "exchange": "INDEX",
            "sector": "YES",
        },
    },
    "NiftyIntradayMagicalLine": {
        "symbols": ["NIFTY"],
        "exchange": "NSE",
        "live": {"exchange": "INDEX", "sector": "YES"},
        "backtest": {
            "start_date": "2026-01-02",
            "end_date": "2026-02-19",
            "timeframe": "15",
            "exchange": "INDEX",
            "sector": "YES",
        },
    },
    "FuturesEMAHighLow": {
        "symbols": ["NIFTY"],
        "exchange": "NSE",
        "live": {"exchange": "INDEX", "sector": "YES"},
        "backtest": {
            "start_date": "2024-02-01",
            "end_date": "2026-03-02",
            "timeframe": "60",
            "exchange": "INDEX",
            "sector": "YES",
        },
    },
    "MagicalLines": {
        "symbols": ["NIFTY"],
        "exchange": "NSE",
        "live": {"exchange": "INDEX", "sector": "YES"},
        "backtest": {
            "start_date": "2026-01-01",
            "end_date": "2026-02-19",
            "timeframe": "DAY",
            "exchange": "INDEX",
            "sector": "YES",
        },
    },
    "IPOBreakout": {
        "symbols": None,
        "exchange": "NSE",
        "live": {
            "exchange": "NSE",
            "sector": "NO",
            "ipo_days": 365,
            "ipo_filter": {"price_above": 200, "volume_above": 500000},
            "ipo_max_symbols": 50,
        },
        "backtest": {
            "start_date": "2022-01-01",
            "end_date": "2026-02-20",
            "timeframe": "DAY",
            "exchange": "NSE",
            "sector": "NO",
            "ipo_days": 365,
            "ipo_filter": {"price_above": 200, "volume_above": 500000},
            "ipo_max_symbols": 50,
            "ipo_fallback_symbols": ["RELIANCE"],
        },
    },
    "SignalFloodTest": {
        "live": {"exchange": "INDEX", "sector": "YES"},
        "backtest": {
            "start_date": "2024-03-20",
            "end_date": "2024-03-25",
            "timeframe": "1",
            "exchange": "INDEX",
            "sector": "YES",
        },
    },
    "OneDayMagicalLine": {
        "symbols": ["BTCUSD"],
        "exchange": "NSE",
        "delta": {"india": True, "testnet": False, "leverage": 10},
        "live": {"exchange": "DELTA", "sector": "YES"},
        "backtest": {
            "start_date": "2026-02-01",
            "end_date": "2026-02-26",
            "timeframe": "60",
            "exchange": "DELTA",
            "sector": "YES",
        },
    },
    "Futures_EMA_Momentum": {
        "symbols": ["BTCUSD"],
        "delta": {"india": True, "testnet": False, "leverage": 1},
        "live": {"exchange": "INDEX", "sector": "YES"},
        "backtest": {
            "start_date": "2024-09-01",
            "end_date": "2026-03-13",
            "timeframe": "60",
            "exchange": "INDEX",
            "sector": "YES",
        },
    },
    "RSIBreadAndButter": {
        "symbols": ["BTCUSD"], # ,"ETHUSD"
        "delta": {"india": True, "testnet": False, "leverage": 5},
        "live": {"exchange": "DELTA", "sector": "YES"},
        "backtest": {
            "start_date": "2026-07-02",
            "end_date": "2026-07-03",
            "timeframe": "1",
            "exchange": "DELTA",
            "sector": "YES",
        },
    },
    "LiquiditySweepStrategy": {
        "symbols": ["BTCUSD"],
        "delta": {"india": True, "testnet": False, "leverage": 5},
        "live": {"exchange": "DELTA", "sector": "YES"},
        "backtest": {
            "start_date": "2026-06-02",
            "end_date": "2026-07-03",
            "timeframe": "1",
            "exchange": "DELTA",
            "sector": "YES",
        },
    },
}


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
