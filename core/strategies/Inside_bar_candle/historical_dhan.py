import pandas as pd
import datetime as dt

START_TIME = dt.time(9, 20)
END_TIME = dt.time(14, 30)


class HistoricalDhanData:
    def __init__(self, tsl):
        self.tsl = tsl

    def get_intraday(self, symbol, date):
        df = self.tsl.get_long_term_historical_data(
            tradingsymbol=symbol,
            exchange="NSE",
            timeframe="15",
            from_date=date.strftime("%Y-%m-%d"),
            to_date=date.strftime("%Y-%m-%d"),
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
        df = df[(df["time"] >= START_TIME) & (df["time"] <= END_TIME)]

        return df.reset_index(drop=True)
