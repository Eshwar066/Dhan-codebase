"""
Run quarterly report from strategy trades CSV.

Usage:
  python -m run.run_quarterly_report [path] [margin_utilized] [lot_size]

Example:
  python -m run.run_quarterly_report logs/FuturesEMAHighLow_trades.csv 400000 150
"""

import sys

# Add project root for imports
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from core.analytics.quarterly_report import print_quarterly_report


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "logs/FuturesEMAHighLow_trades.csv"
    margin = float(sys.argv[2]) if len(sys.argv) > 2 else 400_000.0
    lot = float(sys.argv[3]) if len(sys.argv) > 3 else 150.0
    print_quarterly_report(path, margin_utilized=margin, lot_size=lot, pnl_is_currency=True)


if __name__ == "__main__":
    main()
