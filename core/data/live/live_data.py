import pandas as pd
import datetime as dt


class LiveData:

    def __init__(self, tsl):
        self.tsl = tsl
        self.last_ts = None

    # -------------------------------------------------
    # Warmup / Historical candles
    # -------------------------------------------------
    def expiry_list(self, symbol, exchange):
        expiry_list = self.tsl.get_expiry_list(Underlying=symbol, exchange=exchange)
        return expiry_list


    

    # -------------------------------------------------
    # Live candle (latest closed)
    # -------------------------------------------------
    def get_latest_candle(self):
        """
        Called continuously by LiveEngine
        Returns ONE closed candle
        """
        df = self.tsl.get_intraday_data(
            symbol="NIFTY",
            exchange="NSE",
            interval="1h",
        )

        if df is None or df.empty:
            return None

        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df.sort_values("timestamp", inplace=True)

        candle = df.iloc[-1]

        # Avoid duplicates
        if self.last_ts is not None and candle["timestamp"] <= self.last_ts:
            return None

        self.last_ts = candle["timestamp"]

        return {
            "timestamp": candle["timestamp"],
            "open": float(candle["open"]),
            "high": float(candle["high"]),
            "low": float(candle["low"]),
            "close": float(candle["close"]),
            "volume": int(candle.get("volume", 0)),
            "is_closed": True,  # important for LiveEngine
        }
