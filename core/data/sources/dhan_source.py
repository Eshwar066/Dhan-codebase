import os
import sys
import pandas as pd
from dotenv import load_dotenv
from Dhan_Tradehull import Tradehull
import pdb

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

load_dotenv()


class DhanSource:
    def __init__(self):
        client_id = os.getenv("DHAN_CLIENT_CODE")
        access_token = os.getenv("DHAN_ACCESS_TOKEN")

        if not client_id or not access_token:
            raise RuntimeError("❌ Dhan credentials missing")

        self.tsl = Tradehull(client_id, access_token)

    def get_intraday(self, symbol, start_date, end_date, timeframe, exchange, sector):
        df = self.tsl.get_long_term_historical_data(
            tradingsymbol=symbol,
            exchange=exchange,
            timeframe=timeframe,
            from_date=start_date,
            to_date=end_date,
            sector=sector,
        )

        if df is None or df.empty:
            return None

        # Normalize timestamp
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
        elif "date" in df.columns:
            df["timestamp"] = pd.to_datetime(df["date"])
        elif "start_Time" in df.columns:
            df["timestamp"] = pd.to_datetime(df["start_Time"])
        else:
            return None

        df = df.sort_values("timestamp").reset_index(drop=True)

        # Market hours filter
        df["time"] = df["timestamp"].dt.time
        # df = df[(df["time"] >= START_TIME) & (df["time"] <= END_TIME)]

        return df.reset_index(drop=True)

    def expiry_list(self, symbol, exchange):
        expiry_list = self.tsl.get_expiry_list(Underlying=symbol, exchange=exchange)
        return expiry_list

    def get_expired_optionchain(
        self,
        symbol,
        monthlyExpiryDate,
        exchange,
        interval,
        expiry_flag,
        expiry_code,
        strike,
        option_type,
        from_date,
        to_date,
    ):
        data = self.tsl.get_expired_option_data(
            tradingsymbol=symbol,
            exchange=exchange,
            interval=interval,  # 1-hour candle
            expiry_flag=expiry_flag,  # Monthly expiry
            expiry_code=expiry_code,  # March 2023 expiry (check your DHAN expiry sequence)
            strike=strike,  # OTM strike relative to ATM
            option_type=option_type,
            from_date=from_date,  # start of month
            to_date=to_date,  # expiry date
        )

        return data
