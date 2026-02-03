import talib
import pandas as pd
import uuid
import datetime as dt
import pdb

from run.config import RUN_MODE, RunMode
from core.strategies.base import BaseStrategy

# from core.utils.expiry_calendar import Expiry_Calendar
from core.utils.expiry_resolver import ExpiryResolver

VALID_TIMES = {"10:15", "11:15", "12:15", "13:15", "14:15", "15:15"}


class LeapsQuarterly(BaseStrategy):
    """
    LEAPS Quarterly RSI Option Selling Strategy
    SIGNAL ONLY
    """

    name = "LEAPS_RSI"
    timeframe = "60"
    required_context = ["option_chain"]
    api = "DHAN"
    expiryType = "QUARTERLY"
    strike_count = 5
    # --------------------------------------------------
    # INDICATORS
    # --------------------------------------------------

    def prepare_indicators(self, df):
        df["rsi"] = talib.RSI(df["close"], 14)
        df["prev_rsi"] = df["rsi"].shift(1)
        return df

    # --------------------------------------------------
    # TIME FILTER
    # --------------------------------------------------

    def _is_valid_time(self, ts):
        return ts.strftime("%H:%M") in VALID_TIMES

    # --------------------------------------------------
    # ENTRY SIGNAL
    # --------------------------------------------------

    def should_evaluate(self, candle):
        rsi = candle.get("rsi")
        prev = candle.get("prev_rsi")

        if pd.isna(rsi) or pd.isna(prev):
            return False

        # regime flip
        if prev >= 32 and rsi < 32:
            return True

        if prev <= 52 and rsi > 52:
            return True

        return False

    # --------------------------------------------------
    # MAIN ENTRY
    # --------------------------------------------------

    def on_candle(self, candle, ctx):
        ts = pd.to_datetime(candle["timestamp"])

        # time gate
        if not self._is_valid_time(ts):
            return None

        rsi = candle["rsi"]

        # decide direction
        if rsi < 32:
            option_type = "CE"
            ltp_range = (200, 400)
        elif rsi > 52:
            option_type = "PE"
            ltp_range = (200, 400)
        else:
            return None

        chain = self.fetch_option_chain(candle, ctx, option_type)
        pdb.set_trace()
        if not chain:
            return None

        atm, oc_df, expiry = chain["chain"]

        ltp_col = "CE LTP" if option_type == "CALL" else "PE LTP"

        filtered = oc_df[
            (oc_df["Strike Price"] % 500 == 0) & (oc_df[ltp_col].between(*ltp_range))
        ]

        if filtered.empty:
            return None

        row = filtered.iloc[(filtered[ltp_col] - 350).abs().argsort()].iloc[0]

        trading_symbol = self.build_option_symbol(
            candle["symbol"],
            expiry,
            row["Strike Price"],
            option_type,
        )

        inst = ctx["instrument_store"].intent_creation_details(
            trading_symbol, ctx["exchange"]
        )

        if not inst:
            return None

        sell_intent = self.map_instrument_to_intent(
            inst=inst,
            strike_row=row,
            strategy=self.name,
            side="SELL",
        )
        sell_intent["tag"] = "MAIN"

        hedge_intent = self.create_hedge_intent(
            parent_sell_intent=sell_intent,
            candle=candle,
            ctx=ctx,
        )
        if hedge_intent:
            return [sell_intent, hedge_intent]
        return sell_intent

    # --------------------------------------------------
    # EXIT LOGIC
    # --------------------------------------------------

    def should_exit(self, position, candle, ctx=None):
        if position.tag != "MAIN":
            return False

        rsi = candle.get("rsi")

        if position.option_type == "CALL" and rsi > 52:
            return True

        if position.option_type == "PUT" and rsi < 32:
            return True

        return False

    def on_position_exit(self, position, candle, ctx):
        """
        Called when a main position is exiting.
        Exit hedge explicitly.
        """
        if position.tag != "MAIN":
            return None

        hedge = ctx["position_store"].get_hedge_for(position)

        if not hedge:
            return None

        return {
            "intent_id": uuid.uuid4().hex,
            "action": "EXIT",
            "trading_symbol": hedge.trading_symbol,
            "qty": abs(hedge.net_qty),
            "strategy": self.name,
            "tag": "HEDGE_EXIT",
        }

    def on_candle_rollover(self, open_positions, candle, ctx):
        ts = pd.to_datetime(candle["timestamp"])

        if not self.is_hedge_rollover_day(ts):
            return []

        intents = []

        for hedge in open_positions:
            if hedge.tag != "HEDGE":
                continue

            intents.append(self.create_hedge_exit_intent(hedge))
            intents.append(self.create_hedge_intent(hedge.parent_position, candle, ctx))

        return intents

    def is_hedge_rollover_day(self, ts):
        target = dt.date(ts.year, ts.month, 18)

        if target.weekday() == 5:  # Saturday
            target -= dt.timedelta(days=1)
        elif target.weekday() == 6:  # Sunday
            target -= dt.timedelta(days=2)

        return ts.date() == target

    def resolve_hedge_expiry(self, trade_date):
        if trade_date.day < 15:
            return ExpiryResolver.current_month_expiry(trade_date)
        return ExpiryResolver.next_month_expiry(trade_date)

    def calculate_hedge_strike(self, sold_strike, option_type):
        if option_type == "CALL":
            return int(round((sold_strike * 1.02) / 500) * 500)
        return int(round((sold_strike * 0.98) / 500) * 500)

    def create_hedge_intent(self, parent_sell_intent, candle, ctx):
        trade_date = pd.to_datetime(candle["timestamp"]).date()

        hedge_expiry = self.resolve_hedge_expiry(trade_date)
        hedge_strike = self.calculate_hedge_strike(
            parent_sell_intent["strike"],
            parent_sell_intent["option_type"],
        )

        hedge_symbol = self.build_option_symbol(
            parent_sell_intent["symbol"],
            hedge_expiry,
            hedge_strike,
            parent_sell_intent["option_type"],
        )

        inst = ctx["instrument_store"].intent_creation_details(
            hedge_symbol, ctx["exchange"]
        )

        if not inst:
            return None

        return {
            "intent_id": uuid.uuid4().hex,
            "trading_symbol": inst["SEM_CUSTOM_SYMBOL"],
            "symbol": parent_sell_intent["symbol"],
            "expiry": str(inst["SEM_EXPIRY_DATE"]),
            "side": "BUY",
            "option_type": parent_sell_intent["option_type"],
            "strike": hedge_strike,
            "qty": 1,
            "strategy": self.name,
            "trade_type": "MARGIN",
            "exchange": inst["SEM_EXM_EXCH_ID"],
            "segment": inst["SEM_SEGMENT"],
            "lot_size": int(inst["SEM_LOT_UNITS"]),
            "tag": "HEDGE",
            "parent_intent_id": parent_sell_intent["intent_id"],
        }

    def create_hedge_exit_intent(self, hedge_position):
        return {
            "intent_id": uuid.uuid4().hex,
            "action": "EXIT",
            "trading_symbol": hedge_position.trading_symbol,
            "qty": abs(hedge_position.net_qty),
            "strategy": self.name,
            "tag": "HEDGE_EXIT",
        }

    # --------------------------------------------------
    # OPTION CHAIN (LIVE + BACKTEST SAFE)
    # --------------------------------------------------

    def fetch_option_chain(self, candle, ctx, option_type):
        ocs = ctx["option_chain_service"]

        expiry_code = ExpiryResolver.resolve(
            expiry_list=ctx.get("expiry_list"),
            trade_date=ctx["timestamp"],
            api=self.api,
            expiry_pref=self.expiryType,
        )

        params = {
            "exchange": ctx["exchange"],
            "interval": self.timeframe,
            "expiry_code": expiry_code,
            "strike": f"ATM+{self.strike_count}",
            "option_type": option_type,
            "expiry_flag": "MONTHLY",
        }

        ctx["selected_expiry"] = expiry_code

        return ocs.get_chain(
            # self,
            api=self.api,
            ctx=ctx,
            params=params,
        )

    # --------------------------------------------------
    # SYMBOL BUILDER
    # --------------------------------------------------

    def build_option_symbol(self, symbol, expiry, strike, option_type):
        if isinstance(expiry, str):
            expiry = dt.datetime.strptime(expiry, "%Y-%m-%d").date()

        return f"{symbol.upper()} {expiry.day:02d} {expiry.strftime('%b').upper()} {int(strike)} {option_type}"

    # --------------------------------------------------
    # INTENT MAPPER
    # --------------------------------------------------

    def map_instrument_to_intent(self, inst, strike_row, strategy, side):
        option_type = inst["SEM_OPTION_TYPE"]
        ltp = strike_row.get(f"{option_type} LTP", 0)

        return {
            "intent_id": uuid.uuid4().hex,
            "trading_symbol": inst["SEM_CUSTOM_SYMBOL"],
            "symbol": inst["SEM_CUSTOM_SYMBOL"].split()[0],
            "expiry": str(inst["SEM_EXPIRY_DATE"]),
            "side": side,
            "option_type": "CALL" if option_type == "CE" else "PUT",
            "strike": float(inst["SEM_STRIKE_PRICE"]),
            "price": ltp,
            "qty": 1,
            "strategy": strategy,
            "trade_type": "MARGIN",
            "exchange": inst["SEM_EXM_EXCH_ID"],
            "segment": inst["SEM_SEGMENT"],
            "lot_size": int(inst["SEM_LOT_UNITS"]),
        }
