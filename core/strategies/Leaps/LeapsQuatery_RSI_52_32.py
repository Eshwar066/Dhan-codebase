import talib
import pandas as pd
import pdb
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
    timeframe = "60"

    # Engine will auto-populate these via runtime_spec
    required_context = ["option_chain"]

    # def __init__(self):
    def should_evaluate(self, candle) -> bool:
        """
        Lightweight pre-check before building full context.
        Only allow evaluation when RSI is in trade zone.
        """

        rsi = candle.get("rsi")

        # No RSI yet
        if rsi is None or pd.isna(rsi):
            return False

        # Only evaluate when signal possible
        if rsi < 32 or rsi > 52:
            return True

        return False

    def _is_valid_time(self, ts):
        return ts.strftime("%H:%M") in VALID_TIMES

    def on_candle(self, candle, ctx):

        ts = pd.to_datetime(candle["timestamp"])
        date = ts.date()
        symbol = candle["symbol"]
        rsi = candle.get("rsi")

        if not self._is_valid_time(ts):
            return None

        # ---------- Stage 1: Expiry Selection ----------
        if "option_chain" not in ctx:
            expiry_list = ctx.get("expiry_list")
            expiry_index = self.select_expiry(expiry_list, date)

            return {"selected_expiry": expiry_index}

        # ---------- Stage 2: Trading Logic ----------
        option_chain = ctx["option_chain"]
        atm_strike, oc_df, expiry, expiry_list = option_chain["chain"]
        pdb.set_trace()
        if rsi < 32:
            return Position(
                symbol=symbol,
                side="SELL",
                option_type="CALL",
                expiry=expiry,
                qty=1000,
                entry_time=ts,
                meta={"signal": "RSI_BELOW_32"},
            )

        if rsi > 52:
            return Position(
                symbol=symbol,
                side="SELL",
                option_type="PUT",
                expiry=expiry,
                qty=1000,
                entry_time=ts,
                meta={"signal": "RSI_ABOVE_52"},
            )

        return None

    def select_expiry(self, expiry_list, date):
        target_month, target_year = self.select_expiryMonth(date)

        # Convert once
        expiry_dates = [pd.to_datetime(e).date() for e in expiry_list]

        # Collect matching indices
        matches = [
            i
            for i, e in enumerate(expiry_dates)
            if e.month == target_month and e.year == target_year
        ]

        if not matches:
            return None  # or fallback index

        # Monthly expiry = LAST one in that month
        return matches[-1]

    def select_expiryMonth(self, trade_date):
        year = trade_date.year
        month = trade_date.month
        day = trade_date.day

        quarters = [3, 6, 9, 12]
        cutoffs = {2: 15, 5: 15, 8: 20, 11: 20}

        # next quarter
        q = next((m for m in quarters if m > month), 3)
        if q == 3 and month > 9:
            year += 1

        # cutoff shift
        if month in cutoffs and day > cutoffs[month]:
            q = quarters[(quarters.index(q) + 1) % 4]
            if q == 3:
                year += 1

        return q, year

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
