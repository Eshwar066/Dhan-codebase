"""
Standard helpers for ``OrderIntent.metadata_extras`` / persisted strategy_meta.

New strategies should use ``pack_strategy_meta`` so engine hooks can resolve
underlying symbols without hard-coded key lists in ``live_engine``.
Legacy per-strategy keys remain readable via ``unpack_strategy_meta``.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from core.strategies._generated.meta_keys import (
    GENERATED_LEGACY_META_KEYS,
    GENERATED_META_ALIASES,
)

STRATEGY_META_KEY = "strategy_meta"

LEGACY_META_KEYS: Dict[str, str] = dict(GENERATED_LEGACY_META_KEYS)

LEGACY_META_ALIASES: Dict[str, str] = dict(GENERATED_META_ALIASES)


def legacy_meta_key(registry_key: str) -> Optional[str]:
    return LEGACY_META_KEYS.get(str(registry_key or "").strip())


def pack_strategy_meta(registry_key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Canonical envelope plus legacy top-level key when mapped."""
    key = str(registry_key or "").strip()
    body = dict(payload or {})
    out: Dict[str, Any] = {
        STRATEGY_META_KEY: {"strategy": key, **body},
    }
    legacy = legacy_meta_key(key)
    if legacy:
        out[legacy] = body
    return out


def unpack_strategy_meta(
    metadata_extras: Any,
    registry_key: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Read strategy payload from canonical or legacy metadata shapes."""
    if not isinstance(metadata_extras, dict):
        return None

    canonical = metadata_extras.get(STRATEGY_META_KEY)
    if isinstance(canonical, dict):
        return dict(canonical)

    if registry_key:
        legacy = legacy_meta_key(registry_key)
        if legacy:
            raw = metadata_extras.get(legacy)
            if isinstance(raw, dict):
                return dict(raw)

    for alias, canonical_legacy in LEGACY_META_ALIASES.items():
        raw = metadata_extras.get(alias)
        if isinstance(raw, dict):
            return dict(raw)

    for legacy in LEGACY_META_KEYS.values():
        raw = metadata_extras.get(legacy)
        if isinstance(raw, dict):
            return dict(raw)

    return None


def underlying_from_metadata(metadata_extras: Any) -> Optional[str]:
    """Extract underlying symbol from any known metadata shape."""
    payload = unpack_strategy_meta(metadata_extras)
    if isinstance(payload, dict):
        sym = payload.get("symbol")
        if sym:
            return str(sym).strip().upper() or None

    if not isinstance(metadata_extras, dict):
        return None

    for key in list(LEGACY_META_KEYS.values()) + list(LEGACY_META_ALIASES.keys()):
        block = metadata_extras.get(key)
        if isinstance(block, dict) and block.get("symbol"):
            return str(block["symbol"]).strip().upper() or None

    canonical = metadata_extras.get(STRATEGY_META_KEY)
    if isinstance(canonical, dict) and canonical.get("symbol"):
        return str(canonical["symbol"]).strip().upper() or None

    return None
