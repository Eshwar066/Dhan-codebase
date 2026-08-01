"""Discover and load strategy.yaml manifests."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from tools.strategy_manifest.schema import StrategyManifest, parse_manifest

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore


REPO_ROOT = Path(__file__).resolve().parents[2]
STRATEGIES_ROOT = REPO_ROOT / "core" / "strategies"
MANIFEST_FILENAME = "strategy.yaml"


def discover_manifest_paths(root: Optional[Path] = None) -> List[Path]:
    base = root or STRATEGIES_ROOT
    return sorted(base.rglob(MANIFEST_FILENAME))


def load_manifest(path: Path) -> StrategyManifest:
    if yaml is None:
        raise RuntimeError(
            "PyYAML is required. Install with: pip install PyYAML"
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        raise ValueError(f"empty manifest: {path}")
    return parse_manifest(raw, source_path=path)


def discover_manifests(root: Optional[Path] = None) -> List[StrategyManifest]:
    manifests: List[StrategyManifest] = []
    for path in discover_manifest_paths(root):
        manifests.append(load_manifest(path))
    manifests.sort(key=lambda m: m.id)
    return manifests


def manifests_by_id(manifests: List[StrategyManifest]) -> Dict[str, StrategyManifest]:
    out: Dict[str, StrategyManifest] = {}
    for m in manifests:
        if m.id in out:
            raise ValueError(f"duplicate manifest id: {m.id}")
        out[m.id] = m
    return out
