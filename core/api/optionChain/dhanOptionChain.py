import requests
import pandas as pd
from datetime import datetime


class DhanOptionChain:
    BASE_URL = "https://api.dhan.co/v2"

    def __init__(self, client_id: str, access_token: str):
        self.client_id = client_id
        self.access_token = access_token

        self.headers = {
            "access-token": self.access_token,
            "client-id": self.client_id,
            "Content-Type": "application/json",
        }

    def get_option_chain(self, underlying_scrip: int, underlying_seg: str, expiry: str):
        """
        Fetch option chain for given underlying and expiry
        """

        payload = {
            "UnderlyingScrip": underlying_scrip,
            "UnderlyingSeg": underlying_seg,
            "Expiry": expiry,
        }

        url = f"{self.BASE_URL}/optionchain"

        response = requests.post(url, headers=self.headers, json=payload, timeout=10)
        response.raise_for_status()

        data = response.json()

        if "data" not in data:
            raise ValueError(f"Invalid Option Chain response: {data}")

        return data["data"]

    def option_chain_to_df(self, oc_data: dict) -> pd.DataFrame:
        """
        Convert option chain JSON into flat DataFrame
        """

        records = []
        underlying_ltp = oc_data.get("last_price")

        for strike, strike_data in oc_data["oc"].items():
            strike = float(strike)

            for opt_type in ["ce", "pe"]:
                if opt_type not in strike_data:
                    continue

                opt = strike_data[opt_type]

                record = {
                    "strike": strike,
                    "type": opt_type.upper(),
                    "underlying_ltp": underlying_ltp,
                    "ltp": opt.get("last_price"),
                    "oi": opt.get("oi"),
                    "prev_oi": opt.get("previous_oi"),
                    "volume": opt.get("volume"),
                    "iv": opt.get("implied_volatility"),
                    "bid_price": opt.get("top_bid_price"),
                    "bid_qty": opt.get("top_bid_quantity"),
                    "ask_price": opt.get("top_ask_price"),
                    "ask_qty": opt.get("top_ask_quantity"),
                    "delta": opt["greeks"].get("delta"),
                    "theta": opt["greeks"].get("theta"),
                    "gamma": opt["greeks"].get("gamma"),
                    "vega": opt["greeks"].get("vega"),
                }

                records.append(record)

        return pd.DataFrame(records)

    def get_upcoming_expirylist(self, underlying_scrip: int, underlying_seg: str):
        """
        Fetch expiry list
        """

        payload = {
            "UnderlyingScrip": underlying_scrip,
            "UnderlyingSeg": underlying_seg,
        }

        url = f"{self.BASE_URL}/optionchain/expirylist"

        response = requests.post(url, headers=self.headers, json=payload, timeout=10)
        response.raise_for_status()

        data = response.json()

        if "data" not in data:
            raise ValueError(f"Invalid Option Chain expiry response: {data}")

        return data["data"]

    def get_rolling_optionchain(
        self,
        security_id: int,
        exchange_segment: str,
        interval: str,
        instrument: str,
        expiry_flag: str,
        expiry_code: int,
        strike: str,
        option_type: str,
        from_date: str,
        to_date: str,
        required_data=None,
    ):
        """
        Fetch rolling option chain data (expired contracts)

        expiry_flag : WEEK | MONTH
        expiry_code : 1 = nearest expiry, 2 = next, etc
        strike      : ATM | numeric strike (e.g. "18000")
        option_type : CALL | PUT
        """

        if required_data is None:
            required_data = ["strike", "spot", "open", "high", "low", "close", "volume"]

        payload = {
            "exchangeSegment": exchange_segment,
            "interval": interval,
            "securityId": security_id,
            "instrument": instrument,
            "expiryFlag": expiry_flag,
            "expiryCode": expiry_code,
            "strike": strike,
            "drvOptionType": option_type,
            "requiredData": required_data,
            "fromDate": from_date,
            "toDate": to_date,
        }

        url = f"{self.BASE_URL}/charts/rollingoption"

        response = requests.post(url, headers=self.headers, json=payload, timeout=10)
        response.raise_for_status()

        result = response.json()

        if "data" not in result:
            raise ValueError(f"Invalid rolling option response: {result}")

        return result["data"]

    def rolling_option_to_df(self, rolling_data: dict, option_type: str = "CALL"):
        import pandas as pd
        import numpy as np

        key = "ce" if option_type.upper() == "CALL" else "pe"

        if key not in rolling_data or not rolling_data[key]:
            return pd.DataFrame()

        data = rolling_data[key]

        timestamps = data.get("timestamp", [])
        if not timestamps:
            return pd.DataFrame()

        df = pd.DataFrame({"timestamp": timestamps})

        n = len(df)

        def safe_col(values):
            if isinstance(values, list) and len(values) == n:
                return values
            return [np.nan] * n

        for col in [
            "open",
            "high",
            "low",
            "close",
            "volume",
            "oi",
            "iv",
            "spot",
            "strike",
        ]:
            df[col] = safe_col(data.get(col))

        # Convert timestamp
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="s")
        df.set_index("datetime", inplace=True)
        df.drop(columns=["timestamp"], inplace=True)

        return df
