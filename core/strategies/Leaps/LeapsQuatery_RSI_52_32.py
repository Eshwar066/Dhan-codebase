import pandas as pd
import talib
from datetime import date

from run.config import RUN_MODE, RunMode
from core.strategies.base import BaseStrategy
from core.strategies.IndiaMktMixins import IST, IndiaMktMixins
from core.utils.expiry_resolver import ExpiryResolver

class LeapsQuarterly(IndiaMktMixins, BaseStrategy):
    """
    LEAPS RSI option selling (monthly rollover expiry, 15th cutoff).
    SIGNAL + HEDGE
    """

    name = "LEAPS_RSI"
    timeframe = "60"
    required_context = ["option_chain"]
    api = "DHAN"
    # Monthly rollover table (not Mar/Jun/Sep/Dec quarterly); see ExpiryResolver.LEAPS_ROLL.
    expiryType = "LEAPS_ROLL"
    # NIFTY LEAPS: 22000, 22500, 23000, … (not 50/100-step strikes).
    option_chain_strike_step = 500
    option_chain_ideal_premium = 350
    # Monthly hedge expiry cutoff (readme): before 15th → current month; on/after 15th → next month.
    hedge_monthly_rollover_after_calendar_day = 15

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._leaps_snapshot_logged_slots: set[str] = set()

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

    def resolve_hedge_expiry(self, trade_date: date, parent_expiry=None):
        """
        Hedge is a monthly option (not LEAPS quarterly).
        readme: current-month expiry if trade before 15th; next month if on/after 15th.
        Ignores parent_expiry from the sold LEAPS leg.
        """
        _ = parent_expiry
        cutoff = int(getattr(self, "hedge_monthly_rollover_after_calendar_day", 15) or 15)
        if trade_date.day < cutoff:
            return ExpiryResolver.current_month_expiry(trade_date)
        return ExpiryResolver.next_month_expiry(trade_date)

    #option chain snapshot
    def _candle_close_ts_ist(self, candle: dict) -> pd.Timestamp:
        ts = pd.Timestamp(candle["timestamp"])
        if ts.tzinfo is None:
            ts = ts.tz_localize(IST)
        else:
            ts = ts.tz_convert(IST)
        bar_minutes = int(self.timeframe) if str(self.timeframe).isdigit() else 60
        return ts + pd.Timedelta(minutes=bar_minutes)

      #option chain snapshot
    def _find_strike_snapshot_params(self, candle, ctx, option_type):
        ts_ist = self._candle_close_ts_ist(candle)
        snapshot_date = ts_ist.strftime("%Y-%m-%d")
        snapshot_time = ts_ist.strftime("%H-%M")
        slot_key = "|".join(
            [
                str(getattr(ctx, "symbol", "") or ""),
                str(option_type or ""),
                snapshot_date,
                snapshot_time,
            ]
        )
        if slot_key in self._leaps_snapshot_logged_slots:
            return {}
        self._leaps_snapshot_logged_slots.add(slot_key)
        return {
            "snapshot": True,
            "snapshot_date": snapshot_date,
            "snapshot_time": snapshot_time,
            "snapshot_target": "leaps_rsi",
        }

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
        rsi = candle["rsi"]
        if rsi < 32:
            option_type = "CALL"
            regime = "RSI_LT_32"
        elif rsi > 52:
            option_type = "PUT"
            regime = "RSI_GT_52"
        else:
            # option_type = "PUT"
            # regime = "RSI_GT_52"
            return None

        structure_id = self.build_structure_id(candle, regime)

        # Check if structure is already open
        if ctx.position_store.has_open_structure(
            strategy=self.name, structure_id=structure_id, tag="MAIN"
        ):
            return None

        # Find strike in premium range (500-point grid; CALL 300–400 / PUT 200–400).
        opt_u = option_type.upper()
        if opt_u in ("CE", "CALL"):
            min_prem, max_prem = 200, 400
        else:
            min_prem, max_prem = 200, 400
        result = self.find_strike_in_premium_range(
            candle, ctx, option_type, min_prem=min_prem, max_prem=max_prem
        )
        if result is None:
            print(f"⚠️ No valid strike found at {candle['timestamp']}")
            return None

        strike, premium, row = result
        if not strike:
            return None

        expiry_for_symbol = self._expiry_from_option_chain()
        if expiry_for_symbol is None:
            print(f"⚠️ No expiry on option chain at {candle['timestamp']}")
            return None

        # Build the trading symbol
        trading_symbol = ExpiryResolver.build_option_symbol(
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
