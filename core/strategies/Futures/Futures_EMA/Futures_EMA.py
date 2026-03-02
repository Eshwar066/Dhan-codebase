import pandas as pd
from typing import TYPE_CHECKING, Optional
from core.strategies.base import BaseStrategy
from core.strategies.IndiaMktMixins import IndiaMktMixins
from datetime import datetime, timedelta

if TYPE_CHECKING:
    from core.models.strategy_context import StrategyContext


class FuturesEMAHighLow(IndiaMktMixins, BaseStrategy):

    name = "FuturesEMAHighLow"
    timeframe = "60"
    required_context = ["instrument", "qty", "intent_builder"]
    api = "DELTA"

    macro_ema_slope_period = 50
    macro_ema_slope_threshold = 0.5

    atr_period = 14
    atr_min = 0.003
    atr_max = 0.015

    def __init__(self):
        self.ema_period = 8
        self.target_pct = 0.018
        self.sl_pct = 0.005

        # State
        self.last_exit_reason = None
        self.last_exit_time = None
        self.last_direction = None
        self.prev_close = None
        self.prev_ema_high = None
        self.prev_ema_low = None
        self.current_signal = None

        # Re-entry tracking per structure
        self.reentry_state = {}

        self.on_structure_exit = self.default_structure_exit

    # ----------------- Indicators -----------------

    def get_warmup_period(self):
        # ATR needs atr_period + a few bars to stabilize; ema needs ema_period * 3
        return max(self.ema_period * 3, getattr(self, "atr_period", 14) + 5)

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

        signal = None

        # LONG breakout
        if close > ema_high:
            signal = "LONG"

        # SHORT breakdown
        elif close < ema_low:
            signal = "SHORT"

        # --- Re-entry logic ---
        if self.last_exit_reason in ["SL", "TARGET"]:
            last_ts = self.last_exit_time
            last_dir = self.last_direction

            # Rule 6: wait 1 candle after SL
            if self.last_exit_reason == "SL" and timestamp <= last_ts + timedelta(
                minutes=60
            ):
                signal = None

            # Rule 7: TARGET re-entry only if same trend touches EMA
            elif self.last_exit_reason == "TARGET":
                if last_dir == "LONG" and close <= ema_high:
                    signal = "LONG"
                elif last_dir == "SHORT" and close >= ema_low:
                    signal = "SHORT"
                else:
                    signal = None

        # Macro filter: LONG only if close > ema_100 (Option 1) or ema_slope > 0 (Option 2); SHORT only if opposite
        if signal and (
            getattr(self, "macro_ema_slope_period", None)
            or getattr(self, "macro_ema_period", None)
        ):
            htf_trend = candle.get("htf_trend")
            if signal == "LONG" and htf_trend != "BULL":
                signal = None
            elif signal == "SHORT" and htf_trend != "BEAR":
                signal = None

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

    def _atr_filter_ok(self, candle, ctx: "StrategyContext") -> bool:
        """True if ATR filter passes (or filter disabled). Uses IndiaMktMixins._atr. ATR as % of price (regime-stable)."""
        atr_period = getattr(self, "atr_period", 14)
        atr_min = getattr(self, "atr_min", None)
        atr_max = getattr(self, "atr_max", None)
        if atr_min is None and atr_max is None:
            return True
        recent = ctx.get_recent_candles(atr_period + 1)
        if len(recent) < atr_period + 1:
            return False
        atr_list = self._atr(recent, atr_period)
        if atr_list is None or len(atr_list) == 0:
            return False
        current_atr = atr_list[-1]
        if current_atr is None or (
            isinstance(current_atr, float)
            and (pd.isna(current_atr) or current_atr <= 0)
        ):
            return False
        price = float(candle.get("close") or 0)
        if price <= 0:
            return False
        atr_pct = current_atr / price
        if atr_min is not None and atr_pct < atr_min:
            return False
        if atr_max is not None and atr_pct > atr_max:
            return False
        return True

    def on_candle(self, candle, ctx: "StrategyContext"):

        if not self.current_signal:
            return None

        if not self._atr_filter_ok(candle, ctx):
            return None

        regime = self.compute_regime(candle)
        structure_id = self.build_structure_id(candle, regime)

        hasOpenPosition = ctx.position_store.has_open_structure(
            strategy=self.name, structure_id=structure_id, tag="MAIN"
        )
        if hasOpenPosition:
            return None

        side = "BUY" if self.current_signal == "LONG" else "SELL"
        self.last_direction = self.current_signal

        inst = ctx.instrument

        if inst is None:
            expiry = None
            if self.api == "NSE":
                expiry = self.getExpiry(ctx)

            elif self.api == "DELTA":
                product_type = getattr(ctx, "product_type", None)
                if product_type != "PERPETUALFUTURES":
                    expiry = self.getExpiry(ctx)

            inst = ctx.instrument_store.futures_intent_creation_details(
                trading_symbol=candle["symbol"],
                exchange="NSE" if self.api == "NSE" else "DELTA",
                expiry=expiry,
            )
            if inst.lot_size <= 0:
                raise ValueError(f"Invalid lot_size for {self.trading_symbol}")

            if inst is None:
                return None

        buy_intent = self.map_futures_instrument_to_intent(
            inst=inst,
            strike_row=candle,
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
        high = candle["high"]
        low = candle["low"]

        is_long = pos.net_qty > 0
        is_short = pos.net_qty < 0

        if is_long:
            target = pos.entry_price * (1 + self.target_pct)
            stop = pos.entry_price * (1 - self.sl_pct)

            if high >= target:
                self.last_exit_reason = "TARGET"
                self.last_exit_time = candle["timestamp"]
                return True

            if low <= stop:
                self.last_exit_reason = "SL"
                self.last_exit_time = candle["timestamp"]
                return True

        elif is_short:
            target = pos.entry_price * (1 - self.target_pct)
            stop = pos.entry_price * (1 + self.sl_pct)

            if low <= target:
                self.last_exit_reason = "TARGET"
                self.last_exit_time = candle["timestamp"]
                return True

            if high >= stop:
                self.last_exit_reason = "SL"
                self.last_exit_time = candle["timestamp"]
                return True

        return False

    def on_position_exit(self, pos, candle, ctx: "StrategyContext"):

        if pos.instrument is None:
            return None

        exit_side = "SELL" if pos.net_qty > 0 else "BUY"

        structure_id = pos.structure_id

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
