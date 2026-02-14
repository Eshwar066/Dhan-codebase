import pandas as pd
from typing import TYPE_CHECKING, Optional
from core.strategies.base import BaseStrategy
from core.strategies.IndiaMktMixins import IndiaMktMixins
import pdb

if TYPE_CHECKING:
    from core.models.strategy_context import StrategyContext


class FuturesEMAHighLow(IndiaMktMixins, BaseStrategy):

    name = "FuturesEMAHighLow"
    timeframe = "60"
    required_context = ["instrument", "qty", "intent_builder"]
    api = "NSE"

    def __init__(self):
        self.ema_period = 20
        self.target_pct = 0.006
        self.sl_pct = 0.004

        # State
        self.last_exit_reason = None
        self.last_exit_time = None
        self.last_direction = None

        self.prev_close = None
        self.prev_ema_high = None
        self.prev_ema_low = None

        self.current_signal = None
        self.on_structure_exit = self.default_structure_exit

    # ----------------- Indicators -----------------

    def get_warmup_period(self):
        return self.ema_period * 3

    def prepare_indicators(self, df):
        df["ema_high"] = df["high"].ewm(span=self.ema_period, adjust=False).mean()
        df["ema_low"] = df["low"].ewm(span=self.ema_period, adjust=False).mean()
        return df

    # ----------------- Internal Helper -----------------

    def _update_previous(self, candle):
        self.prev_close = candle.get("close")
        self.prev_ema_high = candle.get("ema_high")
        self.prev_ema_low = candle.get("ema_low")

    # ----------------- Evaluate -----------------

    def should_evaluate(self, candle):

        close = candle.get("close")
        ema_high = candle.get("ema_high")
        ema_low = candle.get("ema_low")
        timestamp = candle.get("timestamp")

        # if self.api in ("NSE", "DHAN"):
        #     if timestamp.hour == 9 and timestamp.minute == 15:
        #         self._update_previous(candle)
        #         return False

        if pd.isna(ema_high) or pd.isna(ema_low):
            self._update_previous(candle)
            return False

        if (
            self.prev_close is None
            or self.prev_ema_high is None
            or self.prev_ema_low is None
        ):
            self._update_previous(candle)
            return False

        if self.last_exit_reason == "SL" and timestamp == self.last_exit_time:
            self._update_previous(candle)
            return False

        signal = None

        # LONG breakout
        # if self.prev_close <= self.prev_ema_high and close > ema_high:
        if close > ema_high:
            signal = "LONG"

        # SHORT breakdown
        # elif self.prev_close >= self.prev_ema_low and close < ema_low:
        elif close < ema_low:
            signal = "SHORT"

        self.current_signal = signal
        self._update_previous(candle)

        return signal is not None

    # ----------------- Regime -----------------

    def compute_regime(self, candle):
        ema_high = candle.get("ema_high")
        ema_low = candle.get("ema_low")

        if ema_high > ema_low:
            return "BULL"
        elif ema_high < ema_low:
            return "BEAR"
        else:
            return "NEUTRAL"

    # ----------------- Entry -----------------

    def on_candle(self, candle, ctx: "StrategyContext"):

        if not self.current_signal:
            return None

        regime = self.compute_regime(candle)
        structure_id = self.build_structure_id(candle, regime)

        hasOpenPosition = ctx.position_store.has_open_structure(
            strategy=self.name, structure_id=structure_id, tag="MAIN"
        )
        # pdb.set_trace()
        if hasOpenPosition:
            return None

        side = "BUY" if self.current_signal == "LONG" else "SELL"
        self.last_direction = self.current_signal

        # ---------------------------------
        # 1️⃣ Prefer engine provided instrument
        # ---------------------------------
        inst = ctx.instrument

        # ---------------------------------
        # 2️⃣ Fallback (Backtest sandbox only)
        # ---------------------------------
        if inst is None:
            expiry = self.getExpiry(ctx)

            inst = ctx.instrument_store.futures_intent_creation_details(
                trading_symbol="NIFTY FUT",
                exchange="NSE",
                expiry=expiry,
            )

            if inst is None:
                return None

        # ---------------------------------
        # 3️⃣ Map to OrderIntent
        # ---------------------------------
        buy_intent = self.map_futures_instrument_to_intent(
            inst=inst,
            strike_row=candle,  # ✅ use candle as price source
            strategy=self.name,
            side=side,
            structure_id=structure_id,
            candle_ts=candle["timestamp"],
            symbol=candle["symbol"],
            action="ENTRY",
            tag="MAIN",
        )

        return [buy_intent]

    # ----------------- Exit -----------------

    def should_exit(self, pos, candle, ctx: Optional["StrategyContext"] = None):

        close = candle["close"]

        is_long = pos.net_qty > 0
        is_short = pos.net_qty < 0

        if is_long:
            target = pos.entry_price * (1 + self.target_pct)
            stop = pos.entry_price * (1 - self.sl_pct)

            if close >= target:
                self.last_exit_reason = "TARGET"
                self.last_exit_time = candle["timestamp"]
                return True

            if close <= stop:
                self.last_exit_reason = "SL"
                self.last_exit_time = candle["timestamp"]
                return True

        elif is_short:
            target = pos.entry_price * (1 - self.target_pct)
            stop = pos.entry_price * (1 + self.sl_pct)

            if close <= target:
                self.last_exit_reason = "TARGET"
                self.last_exit_time = candle["timestamp"]
                return True

            if close >= stop:
                self.last_exit_reason = "SL"
                self.last_exit_time = candle["timestamp"]
                return True

        return False

    def on_position_exit(self, pos, candle, ctx: "StrategyContext"):

        if pos.instrument is None:
            return None

        # Reverse side
        exit_side = "SELL" if pos.net_qty > 0 else "BUY"

        structure_id = pos.structure_id  # keep same structure

        exit_intent = self.map_futures_instrument_to_intent(
            inst=pos.instrument,
            strike_row=candle,
            strategy=self.name,
            side=exit_side,
            structure_id=structure_id,
            candle_ts=candle["timestamp"],
            symbol=candle["symbol"],
            action="EXIT",
            tag="MAIN",
            parent_intent_id=None,
        )

        return [exit_intent]

    # ----------------- Structure Exit -----------------

    def default_structure_exit(self, *args, **kwargs):
        pass
