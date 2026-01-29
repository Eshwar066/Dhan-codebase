from core.data.sources.dhan_source import DhanSource
from core.utils.session.session_manager import SessionManager
import datetime as dt
import pandas as pd
import talib as ta
import math
import pdb


class CandleService:
    def __init__(self, data_source):
        self.data_source = data_source
        self.last_processed = {}
        self.next_fetch_time = {}

    def get_latest_closed(self, symbol, timeframe, exchange, sector, rsi):

        now = SessionManager._now(exchange)
        # if not SessionManager.is_market_open(exchange):
        #     return None
        # ---------- Throttle API calls ----------
        next_time = self.next_fetch_time.get(symbol)
        if next_time and now < next_time:
            return None

        start_date, end_date = self._get_intraday_range(timeframe, 100)

        candles = self.data_source.get_intraday(
            symbol=symbol,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            exchange=exchange,
            sector=sector,
        )

        if candles is None or candles.empty or len(candles) < 2:
            return None
            
        # RSI attachment
        if bool(rsi):
            candles = self.attach_RSIindicators(candles)

        pdb.set_trace()
        # ---------- Choose closed candle ----------
        is_open = SessionManager.is_market_open(exchange)
        closed = candles.iloc[-2] if is_open else candles.iloc[-1]

        if int(closed["volume"]) <= 0:
            return None

        ts = closed["timestamp"]

        # ---------- Boolean gate ----------
        last_ts = self.last_processed.get(symbol)

        is_new_candle = (last_ts is None) or (ts > last_ts)

        if not is_new_candle:
            return None

        # ---------- Save state ----------
        self.last_processed[symbol] = ts

        tf_min = self._tf_to_minutes(timeframe)
        self.next_fetch_time[symbol] = ts + dt.timedelta(minutes=tf_min)

        return closed

    def _tf_to_minutes(self, tf):
        tf = str(tf).lower()
        if tf.endswith("h"):
            return int(tf[:-1]) * 60
        return int(tf)

    def attach_RSIindicators(self, df):
        df["rsi"] = ta.RSI(df["close"], timeperiod=14)
        return df

    def _get_intraday_range(self, timeframe, num_candles=100):
        """
        Calculates start_date and end_date for intraday candles,
        ensuring we fetch at least `num_candles` candles up to now.
        timeframe: string like "1" for 1min, "5" for 5min, "60" for 1hr
        Returns: start_date, end_date as string "YYYY-MM-DD"
        """
        now = dt.datetime.now()
        market_open = now.replace(hour=9, minute=0, second=0, microsecond=0)
        market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)

        if now < market_open:
            # before market opens, go to previous trading day
            end_date = (now - dt.timedelta(days=1)).date()
        else:
            end_date = now.date()

        # Number of trading minutes per day
        total_mins_per_day = (15 * 60 + 30) - (9 * 60)  # 9:00-15:30 = 390 min
        tf_minutes = int(timeframe) if timeframe.isdigit() else 60  # 60 if "60"
        candles_per_day = math.floor(total_mins_per_day / tf_minutes)

        # How many past days needed to get num_candles
        days_needed = math.ceil(num_candles / candles_per_day)

        start_date = end_date - dt.timedelta(days=days_needed)

        return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")
