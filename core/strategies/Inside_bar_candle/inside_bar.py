import talib
import pandas as pd
from core.portfolio import Position


class InsideBarStrategy:
    def prepare_indicators(self, df):
        df["rsi"] = talib.RSI(df["close"], 14)
        return df

    def on_candle(self, idx, df, portfolio):
        if idx < 4:
            return None

        base = df.iloc[idx - 4]
        inside = df.iloc[idx - 3]
        last = df.iloc[idx - 2]
        current = df.iloc[idx - 1]

        if pd.isna(last["rsi"]):
            return None

        inside_candle = inside["high"] < base["high"] and inside["low"] > base["low"]

        if not inside_candle:
            return None

        symbol = df["symbol"].iloc[0]

        # BUY
        if last["rsi"] > 60 and current["high"] > base["high"]:
            return Position(
                symbol=symbol,
                side="BUY",
                entry_price=current["close"],
                qty=100,
                entry_time=current["timestamp"],
                sl=last["low"],
            )

        # SELL
        if last["rsi"] < 40 and current["low"] < base["low"]:
            return Position(
                symbol=symbol,
                side="SELL",
                entry_price=current["close"],
                qty=100,
                entry_time=current["timestamp"],
                sl=last["high"],
            )

        return None

    def should_exit(self, pos, candle):
        if pos.side == "BUY" and candle["close"] <= pos.sl:
            return True
        if pos.side == "SELL" and candle["close"] >= pos.sl:
            return True
        return False
