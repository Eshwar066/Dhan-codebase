import talib
import pandas as pd
from collections import deque
from core.models.position import Position
from core.strategies.base import BaseStrategy
from core.utils.expiry_calendar import Expiry_Calendar


VALID_TIMES = {"10:15", "11:15", "12:15", "13:15", "14:15", "15:15"}


class LeapsQuarterly(BaseStrategy):
    """
    Quarterly option selling strategy based on RSI regime.
    SIGNAL ONLY — execution handled by engine/broker.
    """

    name = "LEAPS_RSI"

    # Engine will auto-populate these via runtime_spec
    required_context = ["option_chain", "expiry"]

    def __init__(self):
        self.buffer = deque(maxlen=50)  # keep enough candles for RSI

    def prepare_indicators(self, df):
        df["rsi"] = talib.RSI(df["close"], 14)
        return df

    def _is_valid_time(self, ts):
        return ts.strftime("%H:%M") in VALID_TIMES

    def on_candle(self, candle, ctx, portfolio):
        """
        candle: dict (OHLCV + timestamp + symbol)
        ctx: runtime context built by BaseEngine
        """

        ts = pd.to_datetime(candle["timestamp"])
        symbol = candle["symbol"]

        # -------- Time Filter --------
        if not self._is_valid_time(ts):
            return None

        # -------- Maintain buffer --------
        self.buffer.append(candle)

        if len(self.buffer) < 15:
            return None

        df = pd.DataFrame(self.buffer)
        rsi = df.iloc[-1]["rsi"]

        if pd.isna(rsi):
            return None

        expiry = ctx.get("expiry")
        option_chain = ctx.get("option_chain")

        # -------- RSI < 32 → SELL CALL --------
        if rsi < 32 and not portfolio.has_position(symbol, "CALL"):
            return Position(
                symbol=symbol,
                side="SELL",
                option_type="CALL",
                expiry=expiry,
                qty=1000,
                entry_time=ts,
                meta={
                    "signal": "RSI_BELOW_32",
                    "regime": "BEARISH",
                },
            )

        # -------- RSI > 52 → SELL PUT --------
        if rsi > 52 and not portfolio.has_position(symbol, "PUT"):
            return Position(
                symbol=symbol,
                side="SELL",
                option_type="PUT",
                expiry=expiry,
                qty=1000,
                entry_time=ts,
                meta={
                    "signal": "RSI_ABOVE_52",
                    "regime": "BULLISH",
                },
            )

        return None

    def should_exit(self, position, candle, ctx=None):
        rsi = candle.get("rsi")
        ts = pd.to_datetime(candle["timestamp"])

        # -------- RSI regime exit --------
        if position.option_type == "CALL" and rsi > 52:
            return True

        if position.option_type == "PUT" and rsi < 32:
            return True

        # -------- Hedge rollover exit --------
        if Expiry_Calendar.is_hedge_rollover_day(ts):
            return True

        return False
