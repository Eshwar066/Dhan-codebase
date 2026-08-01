"""CLI: python -m tools.strategy_manifest [bootstrap|generate|validate|check]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tools.strategy_manifest.bootstrap import bootstrap_manifests
from tools.strategy_manifest.emit import write_generated_files
from tools.strategy_manifest.loader import discover_manifests
from tools.strategy_manifest.validate import validate_all


def _cmd_bootstrap(args: argparse.Namespace) -> int:
    paths = bootstrap_manifests(force=args.force)
    if paths:
        print(f"Wrote {len(paths)} manifest(s):")
        for p in paths:
            print(f"  {p}")
    else:
        print("No manifests written (already exist; use --force to overwrite).")
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    manifests = discover_manifests()
    if not manifests:
        print("No strategy.yaml files found. Run: python -m tools.strategy_manifest bootstrap")
        return 1

    errors, warnings = validate_all(manifests, strict=not args.no_strict)
    for w in warnings:
        print(f"warning: {w}")
    if errors:
        for e in errors:
            print(f"error: {e}", file=sys.stderr)
        return 1

    readme_ids = None
    if args.readme:
        if args.readme == "all":
            readme_ids = [m.id for m in manifests]
        else:
            readme_ids = [s.strip() for s in args.readme.split(",") if s.strip()]

    written = write_generated_files(manifests, readme_ids=readme_ids)
    print(f"Generated {len(written)} file(s) from {len(manifests)} manifest(s).")
    for p in written:
        print(f"  {p}")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    manifests = discover_manifests()
    errors, warnings = validate_all(manifests, strict=True)
    for w in warnings:
        print(f"warning: {w}")
    if errors:
        for e in errors:
            print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"OK — {len(manifests)} manifest(s) valid.")
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    """Fail if generated files are stale vs manifests."""
    from tools.strategy_manifest.emit import (
        emit_aliases,
        emit_meta_keys,
        emit_profiles,
        emit_registry,
        emit_runtime_spec,
        emit_subscriptions,
    )

    manifests = discover_manifests()
    if not manifests:
        print("No manifests found.", file=sys.stderr)
        return 1

    errors, _ = validate_all(manifests, strict=True)
    if errors:
        for e in errors:
            print(f"error: {e}", file=sys.stderr)
        return 1

    gen_dir = Path(__file__).resolve().parents[2] / "core" / "strategies" / "_generated"
    expected = {
        "registry_entries.py": emit_registry(manifests),
        "profiles.py": emit_profiles(manifests),
        "runtime_spec.py": emit_runtime_spec(manifests),
        "meta_keys.py": emit_meta_keys(manifests),
        "aliases.py": emit_aliases(manifests),
        "subscriptions.py": emit_subscriptions(manifests),
    }
    stale = []
    for name, content in expected.items():
        path = gen_dir / name
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            stale.append(name)
    if stale:
        print("Stale generated files:", ", ".join(stale), file=sys.stderr)
        print("Run: python -m tools.strategy_manifest generate", file=sys.stderr)
        return 1
    print(f"OK — generated wiring matches {len(manifests)} manifest(s).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Strategy plugin manifest tooling")
    sub = parser.add_subparsers(dest="command", required=True)

    p_boot = sub.add_parser("bootstrap", help="Write initial strategy.yaml files")
    p_boot.add_argument("--force", action="store_true", help="Overwrite existing manifests")
    p_boot.set_defaults(func=_cmd_bootstrap)

    p_gen = sub.add_parser("generate", help="Generate registry/profile/runtime from manifests")
    p_gen.add_argument(
        "--readme",
        metavar="IDS",
        help="Regenerate readme.md for strategy id(s), comma-separated, or 'all'",
    )
    p_gen.add_argument(
        "--no-strict",
        action="store_true",
        help="Emit even when validation reports issues",
    )
    p_gen.set_defaults(func=_cmd_generate)

    sub.add_parser("validate", help="Validate all strategy.yaml files").set_defaults(
        func=_cmd_validate
    )

    sub.add_parser("check", help="Verify generated files are up to date").set_defaults(
        func=_cmd_check
    )

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
