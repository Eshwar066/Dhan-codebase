"""
Live trading runner. Data and orders via Dhan (Tradehull).
Run from project root: python runners/run_live.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Dhan_Tradehull import Tradehull


def main():
    client_code = os.environ.get("DHAN_CLIENT_CODE", "YOUR_CLIENT_CODE")
    access_token = os.environ.get("DHAN_ACCESS_TOKEN", "YOUR_ACCESS_TOKEN")

    tsl = Tradehull(client_code, access_token)
    bal = tsl.get_balance()
    print("Live balance:", bal)
    # strategy / order logic here


if __name__ == "__main__":
    main()
