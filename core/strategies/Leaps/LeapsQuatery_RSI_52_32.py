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
    api = "NSE"
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
            option_type = "CALL"
            regime = "RSI_LT_32"
        elif rsi > 52:
            option_type = "PUT"
            regime = "RSI_GT_52"
        else:
            return None

        # ✅ BUILD STRUCTURE ID (ONCE)
        structure_id = self.build_structure_id(candle, regime)

        # ✅ DUPLICATE BLOCK
        if ctx["position_store"].has_open_structure(
            strategy=self.name,
            structure_id=structure_id,
        ):
            return None

        # option chain
        strike, premium, row = self.find_strike_in_premium_range(
            candle, ctx, option_type
        )
        expiry = ctx["selected_expiry"]
        if not strike:
            return None

        # atm, oc_df, expiry = chain["chain"]

        # ltp_col = "CE LTP" if option_type == "CALL" else "PE LTP"

        # filtered = oc_df[
        #     (oc_df["Strike Price"] % 500 == 0) & (oc_df[ltp_col].between(*ltp_range))
        # ]

        # if filtered.empty:
        #     return None

        # row = filtered.iloc[(filtered[ltp_col] - 350).abs().argsort()].iloc[0]

        trading_symbol = ExpiryResolver.build_option_symbol(
            self,
            candle["symbol"],
            expiry,
            strike,
            option_type,
        )

        inst = ctx["instrument_store"].intent_creation_details(
            trading_symbol, ctx["exchange"], expiry, option_type, strike
        )

        if inst is None or inst.empty:
            return

        sell_intent = self.map_instrument_to_intent(
            inst=inst,
            strike_row=row,
            strategy=self.name,
            side="SELL",
            structure_id=structure_id,
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

    # used for Create hedge intent
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

        hedge_symbol = ExpiryResolver.build_option_symbol(
            self,
            parent_sell_intent["symbol"],
            hedge_expiry,
            hedge_strike,
            parent_sell_intent["option_type"],
        )

        inst = ctx["instrument_store"].intent_creation_details(
            hedge_symbol,
            ctx["exchange"],
            hedge_expiry,
            hedge_strike,
            parent_sell_intent["option_type"],
        )

        if inst is None or inst.empty:
            return None

        return {
            "intent_id": uuid.uuid4().hex,
            "structure_id": parent_sell_intent["structure_id"],
            "instrument": inst,
            "trading_symbol": inst["SEM_CUSTOM_SYMBOL"],
            "symbol": parent_sell_intent["symbol"],
            "expiry": str(inst["SEM_EXPIRY_DATE"]),
            "side": "BUY",
            "option_type": parent_sell_intent["option_type"],
            "strike": hedge_strike,
            "qty": 1,
            "price": 10,
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
            "structure_id": hedge_position.structure_id,
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

        if self.api == "NSE":
            ctx["expiry_list"] = ocs.get_expiries(
                api=self.api, ctx=ctx, instrument="FUTIDX"
            )

        expiry_code = ExpiryResolver.resolve(
            expiry_list=ctx.get("expiry_list"),
            trade_date=ctx["timestamp"],
            api=self.api,
            expiry_pref=self.expiryType,
        )

        spot = candle["close"]

        step = 500
        otm_strikes = ExpiryResolver.get_otm_strikes(
            self, spot=spot, option_type=option_type, step=step, count=4
        )
        ctx["selected_expiry"] = expiry_code
        ctx["otm_strikes"] = otm_strikes

        return otm_strikes

    def find_strike_in_premium_range(
        self, candle, ctx, option_type, min_prem=200, max_prem=400
    ):
        otm_strikes = self.fetch_option_chain(candle, ctx, option_type)

        candle_time = candle["timestamp"].replace(tzinfo=None)

        for strike in otm_strikes:
            params = {
                "exchange": ctx["exchange"],
                "interval": self.timeframe,
                "expiry_code": ctx["selected_expiry"],
                "strike": str(strike),
                "option_type": option_type,
                "expiry_flag": "MONTH",
                "instrument": "OPTIDX",
                "exchangeSegment": "NSE_FNO",
                "securityId": "13",
            }

            chain = ctx["option_chain_service"].get_chain(
                api=self.api, ctx=ctx, params=params
            )

            if RUN_MODE == RunMode.LIVE or RUN_MODE == RunMode.PAPER:
                # If API returns empty dataframe
                if chain is None or len(chain) == 0:
                    continue

                # Filter row matching candle timestamp
                row = chain[chain["datetime"] == candle_time]

                if row.empty:
                    continue

                # Premium at that exact candle time
                premium = float(row.iloc[0]["close"])
                selected_strike = row.iloc[0]["strike"]
            else:
                chain = chain["chain"]
                if chain is None or len(chain) == 0:
                    continue

                # Find column that matches option_type (case-insensitive, ignores extra spaces)
                option_type_upper = option_type.upper()  # 'PUT' or 'CE'
                premium_col = None
                for col in chain.columns:
                    if option_type_upper in col.upper() and "LTP" in col.upper():
                        premium_col = col
                        break

                if premium_col is None:
                    continue

                # filter by premium
                row = chain[chain[premium_col].between(min_prem, max_prem)]
                if row.empty:
                    continue

                selected_strike = row.iloc[0]["Strike Price"]
                premium = float(row.iloc[0][premium_col])

            if min_prem <= premium <= max_prem:
                return selected_strike, premium, row

        return None, None, None

    # --------------------------------------------------
    # INTENT MAPPER
    # --------------------------------------------------

    def map_instrument_to_intent(self, inst, strike_row, strategy, side, structure_id):
        option_type = inst["SEM_OPTION_TYPE"]
        if RUN_MODE == RunMode.LIVE or RUN_MODE == RunMode.PAPER:
            # ltp = strike_row.get(f"{option_type} LTP", 0)
            ltp = float(strike_row.iloc[0]["close"])
        else:
            optionType = "PUT" if option_type == "PE" else "CALL"
            ltp_value = strike_row.get(f"{optionType} LTP", 0)
            ltp = (
                float(ltp_value.iloc[0])
                if isinstance(ltp_value, pd.Series)
                else float(ltp_value)
            )

        return {
            "intent_id": uuid.uuid4().hex,
            "instrument": inst,
            "structure_id": structure_id,
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

    def build_structure_id(self, candle, regime):
        ts = pd.to_datetime(candle["timestamp"]).strftime("%Y%m%d_%H")  # ⬅ hourly
        symbol = candle["symbol"]
        return f"{self.name}:{symbol}:{regime}:{ts}"
