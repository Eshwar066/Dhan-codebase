"""Strategy plugin manifest: load strategy.yaml → generate registry wiring."""

from tools.strategy_manifest.loader import StrategyManifest, discover_manifests, load_manifest

__all__ = ["StrategyManifest", "discover_manifests", "load_manifest"]
