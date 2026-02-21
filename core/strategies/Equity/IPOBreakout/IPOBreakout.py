import uuid
from datetime import date
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from core.strategies.base import BaseStrategy
from core.strategies.IndiaMktMixins import IndiaMktMixins
from core.models.order_intent import OrderIntent

if TYPE_CHECKING:
    from core.models.strategy_context import StrategyContext


class IPOBreakout(IndiaMktMixins, BaseStrategy):

    name = "IPOAnchorVWAP"
    required_context = ["instrument_store"]

    def __init__(self):
        super().__init__()
        self._anchor_state = {}
        self._stage_state: Dict[str, Dict] = {}  # per-symbol stage tracking

    def should_evaluate(self, candle: Any) -> bool:
        close = candle.get("close")
        if close is None:
            return False

        anchor_vwap = self._update_anchor_vwap(candle)
        if anchor_vwap is None:
            return False

        return close > anchor_vwap

    # ------------------------------------------------------------------ #
    # HELPERS
    # ------------------------------------------------------------------ #

    def _get_symbol_state(self, symbol: str) -> Dict:
        if symbol not in self._stage_state:
            self._stage_state[symbol] = {
                "stage": 0,
                "stage_high": None,
                "entry_low": None,
                "listing_high": None,
                "candles_since_listing": 0,
                "below_listing_count": 0,
            }
        return self._stage_state[symbol]

    def _ema(self, values, period=5):
        if len(values) < period:
            return None

        k = 2 / (period + 1)
        ema = values[0]

        for price in values[1:]:
            ema = (price - ema) * k + ema

        return ema

    # ------------------------------------------------------------------ #
    # ENTRY LOGIC
    # ------------------------------------------------------------------ #

    def on_candle(self, candle: Any, ctx: "StrategyContext"):

        symbol = candle["symbol"]
        close = candle["close"]
        high = candle["high"]
        low = candle["low"]
        volume = candle.get("volume", 0)

        state = self._get_symbol_state(symbol)

        # --- Update anchor VWAP ---
        anchor_vwap = self._update_anchor_vwap(candle)
        if anchor_vwap is None:
            return None

        # --- Get recent candles (from context; filled by BacktestEngine) ---
        candles = ctx.get_recent_candles(20)
        if len(candles) < 10:
            return None

        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]

        ema5_high = self._ema(highs, 5)
        ema5_low = self._ema(lows, 5)

        if ema5_high is None or ema5_low is None:
            return None

        prev_candle = candles[-2]
        prev_high = prev_candle["high"]
        prev_low = prev_candle["low"]

        # --- Track listing behaviour ---
        if state["listing_high"] is None:
            state["listing_high"] = candles[0]["high"]

        state["candles_since_listing"] += 1

        if close < state["listing_high"]:
            state["below_listing_count"] += 1

        # -----------------------------------------------------
        # BASE ENTRY CONDITIONS
        # -----------------------------------------------------

        base_conditions = (
            state["candles_since_listing"] >= 10
            and state["below_listing_count"] >= 5
            and close > anchor_vwap
            and close > ema5_high
        )

        if not base_conditions:
            return None

        # -----------------------------------------------------
        # STAGE LOGIC
        # -----------------------------------------------------

        structure_id = self.build_structure_id(candle, "IPO_LONG")

        if state["stage"] == 0:
            # Stage 1
            state["stage"] = 1
            state["stage_high"] = high
            state["entry_low"] = low
            qty = 1  # 1/4

        elif state["stage"] == 1 and close > state["stage_high"]:
            # Stage 2
            state["stage"] = 2
            state["stage_high"] = high
            qty = 2  # 2/4

        elif state["stage"] == 2 and close > state["stage_high"]:
            # Stage 3
            state["stage"] = 3
            state["stage_high"] = high
            qty = 3  # 3/4

        elif state["stage"] == 3 and close > state["stage_high"]:
            # Stage 4
            state["stage"] = 4
            state["stage_high"] = high
            qty = 4  # full

        else:
            return None

        inst = ctx.instrument_store.equity_intent_creation_details(
            symbol, candle.get("exchange") or "NSE"
        )
        if inst is None:
            return None

        # OMS: use SCALE_IN when adding to existing position (stages 2–4); ENTRY only for first (stage 1).
        # PositionManager raises if action=="ENTRY" and prev_qty != 0; RiskManager blocks duplicate ENTRY for same structure.
        has_open = ctx.position_store.has_open_structure(
            strategy=self.name, structure_id=structure_id, tag="MAIN"
        )
        action = "SCALE_IN" if has_open else "ENTRY"

        return [
            OrderIntent(
                intent_id=uuid.uuid4().hex,
                instrument=inst,
                side="BUY",
                qty=qty,
                price=float(close),
                order_type="LIMIT",
                strategy=self.name,
                structure_id=structure_id,
                trade_type="MARGIN",
                tag="MAIN",
                candle_ts=candle["timestamp"],
                parent_intent_id=None,
                symbol=symbol,
                action=action,
            )
        ]

    # ------------------------------------------------------------------ #
    # EXIT LOGIC
    # ------------------------------------------------------------------ #

    def should_exit(self, position: Any, candle: Any, ctx=None) -> bool:

        symbol = candle["symbol"]
        state = self._get_symbol_state(symbol)

        close = candle["close"]
        low = candle["low"]

        candles = ctx.get_recent_candles(5)
        if len(candles) < 2:
            return False

        prev_low = candles[-2]["low"]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]

        ema5_high = self._ema(highs, 5)
        ema5_low = self._ema(lows, 5)

        if ema5_high is None or ema5_low is None:
            return False

        if state["stage"] == 1:
            return close < state["entry_low"]

        elif state["stage"] == 2:
            return close < ema5_low or close < prev_low or close < state["entry_low"]

        elif state["stage"] == 3:
            return close < ema5_low or close < prev_low or close < state["entry_low"]

        elif state["stage"] == 4:
            return close < ema5_low or close < prev_low or close < state["entry_low"]

        return False

    def on_position_exit(
        self, position: Any, candle: Any, ctx: "StrategyContext"
    ) -> Optional[List[Any]]:
        """Build exit intent for equity position (SELL to close long). Same pattern as Futures_EMA.on_position_exit."""
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
            or self.build_structure_id(candle, "IPO_LONG"),
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
        """On full exit (net qty 0): reset only position/stage so next entry can trigger; keep listing stats so we don't require 10 candles again."""
        super().on_structure_exit(
            strategy=strategy, structure_id=structure_id, **kwargs
        )
        if instrument is not None and getattr(instrument, "trading_symbol", None):
            symbol = instrument.trading_symbol
            if symbol in self._stage_state:
                # Reset only stage/position fields; keep listing_high, candles_since_listing, below_listing_count
                # so base_conditions can be true on the next candle without waiting 10 bars again
                self._stage_state[symbol]["stage"] = 0
                self._stage_state[symbol]["stage_high"] = None
                self._stage_state[symbol]["entry_low"] = None
            # Do not clear _anchor_state: anchor is cumulative VWAP from the 1st candle
