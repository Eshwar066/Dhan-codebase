"""Cross-check manifests against strategy classes."""

from __future__ import annotations

import importlib
from typing import List, Tuple

from tools.strategy_manifest.schema import StrategyManifest


def _import_strategy_class(manifest: StrategyManifest):
    mod = importlib.import_module(manifest.implementation.module)
    cls = getattr(mod, manifest.implementation.class_name, None)
    if cls is None:
        raise ValueError(
            f"{manifest.id}: class {manifest.implementation.class_name!r} "
            f"not found in {manifest.implementation.module}"
        )
    return cls


def validate_manifest(manifest: StrategyManifest) -> List[str]:
    """Return list of warnings/errors (empty = ok)."""
    issues: List[str] = []

    try:
        cls = _import_strategy_class(manifest)
    except Exception as exc:
        issues.append(f"{manifest.id}: import failed: {exc}")
        return issues

    class_name = getattr(cls, "name", None)
    if class_name != manifest.id:
        issues.append(
            f"{manifest.id}: class.name={class_name!r} != manifest.id={manifest.id!r}"
        )

    if manifest.symbols is not None:
        underlying = getattr(cls, "underlying_symbols", None) or []
        underlying_set = {str(s).strip().upper() for s in underlying}
        if underlying_set:
            for sym in manifest.symbols:
                if sym not in underlying_set:
                    issues.append(
                        f"{manifest.id}: profile symbol {sym!r} not in "
                        f"class.underlying_symbols={sorted(underlying_set)!r}"
                    )

    if manifest.schedule.eval_mode == "scheduled" and not manifest.schedule.times:
        issues.append(f"{manifest.id}: scheduled eval_mode requires schedule.times")

    if manifest.data:
        has_default = "default" in manifest.data
        for mode in manifest.allowed_modes:
            mode_key = mode.lower()
            if not has_default and mode_key not in manifest.data:
                issues.append(
                    f"{manifest.id}: allowed_mode {mode} has no data.{mode_key} "
                    f"or data.default block"
                )

    return issues


def validate_all(manifests: List[StrategyManifest], *, strict: bool = True) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []

    ids = [m.id for m in manifests]
    if len(ids) != len(set(ids)):
        errors.append("duplicate manifest ids detected")

    for manifest in manifests:
        for issue in validate_manifest(manifest):
            if strict:
                errors.append(issue)
            else:
                warnings.append(issue)

    return errors, warnings
