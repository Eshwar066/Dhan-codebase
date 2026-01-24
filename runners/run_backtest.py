"""
Backtest runner. Data from Dhan API only (core.api.DhanDataProvider).
Run from project root: python runners/run_backtest.py
"""
import datetime
import os
import sys

# project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.api.dhan_data import DhanDataProvider


def main():
    client_code = os.environ.get("DHAN_CLIENT_CODE", "YOUR_CLIENT_CODE")
    access_token = os.environ.get("DHAN_ACCESS_TOKEN", "YOUR_ACCESS_TOKEN")

    data = DhanDataProvider(client_code, access_token)
    from_date = "2025-01-01"
    to_date = datetime.datetime.now().strftime("%Y-%m-%d")

    # Example: load OHLC from Dhan and run strategy logic (placeholder)
    df = data.get_historical_data("NIFTY", "NSE", 30)
    if df is not None and not df.empty:
        print("Backtest data from Dhan:", df.shape)
    else:
        print("No Dhan data. Set DHAN_CLIENT_CODE, DHAN_ACCESS_TOKEN. Backtest logic: plug in strategy.")


if __name__ == "__main__":
    main()
