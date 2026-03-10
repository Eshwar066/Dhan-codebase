"""
SignalFloodTestStrategy: pipeline test strategy for both Delta and Dhan.

- Generates entry/exit every 1m candle to exercise OMS, RiskManager, PositionManager.
- Alternates BUY/SELL when flat; exits after one candle when in position.
- 10% of entries use oversized qty (to trigger risk rejection).
- 10% of entries return duplicate intents (to trigger duplicate_signal_blocked).
- Uses futures instrument and IndiaMktMixins for intent creation.
"""

import random
from dataclasses import replace
from typing import Any, List, Optional, TYPE_CHECKING
import pdb

from core.strategies.base import BaseStrategy
from core.strategies.IndiaMktMixins import IndiaMktMixins

if TYPE_CHECKING:
    from core.models.strategy_context import StrategyContext


class SignalFloodTestStrategy(IndiaMktMixins, BaseStrategy):
    """Test strategy: signal every 1m, alternate BUY/SELL, force exits, optional oversize/duplicate."""

    name = "SignalFloodTest"
    timeframe = "1"
    required_context = ["instrument", "qty", "intent_builder"]
    api = "DELTA"  # Set from instrument_store in on_candle

    def __init__(self):
        super().__init__()
        self._next_side = "BUY"
        self._last_candle: Optional[dict] = None

    def _exchange_from_store(self, ctx: "StrategyContext") -> str:
        """Infer exchange (DELTA or NSE) from instrument store type."""
        store = getattr(ctx, "instrument_store", None)
        if store is None:
            return "DELTA"
        name = type(store).__name__
        return "DELTA" if "Delta" in name else "NSE"

    def should_evaluate(self, candle: dict) -> bool:
        """Evaluate on every closed 1m candle."""
        return True

    def on_candle(self, candle: Any, ctx: "StrategyContext") -> Optional[Any]:
        """Alternate BUY/SELL when flat; return exit handled by should_exit + on_position_exit."""

        self._last_candle = candle
        self.api = self._exchange_from_store(ctx)
        symbol = candle.get("symbol")
        if not symbol:
            return None

        structure_id = f"{self.name}:{symbol}:FLAT"

        has_open = ctx.position_store.has_open_structure(
            strategy=self.name,
            structure_id=structure_id,
            tag="MAIN",
        )
        has_pending = (
            ctx.intent_store.has_pending_intent(
                strategy=self.name,
                structure_id=structure_id,
            )
            if getattr(ctx, "intent_store", None)
            else False
        )

        if has_open or has_pending:
            return None
     

        # Resolve instrument
        exchange = self.api
        expiry = None
        if exchange == "NSE":
            from core.strategies.IndiaMktMixins import IndiaMktMixins

            if hasattr(self, "getExpiry"):
                expiry = self.getExpiry(ctx)
        inst = ctx.instrument_store.futures_intent_creation_details(
            trading_symbol=symbol, exchange=exchange, expiry=expiry
        )
        if inst is None:
            return None
        if getattr(inst, "lot_size", 0) <= 0:
            inst.lot_size = 1

        side = self._next_side
        self._next_side = "SELL" if side == "BUY" else "BUY"
        structure_id = f"{self.name}:{symbol}:FLAT"

        # 10% oversized qty (to trigger risk rejection)
        qty = int(inst.lot_size)
        # if random.random() < 0.10:
        #     qty = max(qty, 99999)

        intent = self.map_futures_instrument_to_intent(
            inst=inst,
            strike_row=candle,
            strategy=self.name,
            side=side,
            structure_id=structure_id,
            candle_ts=candle.get("timestamp"),
            symbol=symbol,
            action="ENTRY",
            tag="MAIN",
        )
        if intent and qty != int(inst.lot_size):
            intent = replace(intent, qty=qty)
        # 10% return same intent twice to trigger duplicate_signal_blocked on second
        # if random.random() < 0.10 and intent:
        #     return [intent, intent]
        return [intent] if intent else None

    def should_exit(
        self, pos: Any, candle: Any, ctx: Optional["StrategyContext"] = None
    ) -> bool:
        """Exit after one candle (always exit when in position for this test)."""

        return True

    def on_position_exit(
        self, pos: Any, candle: Any, ctx: "StrategyContext"
    ) -> Optional[List[Any]]:
        """Build exit intent from position."""
        # pdb.set_trace()
        if pos.instrument is None:
            return None
        exit_side = "SELL" if pos.net_qty > 0 else "BUY"
        strike_row = self._last_candle if self._last_candle is not None else candle
        exit_intent = self.map_futures_instrument_to_intent(
            inst=pos.instrument,
            strike_row=strike_row,
            strategy=self.name,
            side=exit_side,
            structure_id=pos.structure_id
            or f"{self.name}:{strike_row.get('symbol', '')}:FLAT",
            candle_ts=candle.get("timestamp"),
            symbol=candle.get("symbol", ""),
            action="EXIT",
            tag="MAIN",
            parent_intent_id=None,
        )
        return [exit_intent] if exit_intent else None
