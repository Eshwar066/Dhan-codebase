"""
Futures_EMA_Momentum: Trend Breakout (EMA filter only).

Trend defines direction. Donchian defines entry. No ATR/volatility gating.
Simplified Turtle-style logic with trend bias. For crypto/futures (DELTA/DHAN).

Entry:
  Long:  close > EMA(200) and close > donchian_high (previous N bars, excl. current)
  Short: close < EMA(200) and close < donchian_low (previous N bars, excl. current)
Stop: 2 × ATR(14)
Risk per trade: 1% (sizing may require engine/capital context)
"""

import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from core.strategies.base import BaseStrategy
from core.strategies.IndiaMktMixins import IndiaMktMixins
from core.models.order_intent import OrderIntent

if TYPE_CHECKING:
    from core.models.strategy_context import StrategyContext


# Clean parameter set (e.g. BTC Daily)
EMA_TREND_PERIOD = 200
DONCHIAN_PERIOD = 20   # or test 55
ATR_PERIOD = 14
ATR_STOP_MULT = 2.0   # stop = 2 × ATR(14)
RISK_PER_TRADE_PCT = 0.01   # 1%; sizing needs capital from engine if applied
MAX_QTY = 1


class FuturesEMAMomentum(IndiaMktMixins, BaseStrategy):

    name = "Futures_EMA_Momentum"
    required_context = ["instrument_store"]

    def __init__(self):
        super().__init__()
        self._stage_state: Dict[str, Dict] = {}

    def get_warmup_period(self):
        return max(EMA_TREND_PERIOD + 20, DONCHIAN_PERIOD + ATR_PERIOD + 5)

    def should_evaluate(self, candle: Any) -> bool:
        return candle.get("close") is not None

    def _get_symbol_state(self, symbol: str) -> Dict:
        if symbol not in self._stage_state:
            self._stage_state[symbol] = {
                "long_entry_price": None,
                "long_entry_atr": None,
                "short_entry_price": None,
                "short_entry_atr": None,
            }
        return self._stage_state[symbol]

    @staticmethod
    def _ema(values: List[float], period: int) -> Optional[float]:
        if len(values) < period:
            return None
        k = 2 / (period + 1)
        ema = values[0]
        for price in values[1:]:
            ema = (price - ema) * k + ema
        return ema

    @staticmethod
    def _atr(
        highs: List[float], lows: List[float], closes: List[float], period: int
    ) -> Optional[float]:
        if (
            len(highs) < period + 1
            or len(lows) < period + 1
            or len(closes) < period + 1
        ):
            return None
        tr_list = []
        for i in range(1, len(closes)):
            high, low, prev_close = highs[i], lows[i], closes[i - 1]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_list.append(tr)
        if len(tr_list) < period:
            return None
        k = 2 / (period + 1)
        atr = sum(tr_list[:period]) / period
        for tr in tr_list[period:]:
            atr = (tr - atr) * k + atr
        return atr

    def _donchian_high(
        self, highs: List[float], period: int = DONCHIAN_PERIOD
    ) -> Optional[float]:
        """Previous N bars only, excluding current bar."""
        if len(highs) < period + 1:
            return None
        return max(highs[-period - 1 : -1])

    def _donchian_low(
        self, lows: List[float], period: int = DONCHIAN_PERIOD
    ) -> Optional[float]:
        """Previous N bars only, excluding current bar."""
        if len(lows) < period + 1:
            return None
        return min(lows[-period - 1 : -1])

    def on_candle(self, candle: Any, ctx: "StrategyContext") -> Optional[List[Any]]:
        symbol = candle["symbol"]
        close = float(candle["close"])
        high = float(candle["high"])
        low = float(candle["low"])

        state = self._get_symbol_state(symbol)
        n_need = max(EMA_TREND_PERIOD + 20, DONCHIAN_PERIOD + ATR_PERIOD + 5)
        candles = ctx.get_recent_candles(n_need)
        if len(candles) < EMA_TREND_PERIOD:
            return None

        closes = [float(c["close"]) for c in candles]
        highs = [float(c["high"]) for c in candles]
        lows = [float(c["low"]) for c in candles]

        ema_200 = self._ema(closes, EMA_TREND_PERIOD)
        donchian_high = self._donchian_high(highs, DONCHIAN_PERIOD)
        donchian_low = self._donchian_low(lows, DONCHIAN_PERIOD)
        atr = self._atr(highs, lows, closes, ATR_PERIOD)

        if (
            ema_200 is None
            or donchian_high is None
            or donchian_low is None
            or atr is None
        ):
            return None

        # Trend defines direction
        long_trend_ok = close > ema_200
        short_trend_ok = close < ema_200

        # Donchian defines entry (previous N bars, excl. current)
        long_entry = long_trend_ok and close > donchian_high
        short_entry = short_trend_ok and close < donchian_low

        exchange = candle.get("exchange") or "DELTA"
        inst = ctx.instrument_store.futures_intent_creation_details(
            symbol, exchange, expiry=None
        )
        if inst is None:
            return None

        structure_long = self.build_structure_id(candle, "LONG")
        structure_short = self.build_structure_id(candle, "SHORT")
        has_long = ctx.position_store.has_open_structure(
            strategy=self.name, structure_id=structure_long, tag="MAIN"
        )
        has_short = ctx.position_store.has_open_structure(
            strategy=self.name, structure_id=structure_short, tag="MAIN"
        )

        if has_long or has_short:
            return None

        qty = max(1, MAX_QTY)

        if long_entry:
            state["long_entry_price"] = close
            state["long_entry_atr"] = atr
            return [
                OrderIntent(
                    intent_id=uuid.uuid4().hex,
                    instrument=inst,
                    side="BUY",
                    qty=qty,
                    price=close,
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

        if short_entry:
            state["short_entry_price"] = close
            state["short_entry_atr"] = atr
            return [
                OrderIntent(
                    intent_id=uuid.uuid4().hex,
                    instrument=inst,
                    side="SELL",
                    qty=qty,
                    price=close,
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
        close = float(candle["close"])

        candles = ctx.get_recent_candles(ATR_PERIOD + 5)
        if len(candles) < ATR_PERIOD + 1:
            return False
        highs = [float(c["high"]) for c in candles]
        lows = [float(c["low"]) for c in candles]
        closes = [float(c["close"]) for c in candles]
        atr = self._atr(highs, lows, closes, ATR_PERIOD)
        if atr is None:
            return False

        stop_dist = ATR_STOP_MULT * atr

        if position.net_qty > 0:
            entry = state.get("long_entry_price")
            if entry is not None and stop_dist > 0 and close <= entry - stop_dist:
                return True
            return False

        if position.net_qty < 0:
            entry = state.get("short_entry_price")
            if entry is not None and stop_dist > 0 and close >= entry + stop_dist:
                return True
            return False
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
            s["long_entry_price"] = None
            s["long_entry_atr"] = None
        elif structure_id and "SHORT" in str(structure_id):
            s["short_entry_price"] = None
            s["short_entry_atr"] = None
