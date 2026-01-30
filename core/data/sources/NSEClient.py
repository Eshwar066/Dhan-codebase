import requests
import json
import os
from datetime import datetime
import pdb

BASE = "https://www.nseindia.com"
EXPIRY_API = "/api/historicalOR/meta/foCPV/expireDts"
HISTORICAL_API = "/api/historicalOR/foCPV"

CACHE_DIR = "data_cache"
os.makedirs(CACHE_DIR, exist_ok=True)


class NSEClient:

    def __init__(self, timeout=5):
        self.timeout = timeout
        self.headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "Referer": "https://www.nseindia.com",
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        # Make initial request to set cookies
        self.session.get(BASE, timeout=self.timeout)

    # ---------- CACHE ----------
    def _cache_path(self, name):
        return f"{CACHE_DIR}/{name}.json"

    def _load_cache(self, name):
        path = self._cache_path(name)
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
        return None

    def _save_cache(self, name, data):
        with open(self._cache_path(name), "w") as f:
            json.dump(data, f, indent=2)

    # =========================================================
    # ✅ EXPIRIES
    # =========================================================
    def get_expiries(self, symbol, year, instrument="OPTIDX"):
        """
        instrument:
            OPTIDX → options
            FUTIDX → futures
        """

        cache_key = f"expiries_{instrument}_{symbol}_{year}"
        cached = self._load_cache(cache_key)
        if cached:
            return cached

        params = {
            "instrument": instrument,
            "symbol": symbol,
            "year": year,
        }

        url = BASE + EXPIRY_API
        r = self.session.get(url, params=params, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()

        expiries = [
            datetime.strptime(d, "%d-%b-%Y").strftime("%Y-%m-%d")
            for d in data.get("expiresDts", [])
        ]

        self._save_cache(cache_key, expiries)
        return expiries

    # =========================================================
    # ✅ FUTURES HISTORICAL
    # =========================================================
    def get_futures_history(self, symbol, from_date, to_date, expiry_date, year):
        """
        Dates format:
            from/to → DD-MM-YYYY
            expiry_date → DD-MMM-YYYY (31-DEC-2020)
        """
        cache_key = f"fut_{symbol}_{expiry_date}_{from_date}_{to_date}"
        cached = self._load_cache(cache_key)
        if cached:
            return cached

        params = {
            "from": from_date,
            "to": to_date,
            "instrumentType": "FUTIDX",
            "symbol": symbol,
            "year": year,
            "expiryDate": expiry_date,
        }

        url = BASE + HISTORICAL_API
        r = self.session.get(url, params=params, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()

        self._save_cache(cache_key, data)
        return data

    # =========================================================
    # ✅ OPTIONS HISTORICAL
    # =========================================================
    def get_options_history(
        self, symbol, from_date, to_date, expiry_date, strike, option_type, year
    ):
        """
        option_type → CE / PE
        expiry_date → DD-MMM-YYYY
        """
        cache_key = f"opt_{symbol}_{expiry_date}_{strike}_{option_type}"
        cached = self._load_cache(cache_key)
        if cached:
            return cached

        params = {
            "from": from_date,
            "to": to_date,
            "instrumentType": "OPTIDX",
            "symbol": symbol,
            "year": year,
            "expiryDate": expiry_date,
            "optionType": option_type,
            "strikePrice": strike,
        }

        url = BASE + HISTORICAL_API
        r = self.session.get(url, params=params, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()

        self._save_cache(cache_key, data)
        return data
