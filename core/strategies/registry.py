# core/strategies/registry.py
# Strategy wiring is generated from core/strategies/**/strategy.yaml
# Regenerate: python -m tools.strategy_manifest generate
from __future__ import annotations

from typing import Any, Dict, Optional

from core.instruments import EquityInstrument, FutureInstrument, OptionInstrument
from core.strategies._generated.aliases import GENERATED_STRATEGY_ALIASES
from core.strategies._generated.registry_entries import GENERATED_STRATEGY_MAP

INSTRUMENT_MAP = {
    "EQUITY": EquityInstrument,
    "OPTION": OptionInstrument,
    "FUTURE": FutureInstrument,
}

STRATEGY_MAP: Dict[str, Dict[str, Any]] = dict(GENERATED_STRATEGY_MAP)

STRATEGY_ALIASES: Dict[str, str] = dict(GENERATED_STRATEGY_ALIASES)


def resolve_registry_key(name: str) -> Optional[str]:
    """Resolve config or class ``name`` to canonical ``STRATEGY_MAP`` key."""
    key = str(name or "").strip()
    if not key:
        return None
    if key in STRATEGY_MAP:
        return key
    alias = STRATEGY_ALIASES.get(key)
    if alias and alias in STRATEGY_MAP:
        return alias
    for reg_key, cfg in STRATEGY_MAP.items():
        cls = cfg.get("strategy")
        if cls is not None and getattr(cls, "name", None) == key:
            return reg_key
    return None


def get_strategy_config(name: str) -> Optional[Dict[str, Any]]:
    reg_key = resolve_registry_key(name)
    if not reg_key:
        return None
    return STRATEGY_MAP.get(reg_key)
