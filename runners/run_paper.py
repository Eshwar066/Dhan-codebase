"""
Paper trading runner. Data and simulated orders; no live execution.
Data: Dhan (core.api). Broker: PaperBroker.
Run from project root: python runners/run_paper.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.api.dhan_data import DhanDataProvider
from core.broker.paper import PaperBroker


def main():
    client_code = os.environ.get("DHAN_CLIENT_CODE", "YOUR_CLIENT_CODE")
    access_token = os.environ.get("DHAN_ACCESS_TOKEN", "YOUR_ACCESS_TOKEN")

    broker = PaperBroker(client_code, access_token)
    data = broker.data  # DhanDataProvider

    # Example: fetch from Dhan, place paper order
    df = data.get_historical_data("NIFTY", "NSE", 5)
    if df is not None and not df.empty:
        print("Paper data from Dhan:", df.shape)
    oid = broker.place_order("NIFTY", "NSE", 50, 0, 0, "MARKET", "BUY", "MIS")
    print("Paper order id:", oid)


if __name__ == "__main__":
    main()
