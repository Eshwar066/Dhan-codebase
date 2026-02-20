"""
IPO Anchor VWAP Breakout – equity strategy for Dhan broker.

Entry  : Close > Anchor VWAP
Exit   : Close < Anchor VWAP
Universe: IPO stocks listed within last 365 days (time-aware).
Anchor VWAP logic handled inside IndiaMktMixins.
"""

import uuid
from datetime import date
from typing import TYPE_CHECKING, Any, Dict, Optional, Set

from core.strategies.base import BaseStrategy
from core.strategies.IndiaMktMixins import IndiaMktMixins
from core.models.order_intent import OrderIntent

if TYPE_CHECKING:
    from core.models.strategy_context import StrategyContext


IPO_DAYS = 365


class IPOBreakout(IndiaMktMixins, BaseStrategy):

    name = "IPOAnchorVWAP"
    required_context = ["instrument_store"]
    api = "NSE"

    def __init__(self):
        # Cache IPO universe per date
        self._ipo_stocks_cache: Dict[date, Set[str]] = {}
        self._anchor_state = {}

    # ------------------------------------------------------------------ #
    # ENTRY EVALUATION
    # ------------------------------------------------------------------ #
    def should_evaluate(self, candle: Any) -> bool:
        close = candle.get("close")
        if close is None:
            return False

        anchor_vwap = self._update_anchor_vwap(candle)
        if anchor_vwap is None:
            return False

        return close > anchor_vwap

    # ------------------------------------------------------------------ #
    # ENTRY EXECUTION
    # ------------------------------------------------------------------ #
    def on_candle(self, candle: Any, ctx: "StrategyContext"):

        symbol = candle["symbol"]

        structure_id = self.build_structure_id(candle, "IPO_LONG")

        # Avoid duplicate open structure
        if ctx.position_store.has_open_structure(
            strategy=self.name, structure_id=structure_id, tag="MAIN"
        ):
            return None

        store = ctx.instrument_store
        inst = store.equity_intent_creation_details(
            symbol, candle.get("exchange") or "NSE"
        )

        if inst is None:
            return None

        intent = OrderIntent(
            intent_id=uuid.uuid4().hex,
            instrument=inst,
            side="BUY",
            qty=1,
            price=float(candle["close"]),
            order_type="LIMIT",
            strategy=self.name,
            structure_id=structure_id,
            trade_type="MARGIN",
            tag="MAIN",
            candle_ts=candle["timestamp"],
            parent_intent_id=None,
            symbol=symbol,
            action="ENTRY",
        )

        return [intent]

    # ------------------------------------------------------------------ #
    # EXIT CONDITION
    # ------------------------------------------------------------------ #
    def should_exit(
        self, position: Any, candle: Any, ctx: Optional["StrategyContext"] = None
    ) -> bool:

        if not position or position.net_qty <= 0:
            return False

        close = candle.get("close")
        if close is None:
            return False

        anchor_vwap = self._update_anchor_vwap(candle)
        if anchor_vwap is None:
            return False

        return close < anchor_vwap

    # ------------------------------------------------------------------ #
    # EXIT EXECUTION
    # ------------------------------------------------------------------ #
    def on_position_exit(self, position: Any, candle: Any, ctx: "StrategyContext"):

        inst = position.instrument
        if inst is None:
            return None

        intent = OrderIntent(
            intent_id=uuid.uuid4().hex,
            instrument=inst,
            side="SELL",
            qty=abs(position.net_qty),
            price=float(candle["close"]),
            order_type="LIMIT",
            strategy=self.name,
            structure_id=position.structure_id,
            trade_type="MARGIN",
            tag="MAIN",
            candle_ts=candle["timestamp"],
            parent_intent_id=None,
            symbol=candle["symbol"],
            action="EXIT",
        )

        return [intent]
