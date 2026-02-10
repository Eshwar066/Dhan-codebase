import uuid
import pandas as pd
import talib
from datetime import date, timedelta
import pdb

from run.config import RUN_MODE, RunMode
from core.strategies.base import BaseStrategy
from core.utils.expiry_resolver import ExpiryResolver
from core.models.order_intent import OrderIntent  # Make sure this is imported


VALID_TIMES = {"10:15", "11:15", "12:15", "13:15", "14:15", "15:15"}


class LeapsQuarterly(BaseStrategy):
    """
    LEAPS Quarterly RSI Option Selling Strategy
    SIGNAL + HEDGE
    """

    name = "LEAPS_RSI"
    timeframe = "60"
    required_context = ["option_chain"]
    api = "NSE"
    expiryType = "QUARTERLY"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # 🔒 rollover memory (CRITICAL)
        self.rolled_hedges = set()

    # ==================================================
    # INDICATORS
    # ==================================================
    def prepare_indicators(self, df):
        df["rsi"] = talib.RSI(df["close"], 14)
        df["prev_rsi"] = df["rsi"].shift(1)
        return df

    # ==================================================
    # TIME FILTER
    # ==================================================
    def _is_valid_time(self, ts):
        return ts.strftime("%H:%M") in VALID_TIMES

    # ==================================================
    # SHOULD EVALUATE
    # ==================================================
    def should_evaluate(self, candle):
        rsi = candle.get("rsi")
        prev = candle.get("prev_rsi")
        if pd.isna(rsi) or pd.isna(prev):
            return False
        return (prev >= 32 and rsi < 32) or (prev <= 52 and rsi > 52)

    # ==================================================
    # ENTRY
    # ==================================================
    def on_candle(self, candle, ctx):
        ts = pd.to_datetime(candle["timestamp"])
        if not self._is_valid_time(ts):
            return None

        rsi = candle["rsi"]
        if rsi < 32:
            option_type = "CALL"
            regime = "RSI_LT_32"
        elif rsi > 52:
            option_type = "PUT"
            regime = "RSI_GT_52"
        else:
            return None

        structure_id = self.build_structure_id(candle, regime)

        # Check if structure is already open
        if ctx["position_store"].has_open_structure(
            strategy=self.name, structure_id=structure_id, tag="MAIN"
        ):
            return None

        # Find strike in premium range
        result = self.find_strike_in_premium_range(candle, ctx, option_type)
        if result is None:
            print(f"⚠️ No valid strike found at {candle['timestamp']}")
            return None

        strike, premium, row = result
        if not strike:
            return None

        expiry = ctx["selected_expiry"]

        # Build the trading symbol
        trading_symbol = ExpiryResolver.build_option_symbol(
            self,
            candle["symbol"],
            expiry,
            strike,
            option_type,
        )

        # Fetch Instrument object from InstrumentStore
        inst = ctx["instrument_store"].intent_creation_details(
            trading_symbol,
            ctx["exchange"],
            expiry,
            option_type,
            strike,
        )

        if inst is None:
            print(f"❌ Instrument not found for {trading_symbol}")
            return None

        # Main sell intent as OrderIntent
        sell_intent = self.map_instrument_to_intent(
            inst=inst,
            strike_row=row,  # keep for any additional data if needed
            strategy=self.name,
            side="SELL",
            structure_id=structure_id,
            candle_ts=candle["timestamp"],
            tag="MAIN",
            symbol=candle["symbol"],
            action="ENTRY",
        )

        # Hedge intent as OrderIntent
        hedge_intent = self.create_hedge_intent(
            parent_sell_intent=sell_intent,
            candle=candle,
            ctx=ctx,
        )

        # Return intents as a list
        return [sell_intent, hedge_intent] if hedge_intent else [sell_intent]

    # ==================================================
    # EXIT SIGNAL
    # ==================================================
    def should_exit(self, position, candle, ctx=None):
        if position.tag != "MAIN":
            return False
        rsi = candle.get("rsi")
        if position.instrument.option_type in ("CE", "CALL") and rsi > 52:
            return True
        if position.instrument.option_type in ("PE", "PUT") and rsi < 32:
            return True
        return False

    # ==================================================
    # EXIT HANDLER
    # ==================================================
    def on_position_exit(self, position, candle, ctx):
        intents = []

        price = (
            self.get_option_price_at_candle(
                candle,
                ctx,
                position.instrument.strike,
                position.instrument.option_type,
                position.instrument.expiry,
            )
            if RUN_MODE == RunMode.BACKTEST
            else None
        )
        intents.append(
            self.create_order_intent(
                inst=position.instrument,
                side="BUY" if position.net_qty < 0 else "SELL",
                qty=abs(position.net_qty),
                price=price,
                strategy=self.name,
                candle_ts=candle["timestamp"],
                structure_id=position.structure_id,
                tag="MAIN_EXIT",
                symbol=candle["symbol"],
                action="EXIT",
            )
        )

        hedge_exit = self.create_hedge_exit_intent(position, candle, ctx)
        if hedge_exit:
            intents.append(hedge_exit)

        return intents

    # ==================================================
    # HEDGE EXIT
    # ==================================================
    def create_hedge_exit_intent(self, position, candle, ctx):
        hedge = ctx["position_store"].get_hedge_for(position)
        if not hedge or hedge.net_qty == 0:
            return None

        price = (
            self.get_option_price_at_candle(
                candle,
                ctx,
                hedge.instrument.strike,
                hedge.instrument.option_type,
                hedge.instrument.expiry,
            )
            if RUN_MODE == RunMode.BACKTEST
            else None
        )
        if price is None:
            print(
                f"⚠️ No exit price for hedge {hedge.instrument.symbol} at {candle['timestamp']}"
            )
            return None

        return self.create_order_intent(
            inst=hedge.instrument,
            side="BUY" if hedge.net_qty < 0 else "SELL",
            qty=abs(hedge.net_qty),
            price=price,
            strategy=self.name,
            candle_ts=candle["timestamp"],
            structure_id=hedge.structure_id,
            tag="HEDGE_EXIT",
            symbol=candle["symbol"],
            action="EXIT",
        )

    # ==================================================
    # HEDGE ENTRY
    # ==================================================
    def resolve_hedge_expiry(self, trade_date):
        return (
            ExpiryResolver.current_month_expiry(trade_date)
            if trade_date.day < 15
            else ExpiryResolver.next_month_expiry(trade_date)
        )

    def calculate_hedge_strike(self, sold_strike, option_type):
        if option_type == "CALL":
            return int(round((sold_strike * 1.02) / 500) * 500)
        return int(round((sold_strike * 0.98) / 500) * 500)

    def create_hedge_intent(self, parent_sell_intent, candle, ctx):
        trade_date = pd.to_datetime(candle["timestamp"]).date()
        hedge_expiry = self.resolve_hedge_expiry(trade_date)

        hedge_strike = self.calculate_hedge_strike(
            parent_sell_intent.instrument.strike,
            parent_sell_intent.instrument.option_type,
        )

        # Enters into if condition on main entry and into else for rollover logic
        hedge_symbol = ExpiryResolver.build_option_symbol(
            self,
            candle["symbol"],
            hedge_expiry,
            hedge_strike,
            parent_sell_intent.instrument.option_type,
        )

        inst = ctx["instrument_store"].intent_creation_details(
            hedge_symbol,
            ctx["exchange"],
            hedge_expiry,
            parent_sell_intent.instrument.option_type,
            hedge_strike,
        )
        if inst is None:
            return None

        hedge_price = (
            self.get_option_price_at_candle(
                candle,
                ctx,
                hedge_strike,
                parent_sell_intent.instrument.option_type,
                hedge_expiry,
            )
            if RUN_MODE == RunMode.BACKTEST
            else 0
        )

        return self.create_order_intent(
            inst=inst,
            side="BUY",
            qty=1,
            price=hedge_price,
            strategy=self.name,
            candle_ts=candle["timestamp"],
            structure_id=parent_sell_intent.structure_id,
            tag="HEDGE",
            parent_intent_id=parent_sell_intent.intent_id,
            symbol=candle["symbol"],
            action="ENTRY",
        )

    # ==================================================
    # STRUCTURE ID
    # ==================================================
    def build_structure_id(self, candle, regime):
        return f"{self.name}:{candle['symbol']}:{regime}"

    # ==================================================
    # ORDER INTENT FACTORY
    # ==================================================
    def create_order_intent(
        self,
        inst,
        side,
        qty,
        price,
        strategy,
        candle_ts,
        structure_id,
        tag,
        symbol,
        action,
        parent_intent_id=None,
    ):
        return OrderIntent(
            intent_id=uuid.uuid4().hex,
            instrument=inst,
            side=side,
            qty=int(inst.lot_size),  # or 1 lot if you prefer
            price=price,
            order_type="LIMIT",
            strategy=strategy,
            structure_id=structure_id,
            trade_type="MARGIN",
            tag=tag,
            candle_ts=candle_ts,
            parent_intent_id=parent_intent_id,
            symbol=symbol,
            action=action,
        )

    # ==================================================
    # OPTION PRICING (BACKTEST SAFE)
    # ==================================================
    def get_option_price_at_candle(self, candle, ctx, strike, option_type, expiry):
        params = {
            "exchange": ctx["exchange"],
            "interval": self.timeframe,
            "expiry_code": expiry,
            "strike": [str(int(float(strike)))],
            "option_type": option_type,
            "instrument": "OPTIDX",
            "exchangeSegment": "NSE_FNO",
            "expiry_flag": "MONTH",
            "securityId": "13",
        }

        chain = ctx["option_chain_service"].get_chain(
            api=self.api, ctx=ctx, params=params
        )

        if not chain or "chain" not in chain:
            return None

        df = chain["chain"]

        if option_type.upper() in ("PUT", "PE"):
            cols = ["PE LTP", "PUT LTP"]
        else:
            cols = ["CE LTP", "CALL LTP"]

        for col in cols:
            if col in df.columns:
                return float(df[col].iloc[0])

        return None

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
        self, candle, ctx, option_type, min_prem=200, max_prem=500
    ):
        otm_strikes = self.fetch_option_chain(candle, ctx, option_type)

        candle_time = candle["timestamp"].replace(tzinfo=None)

        # for strike in otm_strikes:
        params = {
            "exchange": ctx["exchange"],
            "interval": self.timeframe,
            "expiry_code": ctx["selected_expiry"],
            "strike": otm_strikes,
            "option_type": option_type,
            "instrument": "OPTIDX",
            "exchangeSegment": "NSE_FNO",
            "expiry_flag": "MONTH",
            "securityId": "13",
        }

        chain = ctx["option_chain_service"].get_chain(
            api=self.api, ctx=ctx, params=params
        )
        if not chain:
            print(">>no option chain data", ctx, params)
            return

        if RUN_MODE == RunMode.LIVE or RUN_MODE == RunMode.PAPER:
            # If API returns empty dataframe
            if chain is None or len(chain) == 0:
                return None

            # Filter row matching candle timestamp
            row = chain[chain["datetime"] == candle_time]

            if row.empty:
                return None

            # Premium at that exact candle time
            premium = float(row.iloc[0]["close"])
            selected_strike = row.iloc[0]["strike"]
        else:
            chain = chain["chain"]
            if chain is None or len(chain) == 0:
                return None

            # Find column that matches option_type (case-insensitive, ignores extra spaces)
            option_type_upper = option_type.upper()  # 'PUT' or 'CE'
            premium_col = None
            for col in chain.columns:
                if option_type_upper in col.upper() and "LTP" in col.upper():
                    premium_col = col
                    break

            if premium_col is None:
                return None

            # filter by premium
            row = chain[chain[premium_col].between(min_prem, max_prem)]
            if row.empty:
                return None

            selected_strike = row.iloc[0]["Strike Price"]
            premium = float(row.iloc[0][premium_col])

        if min_prem <= premium <= max_prem:
            return selected_strike, premium, row

        return None, None, None

    def map_instrument_to_intent(
        self,
        inst,
        strike_row,
        strategy,
        side,
        structure_id,
        candle_ts,
        symbol,
        action,
        tag=None,
        parent_intent_id=None,
    ):
        option_type = inst.option_type

        # --- price discovery ---
        if RUN_MODE in (RunMode.LIVE, RunMode.PAPER):
            ltp = float(strike_row.iloc[0]["close"])
        else:
            option_type_label = "PUT" if option_type == "PE" else "CALL"
            ltp_value = strike_row.get(f"{option_type_label} LTP", 0)
            ltp = (
                float(ltp_value.iloc[0])
                if isinstance(ltp_value, pd.Series)
                else float(ltp_value)
            )

        # --- invariants ---
        assert inst.trading_symbol
        assert inst.custom_symbol

        return OrderIntent(
            intent_id=uuid.uuid4().hex,
            instrument=inst,
            side=side,
            qty=int(inst.lot_size),  # or 1 lot if you prefer
            price=ltp,
            order_type="LIMIT",
            strategy=strategy,
            structure_id=structure_id,
            trade_type="MARGIN",
            tag=tag,
            candle_ts=candle_ts,
            parent_intent_id=parent_intent_id,
            symbol=symbol,
            action=action,
        )

    # ==================================================
    # ROLLOVER
    # ==================================================
    def is_rollover_window(self, ts):
        return 15 <= ts.day <= 18

    def should_roll_hedge(self, hedge, ts):
        expiry = pd.to_datetime(hedge.instrument.expiry).date()
        current = pd.to_datetime(ts).date()
        if expiry <= current:
            return False

        target = date(current.year, current.month, 18)
        if target.weekday() == 5:
            target -= timedelta(days=1)
        elif target.weekday() == 6:
            target -= timedelta(days=2)

        return current >= target

    def on_candle_rollover(self, open_positions, candle, ctx):
        ts = pd.to_datetime(candle["timestamp"])
        if not self.is_rollover_window(ts):
            return []

        intents = []

        for hedge in [p for p in open_positions if p.tag == "HEDGE" and p.net_qty != 0]:

            roll_key = self._hedge_roll_key(hedge)

            # 🚫 Already rolled → skip forever
            if roll_key in self.rolled_hedges:
                continue
            if not self.should_roll_hedge(hedge, ts):
                continue

            parent = next(
                (
                    p
                    for p in open_positions
                    if p.structure_id == hedge.structure_id and p.tag == "MAIN"
                ),
                None,
            )
            if not parent:
                continue

            # Append hedge exit and new hedge OrderIntent
            hedge_exit = self.create_hedge_exit_intent(parent, candle, ctx)
            if hedge_exit:
                intents.append(hedge_exit)

            new_hedge = self.create_hedge_intent(parent, candle, ctx)
            if new_hedge:
                intents.append(new_hedge)

            # 🔒 LOCK rollover
            self.rolled_hedges.add(roll_key)

        return intents

    def _hedge_roll_key(self, hedge):
        inst = hedge.instrument
        return (
            hedge.strategy,
            hedge.structure_id,
            inst.expiry,
            inst.strike,
            inst.option_type,
        )

    # rollover cleanup function
    def on_structure_exit(self, structure_id, **kwargs):
        """
        Called when a structure is fully exited.
        kwargs may include:
        - strategy
        - instrument
        - candle_ts
        - reason (future)
        """

        # Clear rolled hedges linked to this structure
        self.rolled_hedges = {k for k in self.rolled_hedges if k[1] != structure_id}
