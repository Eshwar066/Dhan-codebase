import pandas as pd
import talib

from run.config import RUN_MODE, RunMode
from core.strategies.base import BaseStrategy
from core.strategies.IndiaMktMixins import IndiaMktMixins
from core.utils.expiry_resolver import ExpiryResolver


VALID_TIMES = {"10:15", "11:15", "12:15", "13:15", "14:15", "15:15"}


class LeapsQuarterly(IndiaMktMixins, BaseStrategy):
    """
    LEAPS Quarterly RSI Option Selling Strategy
    SIGNAL + HEDGE
    """

    name = "LEAPS_RSI"
    timeframe = "60"
    required_context = ["option_chain"]
    api = "DHAN"
    expiryType = "QUARTERLY"
    valid_times = VALID_TIMES

    # ==================================================
    # INDICATORS
    # ==================================================
    def get_warmup_period(self):
        return 0

    def prepare_indicators(self, df):
        df["rsi"] = talib.RSI(df["close"], 14)
        df["prev_rsi"] = df["rsi"].shift(1)
        return df

    def requires_live_rsi_patch(self) -> bool:
        return True

    # ==================================================
    # SHOULD EVALUATE
    # ==================================================
    def should_evaluate(self, candle):
        rsi = candle.get("rsi")
        prev = candle.get("prev_rsi")
        # return True
        if pd.isna(rsi) or pd.isna(prev):
            return False
        return (prev >= 32 and rsi < 32) or (prev <= 52 and rsi > 52)

    # ==================================================
    # ENTRY
    # ==================================================
    def on_candle(self, candle, ctx):
        ts = pd.to_datetime(candle["timestamp"])
        if not self._is_valid_time(ts, VALID_TIMES):
            return None
        
        rsi = candle["rsi"]
        if rsi < 32:
            option_type = "CALL"
            regime = "RSI_LT_32"
        elif rsi > 52:
            option_type = "PUT"
            regime = "RSI_GT_52"
        else:
            # option_type = "CALL"
            # regime = "RSI_LT_32"
            return None

        structure_id = self.build_structure_id(candle, regime)

        # Check if structure is already open
        if ctx.position_store.has_open_structure(
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

        expiry = ctx.selected_expiry
        trade_date = pd.to_datetime(candle["timestamp"]).date()
        expiry_for_symbol = expiry
        # DHAN option-chain flow stores expiry as rolling series index (0/1/..).
        # Convert to calendar date before building option symbol.
        if isinstance(expiry, (int, float)):
            expiry_for_symbol = ExpiryResolver.dhan_expiry_index_to_date(
                trade_date, int(expiry)
            )
        # Build the trading symbol
        trading_symbol = ExpiryResolver.build_option_symbol(
            self,
            candle["symbol"],
            expiry_for_symbol,
            strike,
            option_type,
        )
       
        # Fetch Instrument object from InstrumentStore
        inst = ctx.instrument_store.intent_creation_details(
            trading_symbol,
            ctx.exchange,
            expiry_for_symbol,
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
        return [hedge_intent,sell_intent] if hedge_intent else [sell_intent]

    # ==================================================
    # EXIT SIGNAL
    # ==================================================
    def should_exit(self, position, candle, ctx=None):
        if position.tag != "MAIN":
            return False
        rsi = candle.get("rsi")
        if pd.isna(rsi):
            return False
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
                order_type="LIMIT",
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
