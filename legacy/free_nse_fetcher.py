"""
Free NSE data (nsepy / nsepython). Not Dhan.
Use core.api.DhanDataProvider for Dhan as single source of truth.
"""

import datetime
import pandas as pd
from nsepy import get_history
from nsepy.derivatives import get_expiry_date
from nsepython import equity_history


class FreeNSEFetcher:
    def __init__(self, logger=None):
        self.logger = logger

    def get_historical_data(
        self,
        tradingsymbol: str,
        exchange: str,
        days: int,
        instrument_type: str = None,
        strike_price: float = None,
        option_type: str = None,
    ) -> pd.DataFrame:
        try:
            from_date = datetime.datetime.now() - datetime.timedelta(days=days)
            to_date = datetime.datetime.now()

            if exchange != "NSE":
                print("⚠️ Only NSE supported in free API")
                return None

            if instrument_type is None:
                ohlc = get_history(symbol=tradingsymbol, start=from_date, end=to_date)
            else:
                expiry = get_expiry_date(year=to_date.year, month=to_date.month)
                ohlc = get_history(
                    symbol=tradingsymbol,
                    start=from_date,
                    end=to_date,
                    option_type=option_type,
                    strike_price=strike_price,
                    expiry_date=expiry,
                    futures=instrument_type.upper().startswith("FUT"),
                )

            if ohlc.empty:
                print("😵‍💫 No data returned")
                return None

            ohlc.reset_index(inplace=True)
            if "Date" in ohlc.columns:
                ohlc["Date"] = pd.to_datetime(ohlc["Date"])
            elif "Expiry" in ohlc.columns:
                ohlc["Expiry"] = pd.to_datetime(ohlc["Expiry"])

            return ohlc

        except Exception as e:
            print(f"Exception in historical data: {e}")
            if self.logger:
                self.logger.exception(e)
            return None

    def get_intraday_data(self, tradingsymbol, exchange, timeframe=1):
        try:
            if exchange != "NSE":
                print("⚠️ Only NSE supported in free API")
                return None

            today = datetime.datetime.now().strftime("%d-%m-%Y")
            raw = equity_history(symbol=tradingsymbol, series="EQ", start_date=today, end_date=today)

            if raw is None:
                print("😵‍💫 NSE returned None")
                return None

            if isinstance(raw, dict):
                if "data" not in raw or not raw["data"]:
                    print("😵‍💫 No 'data' key in NSE response")
                    return None
                df = pd.DataFrame(raw["data"])
            else:
                df = raw.copy()

            if df.empty:
                print("😵‍💫 Empty intraday dataframe")
                return None

            df.columns = [c.upper() for c in df.columns]
            required_cols = {"DATE", "TIME", "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME"}
            if not required_cols.issubset(df.columns):
                print("😵‍💫 Required columns missing:", df.columns)
                return None

            df["DateTime"] = pd.to_datetime(df["DATE"] + " " + df["TIME"])
            df.set_index("DateTime", inplace=True)
            df.rename(columns={"OPEN": "Open", "HIGH": "High", "LOW": "Low", "CLOSE": "Close", "VOLUME": "Volume"}, inplace=True)

            if timeframe != 1 and timeframe in [2, 3, 5, 10, 15, 30, 60]:
                df = df.resample(f"{timeframe}T").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()

            return df

        except Exception as e:
            print(f"Exception in intraday data: {e}")
            if getattr(self, "logger", None):
                self.logger.exception(e)
            return None
