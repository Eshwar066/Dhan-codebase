"""
Dhan API as single source of truth for market data.
- get_instrument_file: instrument master from Dhan (https://images.dhan.co/api-data/api-scrip-master.csv)
- DhanDataProvider: get_historical_data, get_intraday_data, resample_timeframe
"""

import os
import time
import datetime
import traceback
import pandas as pd
from typing import Optional

DHAN_SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"


def get_instrument_file(deps_dir: str = "Dependencies") -> pd.DataFrame:
    """Fetch instrument master from Dhan; use local cache when same-day file exists."""
    current_date = time.strftime("%Y-%m-%d")
    expected_file = "all_instrument " + str(current_date) + ".csv"
    deps_path = os.path.join(deps_dir, expected_file)

    for item in os.listdir(deps_dir):
        if item.startswith("all_instrument") and " " in item:
            part = item.split(" ")[1]
            if current_date not in part:
                old_path = os.path.join(deps_dir, item)
                if os.path.isfile(old_path):
                    try:
                        os.remove(old_path)
                    except OSError:
                        pass

    if os.path.isfile(deps_path):
        try:
            return pd.read_csv(deps_path, low_memory=False)
        except Exception:
            pass
    df = pd.read_csv(DHAN_SCRIP_MASTER_URL, low_memory=False)
    df.to_csv(deps_path, index=False)
    return df


class DhanDataProvider:
    """Market data from Dhan API only. Used by backtest, paper, and live."""

    def __init__(self, client_code: str, access_token: str, deps_dir: str = "Dependencies"):
        from dhanhq import dhanhq

        self.client_code = client_code
        self.access_token = access_token
        self.Dhan = dhanhq(client_code, access_token)
        self.instrument_df = get_instrument_file(deps_dir)

    def convert_to_date_time(self, t):
        return self.Dhan.convert_to_date_time(t)

    def get_historical_data(
        self, tradingsymbol: str, exchange: str, days: int
    ) -> Optional[pd.DataFrame]:
        try:
            from_date = (
                datetime.datetime.now() - datetime.timedelta(days=days)
            ).strftime("%Y-%m-%d")
            to_date = datetime.datetime.now().strftime("%Y-%m-%d")

            script_exchange = {
                "NSE": self.Dhan.NSE,
                "BSE": self.Dhan.BSE,
                "NFO": self.Dhan.NSE_FNO,
                "BFO": self.Dhan.BSE_FNO,
                "MCX": self.Dhan.MCX,
                "CUR": self.Dhan.CUR,
            }
            instrument_exchange = {
                "NSE": "NSE", "BSE": "BSE", "NFO": "NSE", "BFO": "BSE",
                "MCX": "MCX", "CUR": "NSE",
            }
            exchangeSegment = script_exchange[exchange]

            row = self.instrument_df[
                (
                    (self.instrument_df["SEM_TRADING_SYMBOL"] == tradingsymbol)
                    | (self.instrument_df["SEM_CUSTOM_SYMBOL"] == tradingsymbol)
                )
                & (self.instrument_df["SEM_EXM_EXCH_ID"] == instrument_exchange[exchange])
            ]
            if row.empty:
                return None

            security_id = str(row.iloc[-1]["SEM_SMST_SECURITY_ID"])
            instrument_type = row.iloc[-1]["SEM_INSTRUMENT_NAME"]

            if exchange in ["NSE", "BSE"]:
                ohlc = self.Dhan.historical_daily_data(
                    security_id, exchangeSegment, instrument_type, from_date, to_date
                )
            else:
                expiry_code = str(row.iloc[-1]["SEM_EXPIRY_CODE"])
                ohlc = self.Dhan.historical_daily_data(
                    security_id, exchangeSegment, instrument_type,
                    expiry_code, from_date, to_date,
                )

            if not ohlc or ohlc.get("status") != "success":
                return None

            df = pd.DataFrame(ohlc["data"])
            if df.empty:
                return None

            for col in ["start_Time", "start_time", "timestamp", "date", "datetime"]:
                if col in df.columns:
                    df[col] = df[col].apply(self.convert_to_date_time)
                    break
            return df
        except Exception:
            traceback.print_exc()
            return None

    def get_intraday_data(
        self,
        tradingsymbol: str,
        exchange: str,
        timeframe: int,
        from_date: str,
        to_date: str,
    ) -> Optional[pd.DataFrame]:
        try:
            available_frames = {
                2: "2T", 3: "3T", 5: "5T", 10: "10T", 15: "15T", 30: "30T", 60: "60T",
            }
            script_exchange = {
                "NSE": self.Dhan.NSE, "NFO": self.Dhan.NSE_FNO, "BFO": self.Dhan.BSE_FNO,
                "CUR": self.Dhan.CUR, "BSE": self.Dhan.BSE,
            }
            instrument_exchange = {
                "NSE": "NSE", "BSE": "BSE", "NFO": "NSE", "BFO": "BSE",
                "MCX": "MCX", "CUR": "NSE",
            }
            exchangeSegment = script_exchange[exchange]

            security_id = self.instrument_df[
                (
                    (self.instrument_df["SEM_TRADING_SYMBOL"] == tradingsymbol)
                    | (self.instrument_df["SEM_CUSTOM_SYMBOL"] == tradingsymbol)
                )
                & (self.instrument_df["SEM_EXM_EXCH_ID"] == instrument_exchange[exchange])
            ].iloc[-1]["SEM_SMST_SECURITY_ID"]

            instrument_type = self.instrument_df[
                (
                    (self.instrument_df["SEM_TRADING_SYMBOL"] == tradingsymbol)
                    | (self.instrument_df["SEM_CUSTOM_SYMBOL"] == tradingsymbol)
                )
                & (self.instrument_df["SEM_EXM_EXCH_ID"] == instrument_exchange[exchange])
            ].iloc[-1]["SEM_INSTRUMENT_NAME"]

            ohlc = self.Dhan.intraday_minute_data(
                str(security_id), exchangeSegment, instrument_type, from_date, to_date
            )

            if not ohlc or "data" not in ohlc or not isinstance(ohlc["data"], list) or len(ohlc["data"]) == 0:
                return None

            df = pd.DataFrame(ohlc["data"])
            if df.empty:
                return None

            time_col = "date" if "date" in df.columns else "start_Time"
            if time_col in df.columns:
                df[time_col] = df[time_col].apply(self.convert_to_date_time)

            if timeframe == 1:
                return df

            if timeframe not in available_frames:
                return df

            df = self.resample_timeframe(df, available_frames[timeframe])
            return df
        except Exception:
            traceback.print_exc()
            return None

    def resample_timeframe(self, df: pd.DataFrame, timeframe: str = "5T") -> pd.DataFrame:
        time_col = "start_Time" if "start_Time" in df.columns else "date"
        if time_col not in df.columns:
            return df
        df = df.copy()
        df[time_col] = pd.to_datetime(df[time_col])
        df.set_index(time_col, inplace=True)
        earliest_time = df.index.min()
        desired_start_time = earliest_time.replace(hour=9, minute=15, second=0, microsecond=0)

        if earliest_time < desired_start_time:
            adjusted_start_time = desired_start_time
        else:
            step_min = int("".join(c for c in timeframe if c.isdigit()) or "5")
            adjusted_start_time = desired_start_time + pd.DateOffset(
                minutes=((earliest_time - desired_start_time).seconds // 60 // step_min) * step_min
            )

        resampled = df.resample(timeframe, origin=adjusted_start_time).agg({
            "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
        })
        resampled.reset_index(inplace=True)
        return resampled
