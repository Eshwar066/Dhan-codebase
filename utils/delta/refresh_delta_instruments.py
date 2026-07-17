#!/usr/bin/env python3
"""Download the current Delta India product master into Dependencies."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.utils.instruments.delta import fetch_delta_products  # noqa: E402


IST = ZoneInfo("Asia/Kolkata")


def refresh(output_dir: Path, base_url: str) -> Path:
    products = fetch_delta_products(base_url)
    if products.empty or "symbol" not in products.columns:
        raise RuntimeError("Delta returned no usable products")

    output_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(IST).strftime("%Y-%m-%d")
    destination = output_dir / f"delta_instrument_{today}.csv"
    temporary = destination.with_suffix(".csv.tmp")
    products.to_csv(temporary, index=False, float_format="%.2f")
    temporary.replace(destination)

    for old in output_dir.glob("delta_instrument_*.csv"):
        if old != destination:
            old.unlink(missing_ok=True)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "Dependencies",
        help="Instrument cache directory",
    )
    parser.add_argument(
        "--base-url",
        default="https://api.india.delta.exchange",
        help="Delta REST API base URL",
    )
    args = parser.parse_args()
    destination = refresh(args.output_dir.resolve(), str(args.base_url))
    print(f"Downloaded Delta instrument master: {destination}")


if __name__ == "__main__":
    main()
