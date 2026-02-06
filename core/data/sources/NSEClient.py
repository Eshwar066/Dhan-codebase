import requests
import json
import os
from datetime import datetime, date, timedelta
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

    # =========================
    # FILE CACHE
    # =========================
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

    # =========================
    # DATE UTILITIES
    # =========================

    # =========================
    # option chain cached data + if new date date is in between the cached date range will use same cached data
    # =========================
    def to_dd_mm_yyyy(self, value):
        if isinstance(value, (datetime, date)):
            return value.strftime("%d-%m-%Y")

        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value).strftime("%d-%m-%Y")
            except ValueError:
                return datetime.strptime(value, "%d-%b-%Y").strftime("%d-%m-%Y")

        raise TypeError(f"Invalid date type: {type(value)}")

    def to_dd_mmm_yyyy(self, value):
        if isinstance(value, date):
            return value.strftime("%d-%b-%Y").upper()

        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value).strftime("%d-%b-%Y").upper()
            except ValueError:
                return datetime.strptime(value, "%d-%b-%Y").strftime("%d-%b-%Y").upper()

        raise TypeError(f"Invalid expiry_date type: {type(value)}")

    def _ts_to_date(self, ts: str) -> date:
        """
        Supports:
        - '31-Mar-2022'
        - '2022-03-30T18:30:00.000+00:00'
        """
        try:
            return datetime.strptime(ts, "%d-%b-%Y").date()
        except ValueError:
            return datetime.fromisoformat(ts.split("T")[0]).date()

    # =========================
    # INTERNAL HELPERS
    # =========================
    def _slice_data(self, data, from_date, to_date):
        result = []
        for d in data:
            ts = d.get("FH_TIMESTAMP")
            if not ts:
                continue
            d_date = self._ts_to_date(ts)
            if from_date <= d_date <= to_date:
                result.append(d)
        return result

    def _fetch_option_data(
        self,
        symbol,
        from_date,
        to_date,
        instrumentType,
        expiry_date,
        strike,
        option_type,
        year,
    ):
        params = {
            "from": self.to_dd_mm_yyyy(from_date),
            "to": self.to_dd_mm_yyyy(to_date),
            "instrumentType": instrumentType,
            "symbol": symbol,
            "year": year,
            "expiryDate": self.to_dd_mmm_yyyy(expiry_date),
            "optionType": option_type,
            "strikePrice": strike,
        }

        r = self.session.get(BASE + HISTORICAL_API, params=params, timeout=self.timeout)
        r.raise_for_status()
        raw = r.json()

        # ---------- normalize ----------
        if raw is None:
            return []

        # wrapped response
        if isinstance(raw, dict):
            if "data" in raw and isinstance(raw["data"], list):
                raw = raw["data"]
            else:
                return []

        if not isinstance(raw, list):
            return []

        # ---------- hard filter ----------
        clean = [d for d in raw if isinstance(d, dict) and "FH_TIMESTAMP" in d]

        return clean

    # =========================
    # PUBLIC API
    # =========================
    def get_options_history(
        self,
        symbol,
        from_date,
        to_date,
        instrumentType,
        expiry_date,
        strike,
        option_type,
        year,
    ):
        OPTION_TYPE_MAP = {
            "CALL": "CE",
            "PUT": "PE",
            "CE": "CE",
            "PE": "PE",
        }
        option_type = OPTION_TYPE_MAP.get(option_type)
        if option_type is None:
            raise ValueError(f"Invalid option_type: {option_type}")

        # normalize dates
        if not isinstance(from_date, date):
            from_date = datetime.fromisoformat(str(from_date)).date()

        if not isinstance(to_date, date):
            to_date = datetime.fromisoformat(str(to_date)).date()

        expiry_key = self.to_dd_mmm_yyyy(expiry_date)
        cache_key = f"opt_{symbol}_{expiry_key}_{strike}_{option_type}_{year}"
        cached = self._load_cache(cache_key) or []
        cached = sorted(
            cached,
            key=lambda x: self._ts_to_date(x["FH_TIMESTAMP"]),
        )
        stitched = cached.copy()
        earliest = self._ts_to_date(cached[0]["FH_TIMESTAMP"]) if cached else None
        latest = self._ts_to_date(cached[-1]["FH_TIMESTAMP"]) if cached else None
        # fully covered
        if earliest and latest:
            if earliest <= from_date and latest >= to_date:
                return self._slice_data(stitched, from_date, to_date)

        # pdb.set_trace()
        # backward fetch
        if not earliest or from_date < earliest:
            fetch_to = (earliest - timedelta(days=1)) if earliest else to_date
            data = self._fetch_option_data(
                symbol,
                from_date,
                fetch_to,
                instrumentType,
                expiry_date,
                strike,
                option_type,
                year,
            )

            stitched = data + stitched

        # forward fetch
        if latest and to_date > latest:
            data = self._fetch_option_data(
                symbol,
                latest + timedelta(days=1),
                to_date,
                instrumentType,
                expiry_date,
                strike,
                option_type,
                year,
            )
            stitched += data

        # dedupe + sort
        stitched = sorted(
            {
                d["FH_TIMESTAMP"]: d
                for d in stitched
                if isinstance(d, dict) and "FH_TIMESTAMP" in d
            }.values(),
            key=lambda x: self._ts_to_date(x["FH_TIMESTAMP"]),
        )
        # pdb.set_trace()
        self._save_cache(cache_key, stitched)
        return self._slice_data(stitched, from_date, to_date)
