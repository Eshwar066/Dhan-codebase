import pandas as pd
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from core.models.strategy_context import StrategyContext


class FuturesEMAHighLow:

    name = "FuturesEMAHighLow"
    timeframe = "60"
    required_context = ["instrument", "qty", "intent_builder"]
    api = "DHAN"

    def __init__(self):
        self.ema_period = 8
        self.target_pct = 0.006
        self.sl_pct = 0.004
        self.ema_period = 20

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

        # Indicator validity
        if pd.isna(ema_high) or pd.isna(ema_low):
            self._update_previous(candle)
            return False

        # Need previous values
        if (
            self.prev_close is None
            or self.prev_ema_high is None
            or self.prev_ema_low is None
        ):
            self._update_previous(candle)
            return False

        # Prevent same-candle re-entry after SL
        if self.last_exit_reason == "SL" and timestamp == self.last_exit_time:
            self._update_previous(candle)
            return False

        signal = None

        # --------------------------
        # LONG Breakout (Crossover)
        # --------------------------
        if self.prev_close <= self.prev_ema_high and close > ema_high:
            signal = "LONG"

        # --------------------------
        # SHORT Breakdown (Crossover)
        # --------------------------
        elif self.prev_close >= self.prev_ema_low and close < ema_low:
            signal = "SHORT"

        self.current_signal = signal
        self._update_previous(candle)

        return signal is not None

    # ----------------- Entry -----------------

    def on_candle(self, candle, ctx: "StrategyContext"):

        if ctx.instrument is None or ctx.intent_builder is None or ctx.qty is None:
            return None

        if not self.current_signal:
            return None

        side = "BUY" if self.current_signal == "LONG" else "SELL"
        self.last_direction = self.current_signal

        return [
            ctx.intent_builder.build_entry(
                instrument=ctx.instrument,
                side=side,
                qty=ctx.qty,
                tag="MAIN",
            )
        ]

    # ----------------- Exit -----------------

    def should_exit(self, pos, candle, ctx: Optional["StrategyContext"] = None):

        close = candle["close"]

        if pos.side == "BUY":
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

        else:  # SELL
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

        if ctx.intent_builder is None:
            return None

        return [
            ctx.intent_builder.build_exit(
                instrument=pos.instrument,
                qty=abs(pos.net_qty),
                tag="MAIN",
            )
        ]

    # ----------------- Target Re-entry -----------------

    def on_candle_rollover(self, open_positions, candle, ctx: "StrategyContext"):

        if open_positions:
            return None

        if self.last_exit_reason != "TARGET":
            return None

        close = candle["close"]
        ema_high = candle["ema_high"]
        ema_low = candle["ema_low"]

        if ctx.instrument is None or ctx.intent_builder is None:
            return None

        # Re-enter only in same direction after EMA touch + continuation
        if self.last_direction == "LONG" and close > ema_high:
            return [
                ctx.intent_builder.build_entry(
                    instrument=ctx.instrument,
                    side="BUY",
                    qty=ctx.qty,
                    tag="REENTRY",
                )
            ]

        if self.last_direction == "SHORT" and close < ema_low:
            return [
                ctx.intent_builder.build_entry(
                    instrument=ctx.instrument,
                    side="SELL",
                    qty=ctx.qty,
                    tag="REENTRY",
                )
            ]

        return None

    # ----------------- Structure Exit -----------------

    def default_structure_exit(self, *args, **kwargs):
        pass
