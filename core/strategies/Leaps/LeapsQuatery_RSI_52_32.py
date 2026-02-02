import talib
import pandas as pd
import pdb
from collections import deque
import uuid
import datetime as dt

# from core.models.position import Position
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

    def prepare_indicators(self, df):
        df["rsi"] = talib.RSI(df["close"], 14)
        return df

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

    def build_option_symbol(self, symbol, expiry, strike, option_type):
        """
        Output:
        NIFTY 30 MAR 25000 PUT
        NIFTY 30 MAR 25000 CALL
        """

        # normalize expiry
        if isinstance(expiry, str):
            expiry = dt.datetime.strptime(expiry, "%Y-%m-%d").date()
        elif isinstance(expiry, dt.datetime):
            expiry = expiry.date()

        day = f"{expiry.day:02d}"  # 30
        month = expiry.strftime("%b").upper()  # MAR

        strike = int(float(strike))

        # --- normalize option type ---
        opt = option_type.upper()
        option_map = {
            "CE": "CALL",
            "PE": "PUT",
            "CALL": "CALL",
            "PUT": "PUT",
        }

        if opt not in option_map:
            raise ValueError(f"Invalid option_type: {option_type}")

        option_type = option_map[opt]
        return f"{symbol.upper()} {day} {month} {strike} {option_type}"

    def on_candle(self, candle, ctx):

        ts = pd.to_datetime(candle["timestamp"])
        date = ts.date()
        symbol = candle["symbol"]
        rsi = candle.get("rsi")

        # if not self._is_valid_time(ts):
        #     return None

        # ---------- Stage 1: Expiry Selection ----------
        if not ctx.get("option_chain"):
            expiry_list = ctx.get("expiry_list")
            expiry_date = self.select_expiry(expiry_list, date)
            Expiry_date = expiry_date.strftime("%Y-%m-%d")
            # pdb.set_trace()
            return {"selected_expiry": expiry_date}

        # ---------- Stage 2: Trading Logic ----------
        option_chain = ctx["option_chain"]
        pdb.set_trace()
        chain = option_chain.get("chain")
        # if not chain or len(chain) != 3:
        #     return None

        atm_strike, oc_df, expiry_date = chain
        pdf.set_trace()
        if oc_df is None or oc_df.empty:
            return None

        # option_chain = ctx["option_chain"]
        # pdb.set_trace()
        # atm_strike, oc_df, Expiry_date = option_chain["chain"]
        # pdb.set_trace()
        df_Optionchain = oc_df[
            [
                "CE Delta",
                "CE Theta",
                "CE LTP",
                "Strike Price",
                "PE LTP",
                "PE Theta",
                "PE Delta",
            ]
        ]
        pdf.set_trace()

        if rsi < 32:
            filtered = df_Optionchain[
                (df_Optionchain["Strike Price"] % 500 == 0)
                & (df_Optionchain["CE LTP"].between(300, 400))
            ]
            return null

        if rsi > 52:
            filtered = df_Optionchain[
                (df_Optionchain["Strike Price"] % 500 == 0)
                & (df_Optionchain["PE LTP"].between(200, 400))
            ]
            pdb.set_trace()
            if filtered.empty:
                print("filtered option strike didnt found")
                return None

            row = filtered.iloc[(filtered["PE LTP"] - 350).abs().argsort()[:1]].iloc[0]
            instrument_store = ctx["instrument_store"]
            tradingSymbol = self.build_option_symbol(
                symbol, Expiry_date, float(row["Strike Price"]), "PE"
            )
            # pdb.set_trace()
            if not tradingSymbol:
                print("Leaps no tradingSymbol found")
                return None
            inst = instrument_store.intent_creation_details(tradingSymbol, "NSE")
            # pdb.set_trace()
            if not inst["SEM_TRADING_SYMBOL"]:
                print("Leaps no intrument row")
                return None

            intent = self.map_instrument_to_intent(
                inst, strategy="LEAPS_RSI", side="SELL", strike_row=row
            )
            # pdb.set_trace()

            return intent

    # create_exit_intent
    #  create this

    def map_instrument_to_intent(
        self,
        inst,
        strike_row,
        strategy="LEAPS_RSI",
        side="SELL",
    ):
        """
        Map a Dhan instrument row to an intent dictionary.

        Args:
            row (pd.Series): instrument row from instrument_df
            strategy (str): strategy name
            side (str): BUY or SELL
            qty (int): quantity to trade

        Returns:
            dict: intent ready for order placement
        """

        trading_symbol = inst["SEM_CUSTOM_SYMBOL"]  # e.g., NIFTY-Mar2026-24500-PE
        symbol = inst["SEM_CUSTOM_SYMBOL"].split()[0]
        expiry_date = inst["SEM_EXPIRY_DATE"]
        strike_price = float(inst["SEM_STRIKE_PRICE"])
        option_type = inst["SEM_OPTION_TYPE"]
        lot_size = int(inst["SEM_LOT_UNITS"])
        segment = inst["SEM_SEGMENT"]
        exchange = inst["SEM_EXM_EXCH_ID"]
        option_map = {"CE": "CALL", "PE": "PUT"}
        reverse_option_map = {"CALL": "CE", "PUT": "PE"}
        option_type_mapped = option_map.get(option_type.upper(), option_type.upper())
        tick_size = float(inst["SEM_TICK_SIZE"]) or 1.0
        ltp = strike_row.get(
            f"{option_type} LTP",
            0.0,
        )  # if column exists
        price = round(float(ltp) / tick_size) * tick_size if ltp else 0.0
        intent = {
            "intent_id": uuid.uuid4().hex,
            "trading_symbol": trading_symbol,
            "symbol": symbol,
            "expiry": str(expiry_date),
            "side": side,
            "option_type": option_type_mapped,
            "strike": strike_price,
            "price": price,
            "qty": 1,
            "strategy": strategy,
            "trade_type": "MARGIN",
            "disclosed_quantity": 0,
            "after_market_order": False,
            "validity": "DAY",
            "amo_time": "OPEN",
            "bo_profit_value": None,
            "bo_stop_loss_value": None,
            "tag": f"{strategy} intent",
            "exchange": exchange,
            "lot_size": lot_size,
            "segment": segment,
        }
        # pdb.set_trace()
        return intent

    def select_expiry(self, expiry_list, date):
        if not expiry_list:
            print("⚠️ Expiry list is empty! Cannot select expiry.")
            return None

        target_month, target_year = self.select_expiryMonth(date)

        # Convert once
        expiry_dates = [pd.to_datetime(e).date() for e in expiry_list]

        # Find matching indices
        matches = [
            i
            for i, e in enumerate(expiry_dates)
            if e.month == target_month and e.year == target_year
        ]

        if not matches:
            return None

        # Monthly expiry = LAST one in that month
        selected_index = matches[-1]

        # ✅ Return expiry date
        return expiry_dates[selected_index]

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
