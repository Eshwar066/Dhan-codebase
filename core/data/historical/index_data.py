import pandas as pd
import datetime as dt

START_TIME = dt.time(9, 10)
END_TIME = dt.time(15, 30)


class IndexHistoricalData:
    """
        Reusable for ALL index-based and stock strategies
        ✅ Can be used by:
            RSI strategy
            MACD trend
            VWAP
            Breakout
            Any index strategy
    """

    def __init__(self, tsl):    
        self.tsl = tsl

    def get_ohlc(
        self, symbol, timeframe="60", start_date=None, end_date=None, exchange="INDEX"
    ):
        df = self.tsl.get_long_term_historical_data(
            tradingsymbol=symbol,
            exchange=exchange,
            timeframe=timeframe,
            from_date=start_date,
            to_date=end_date,
        )

        if df is None or df.empty:
            return None

        # Normalize timestamp
        for col in ("timestamp", "date", "start_Time"):
            if col in df.columns:
                df["timestamp"] = pd.to_datetime(df[col])
                break
        else:
            return None

        df = df.sort_values("timestamp").reset_index(drop=True)

        # Market hours filter
        df["time"] = df["timestamp"].dt.time
        df = df[(df["time"] >= START_TIME) & (df["time"] <= END_TIME)]

        return df.reset_index(drop=True)
