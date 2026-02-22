"""
Futures_EMA_Momentum: Supertrend + EMA breakout/breakdown, long and short.
Supertrend green = long only; supertrend red = short only.
For crypto/futures (DELTA/DHAN futures); uses futures_intent_creation_details.
"""

import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from core.strategies.base import BaseStrategy
from core.strategies.IndiaMktMixins import IndiaMktMixins
from core.models.order_intent import OrderIntent

if TYPE_CHECKING:
    from core.models.strategy_context import StrategyContext


class FuturesEMAMomentum(IndiaMktMixins, BaseStrategy):

    name = "Futures_EMA_Momentum"
    required_context = ["instrument_store"]

    def __init__(self):
        super().__init__()
        self._stage_state: Dict[str, Dict] = {}

    def should_evaluate(self, candle: Any) -> bool:
        close = candle.get("close")
        if close is None:
            return False
        return True

    def _get_symbol_state(self, symbol: str) -> Dict:
        if symbol not in self._stage_state:
            self._stage_state[symbol] = {
                "long_stage": 0,
                "long_stage_high": None,
                "long_entry_low": None,
                "short_stage": 0,
                "short_stage_low": None,
                "short_entry_high": None,
            }
        return self._stage_state[symbol]

    # def _ema(self, values, period=5):
    #     if len(values) < period:
    #         return None
    #     k = 2 / (period + 1)
    #     ema = values[0]
    #     for price in values[1:]:
    #         ema = (price - ema) * k + ema
    #     return ema

    def on_candle(self, candle: Any, ctx: "StrategyContext") -> Optional[List[Any]]:
        symbol = candle["symbol"]
        close = candle["close"]
        high = candle["high"]
        low = candle["low"]

        state = self._get_symbol_state(symbol)
        candles = ctx.get_recent_candles(25)
        if len(candles) < 15:
            return None

        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        ema5_high = self._ema(highs, 5)
        ema5_low = self._ema(lows, 5)
        if ema5_high is None or ema5_low is None:
            return None

        exchange = candle.get("exchange") or "DELTA"
        inst = ctx.instrument_store.futures_intent_creation_details(
            symbol, exchange, expiry=None
        )
        if inst is None:
            return None

        # Prefer LONG if we already have open long (scale-in only)
        structure_long = self.build_structure_id(candle, "LONG")
        structure_short = self.build_structure_id(candle, "SHORT")
        has_long = ctx.position_store.has_open_structure(
            strategy=self.name, structure_id=structure_long, tag="MAIN"
        )
        has_short = ctx.position_store.has_open_structure(
            strategy=self.name, structure_id=structure_short, tag="MAIN"
        )

        if has_long:
            if state["long_stage"] == 0:
                state["long_stage"] = 1
                state["long_stage_high"] = high
                state["long_entry_low"] = low
                qty = 1
            elif state["long_stage"] == 1 and close > state["long_stage_high"]:
                state["long_stage"] = 2
                state["long_stage_high"] = high
                qty = 1
            elif state["long_stage"] == 2 and close > state["long_stage_high"]:
                state["long_stage"] = 3
                state["long_stage_high"] = high
                qty = 1
            elif state["long_stage"] == 3 and close > state["long_stage_high"]:
                state["long_stage"] = 4
                state["long_stage_high"] = high
                qty = 1
            else:
                return None
            action = "SCALE_IN"
            return [
                OrderIntent(
                    intent_id=uuid.uuid4().hex,
                    instrument=inst,
                    side="BUY",
                    qty=qty,
                    price=float(close),
                    order_type="LIMIT",
                    strategy=self.name,
                    structure_id=structure_long,
                    trade_type="MARGIN",
                    tag="MAIN",
                    candle_ts=candle["timestamp"],
                    parent_intent_id=None,
                    symbol=symbol,
                    action="SCALE_IN",
                )
            ]

        if has_short:
            if state["short_stage"] == 0:
                state["short_stage"] = 1
                state["short_stage_low"] = low
                state["short_entry_high"] = high
                qty = 1
            elif state["short_stage"] == 1 and close < state["short_stage_low"]:
                state["short_stage"] = 2
                state["short_stage_low"] = low
                qty = 1
            elif state["short_stage"] == 2 and close < state["short_stage_low"]:
                state["short_stage"] = 3
                state["short_stage_low"] = low
                qty = 1
            elif state["short_stage"] == 3 and close < state["short_stage_low"]:
                state["short_stage"] = 4
                state["short_stage_low"] = low
                qty = 1
            else:
                return None
            return [
                OrderIntent(
                    intent_id=uuid.uuid4().hex,
                    instrument=inst,
                    side="SELL",
                    qty=qty,
                    price=float(close),
                    order_type="LIMIT",
                    strategy=self.name,
                    structure_id=structure_short,
                    trade_type="MARGIN",
                    tag="MAIN",
                    candle_ts=candle["timestamp"],
                    parent_intent_id=None,
                    symbol=symbol,
                    action="SCALE_IN",
                )
            ]

        if close > ema5_high:
            state["long_stage"] = 1
            state["long_stage_high"] = high
            state["long_entry_low"] = low
            return [
                OrderIntent(
                    intent_id=uuid.uuid4().hex,
                    instrument=inst,
                    side="BUY",
                    qty=1,
                    price=float(close),
                    order_type="LIMIT",
                    strategy=self.name,
                    structure_id=structure_long,
                    trade_type="MARGIN",
                    tag="MAIN",
                    candle_ts=candle["timestamp"],
                    parent_intent_id=None,
                    symbol=symbol,
                    action="ENTRY",
                )
            ]
        if close < ema5_low:
            state["short_stage"] = 1
            state["short_stage_low"] = low
            state["short_entry_high"] = high
            return [
                OrderIntent(
                    intent_id=uuid.uuid4().hex,
                    instrument=inst,
                    side="SELL",
                    qty=1,
                    price=float(close),
                    order_type="LIMIT",
                    strategy=self.name,
                    structure_id=structure_short,
                    trade_type="MARGIN",
                    tag="MAIN",
                    candle_ts=candle["timestamp"],
                    parent_intent_id=None,
                    symbol=symbol,
                    action="ENTRY",
                )
            ]
        return None

    def should_exit(
        self, position: Any, candle: Any, ctx: Optional["StrategyContext"] = None
    ) -> bool:
        if ctx is None:
            return False
        symbol = candle["symbol"]
        state = self._get_symbol_state(symbol)
        close = candle["close"]

        candles = ctx.get_recent_candles(5)
        if len(candles) < 2:
            return False
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        ema5_high = self._ema(highs, 5)
        ema5_low = self._ema(lows, 5)
        if ema5_high is None or ema5_low is None:
            return False

        if position.net_qty > 0:
            # Long exit
            if state["long_stage"] == 1:
                return close < state["long_entry_low"]
            return close < ema5_low or close < state["long_entry_low"]
        if position.net_qty < 0:
            # Short exit
            if state["short_stage"] == 1:
                return close > state["short_entry_high"]
            return close > ema5_high or close > state["short_entry_high"]
        return False

    def on_position_exit(
        self, position: Any, candle: Any, ctx: "StrategyContext"
    ) -> Optional[List[Any]]:
        if position.instrument is None:
            return None
        exit_side = "SELL" if position.net_qty > 0 else "BUY"
        exit_intent = OrderIntent(
            intent_id=uuid.uuid4().hex,
            instrument=position.instrument,
            side=exit_side,
            qty=abs(position.net_qty),
            price=float(candle["close"]),
            order_type="LIMIT",
            strategy=self.name,
            structure_id=position.structure_id
            or self.build_structure_id(candle, "LONG"),
            trade_type="MARGIN",
            tag="MAIN",
            candle_ts=candle["timestamp"],
            parent_intent_id=None,
            symbol=candle["symbol"],
            action="EXIT",
        )
        return [exit_intent]

    def on_structure_exit(
        self,
        strategy=None,
        structure_id=None,
        instrument=None,
        candle_ts=None,
        **kwargs
    ):
        super().on_structure_exit(
            strategy=strategy, structure_id=structure_id, **kwargs
        )
        if instrument is None or not getattr(instrument, "trading_symbol", None):
            return
        symbol = instrument.trading_symbol
        if symbol not in self._stage_state:
            return
        s = self._stage_state[symbol]
        if structure_id and "LONG" in str(structure_id):
            s["long_stage"] = 0
            s["long_stage_high"] = None
            s["long_entry_low"] = None
        elif structure_id and "SHORT" in str(structure_id):
            s["short_stage"] = 0
            s["short_stage_low"] = None
            s["short_entry_high"] = None
