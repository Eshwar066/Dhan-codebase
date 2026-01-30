import talib
import pandas as pd
from collections import deque

# from core.models import Position
from core.strategies.base import BaseStrategy


class InsideBarStrategy(BaseStrategy):
    name = "INSIDE_BAR"
    required_context = []  # no extra data needed

    def __init__(self):
        self.buffer = deque(maxlen=5)  # rolling candles

    def prepare_indicators(self, df):
        df["rsi"] = talib.RSI(df["close"], 14)
        return df

    def on_candle(self, candle, ctx, portfolio):
        """
        candle = dict with OHLCV + timestamp + symbol
        """

        self.buffer.append(candle)

        if len(self.buffer) < 5:
            return None

        # Convert buffer → DataFrame (small, cheap)
        df = pd.DataFrame(self.buffer)

        base = df.iloc[0]
        inside = df.iloc[1]
        last = df.iloc[2]
        current = df.iloc[3]

        if pd.isna(last["rsi"]):
            return None

        inside_candle = inside["high"] < base["high"] and inside["low"] > base["low"]

        if not inside_candle:
            return None

        symbol = candle["symbol"]

        # -------- BUY --------
        if last["rsi"] > 60 and current["high"] > base["high"]:
            return Position(
                symbol=symbol,
                side="BUY",
                qty=100,
                entry_price=current["close"],
                entry_time=current["timestamp"],
                sl=last["low"],
                target=None,
                status="OPEN",
            )

        # -------- SELL --------
        if last["rsi"] < 40 and current["low"] < base["low"]:
            return Position(
                symbol=symbol,
                side="SELL",
                qty=100,
                entry_price=current["close"],
                entry_time=current["timestamp"],
                sl=last["high"],
                target=None,
                status="OPEN",
            )

        return None

    def should_exit(self, position, candle, ctx=None):
        if position.side == "BUY" and candle["close"] <= position.sl:
            return True

        if position.side == "SELL" and candle["close"] >= position.sl:
            return True

        return False
