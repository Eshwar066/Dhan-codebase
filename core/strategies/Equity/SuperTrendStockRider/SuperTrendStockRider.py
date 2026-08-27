"""
SuperTrend Stock Rider - Equity Swing Strategy

- Universe: Nuvama & SG Mart stocks (from config)
- Timeframe: 1D
- Supertrend: 16, 1.7
- Entry: Supertrend turns green (bullish)
- Risk: If entry candle low breaks on any subsequent day → reduce 50% qty
- Exit: Supertrend turns red → exit full position
- Daily check at 15:15: If green signal today vs yesterday's close → enter
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, time, datetime, timedelta
from typing import Any, Dict, List, Optional, Set

import numpy as np
import pandas as pd

from run.config import RUN_MODE, RunMode
from core.strategies.base import BaseStrategy
from core.strategies.indicator_helpers import add_supertrend
from core.utils.expiry_resolver import ExpiryResolver
from core.utils.session.session_manager import SessionManager

logger = logging.getLogger(__name__)

# Default stocks (can be overridden via config)
DEFAULT_STOCKS = [
    "NUVAMA"   
]



@dataclass
class PositionState:
    """Track per-stock position state."""
    symbol: str
    qty: int = 0
    entry_price: float = 0.0
    entry_candle_low: float = 0.0
    entry_date: Optional[date] = None
    reduced: bool = False  # 50% reduction done
    supertrend_green: bool = False


class SuperTrendStockRider(BaseStrategy):
    """Supertrend-based equity swing with trailing stop at entry candle low."""

    name = "SuperTrendStockRider"
    underlying_symbols: List[str] = DEFAULT_STOCKS
    timeframe = "D"
    extra_timeframes: List[str] = []

    # Supertrend parameters
    supertrend_length = 16
    supertrend_factor = 1.7

    # Entry/Exit parameters
    check_time = time(15, 15)  # 3:15 PM check
    reduce_pct = 0.5  # 50% reduction on low break

    # Required context for indicator manager
    required_context: List[str] = []

    # Persisted indicator keys
    def persisted_indicator_keys(self) -> List[str]:
        return [
            "supertrend",
            "supertrend_direction",
            "supertrend_is_bullish",
            "supertrend_upper",
            "supertrend_lower",
            "supertrend_atr",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._positions: Dict[str, PositionState] = {}
        self._prev_supertrend: Dict[str, bool] = {}
        self._last_check_date: Optional[date] = None

    # -------------------------------------------------------------------------
    # Indicator preparation
    # -------------------------------------------------------------------------
    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute Supertrend(16, 1.7)."""
        df = add_supertrend(
            df,
            length=self.supertrend_length,
            factor=self.supertrend_factor,
        )
        return df

    # -------------------------------------------------------------------------
    # Signal detection
    # -------------------------------------------------------------------------
    def _get_supertrend_signal(self, candle: Dict[str, Any]) -> Optional[str]:
        """Get Supertrend direction: 'GREEN' (bullish) or 'RED' (bearish)."""
        is_bullish = candle.get("supertrend_is_bullish")
        if is_bullish is not None:
            return "GREEN" if is_bullish else "RED"
        dir_val = candle.get("supertrend_direction")
        if dir_val is not None and not pd.isna(dir_val):
            return "GREEN" if dir_val == 1.0 or dir_val == 1 else "RED"
        return None

    def _is_check_time(self, candle: Dict[str, Any]) -> bool:
        """Check if it's 15:15 PM (daily evaluation time)."""
        ts = pd.Timestamp(candle.get("timestamp"))
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC").tz_convert("Asia/Kolkata")
        else:
            ts = ts.tz_convert("Asia/Kolkata")
        return ts.time() >= self.check_time

    # -------------------------------------------------------------------------
    # Main evaluation
    # -------------------------------------------------------------------------
    def should_evaluate(self, candle: Dict[str, Any]) -> bool:
        """Evaluate on daily candles - in backtest mode evaluate all, in live only at 15:15."""
        tf = str(candle.get("timeframe", "")).strip()
        if tf not in ("D", "DAY"):
            return False
        # In backtest mode, evaluate every daily candle
        if RUN_MODE == RunMode.BACKTEST:
            return True
        return self._is_check_time(candle)

    def on_candle(self, candle: Dict[str, Any], ctx) -> Optional[List[Any]]:
        """Process daily candle."""
        symbol = str(candle.get("symbol", "")).strip().upper()
        if symbol not in self.underlying_symbols:
            return None

        # Initialize position state
        if symbol not in self._positions:
            self._positions[symbol] = PositionState(symbol=symbol)

        pos = self._positions[symbol]
        signal = self._get_supertrend_signal(candle)

        logger.debug(f"[{symbol}] on_candle: signal={signal}, pos.qty={pos.qty}, timeframe={candle.get('timeframe')}")

        if signal is None:
            return None

        prev_signal = self._prev_supertrend.get(symbol)
        self._prev_supertrend[symbol] = signal == "GREEN"

        # -----------------------------------------------------------------
        # 1. EXIT: Signal changed to RED -> full exit
        # -----------------------------------------------------------------
        if pos.qty > 0 and signal == "RED" and prev_signal == True:
            logger.info(f"[{symbol}] Supertrend turned RED -> FULL EXIT at {candle.get('close')}")
            return self._build_exit_intent(symbol, ctx, pos, "supertrend_red")

        # -----------------------------------------------------------------
        # 2. REDUCE: Entry candle low broken -> reduce 50%
        # -----------------------------------------------------------------
        if pos.qty > 0 and not pos.reduced and pos.entry_candle_low > 0:
            if float(candle.get("low", 0)) < pos.entry_candle_low:
                logger.info(f"[{symbol}] Entry low {pos.entry_candle_low} broken at {candle.get('low')} -> REDUCE 50%")
                return self._build_reduce_intent(symbol, ctx, pos)

        # -----------------------------------------------------------------
        # 3. ENTRY: Green signal
        # -----------------------------------------------------------------
        if pos.qty == 0 and signal == "GREEN":
            # In backtest: enter on green signal
            # In live: require close > prev_close at 15:15
            if RUN_MODE == RunMode.BACKTEST:
                logger.info(f"[{symbol}] Green signal -> ENTRY at {candle.get('close')}")
                return self._build_entry_intent(symbol, ctx, candle, pos)
            else:
                # Live: check close > prev_close at 15:15
                prev_close = self._get_prev_close(candle, ctx, symbol)
                today_close = float(candle.get("close", 0))
                if prev_close > 0 and today_close > prev_close:
                    logger.info(f"[{symbol}] Green signal at 15:15, close {today_close} > prev {prev_close} -> ENTRY")
                    return self._build_entry_intent(symbol, ctx, candle, pos)

        return None

    def _get_prev_close(self, candle: Dict[str, Any], ctx, symbol: str) -> float:
        """Get yesterday's close from indicator history or cache."""
        try:
            # Try to get from recent candles
            recent = self.get_recent_enriched_candles(ctx, symbol, 2)
            if len(recent) >= 2:
                return float(recent[-2].get("close", 0))
        except Exception:
            pass
        return 0.0

    def get_recent_enriched_candles(self, ctx, symbol: str, n: int) -> List[Dict[str, Any]]:
        """Get last n enriched candles for symbol."""
        # Use indicator_manager if available
        if hasattr(ctx, "indicator_manager") and ctx.indicator_manager:
            return ctx.indicator_manager.get_recent_enriched_candles(
                self, symbol, n, exchange="NSE"
            )
        return []

    # -------------------------------------------------------------------------
    # Intent builders
    # -------------------------------------------------------------------------

    def _build_entry_intent(self, symbol: str, ctx, candle: Dict[str, Any], pos: PositionState):
        """Create entry intent."""
        from core.events.types import Intent, IntentType

        # Determine qty (from config or default 100)
        lot_size = self._get_lot_size(symbol)
        qty = max(1, int(getattr(self, "base_qty", 100) / lot_size))

        intent = Intent(
            strategy=self.name,
            symbol=symbol,
            intent_type=IntentType.ENTRY,
            side="BUY",
            qty=qty,
            price=float(candle.get("close", 0)),
            order_type="MARKET",
            tag="ST_GREEN",
            metadata={
                "entry_candle_low": float(candle.get("low", 0)),
                "entry_date": str(candle.get("timestamp", "")[:10]),
                "supertrend_signal": "GREEN",
            },
        )

        # Update position state
        pos.qty = qty
        pos.entry_price = float(candle.get("close", 0))
        pos.entry_candle_low = float(candle.get("low", 0))
        pos.entry_date = pd.Timestamp(candle.get("timestamp")).date() if candle.get("timestamp") else None
        pos.supertrend_green = True
        pos.reduced = False

        return [intent]

    def _build_reduce_intent(self, symbol: str, ctx, pos: PositionState):
        """Create 50% reduction intent."""
        from core.events.types import Intent, IntentType

        reduce_qty = max(1, int(pos.qty * self.reduce_pct))

        intent = Intent(
            strategy=self.name,
            symbol=symbol,
            intent_type=IntentType.EXIT,
            side="SELL",
            qty=reduce_qty,
            price=0,  # Market
            order_type="MARKET",
            tag="ST_LOW_BREAK_50",
            metadata={
                "reason": "entry_low_broken",
                "original_qty": pos.qty,
                "reduce_qty": reduce_qty,
            },
        )

        pos.qty -= reduce_qty
        pos.reduced = True
        return [intent]

    def _build_exit_intent(self, symbol: str, ctx, pos: PositionState, reason: str):
        """Create full exit intent."""
        from core.events.types import Intent, IntentType

        intent = Intent(
            strategy=self.name,
            symbol=symbol,
            intent_type=IntentType.EXIT,
            side="SELL",
            qty=pos.qty,
            price=0,  # Market
            order_type="MARKET",
            tag=f"ST_{reason.upper()}",
            metadata={"reason": reason, "original_qty": pos.qty},
        )

        # Reset position
        pos.qty = 0
        pos.entry_price = 0.0
        pos.entry_candle_low = 0.0
        pos.entry_date = None
        pos.reduced = False
        pos.supertrend_green = False

        return [intent]

    def on_structure_exit(self, *args, **kwargs):
        """Required by backtest engine - called when position structure exits."""
        return None

    def _get_lot_size(self, symbol: str) -> int:
        """Get lot size (default 1 for equity)."""
        return 1

    # -------------------------------------------------------------------------
    # Warmup
    # -------------------------------------------------------------------------
    def get_warmup_period(self) -> int:
        return max(self.supertrend_length * 3, 60)  # ~60 days

    # -------------------------------------------------------------------------
    # Backtest engine required methods
    # -------------------------------------------------------------------------
    def on_candle_rollover(self, *args, **kwargs):
        """Required by backtest engine - called on candle rollover."""
        return None

    def on_structure_exit(self, *args, **kwargs):
        """Required by backtest engine - called when position structure exits."""
        return None

    def should_exit(self, pos, candle, ctx) -> bool:
        """Check if position should be exited."""
        symbol = pos.symbol if hasattr(pos, "symbol") else pos.get("symbol", "")
        signal = self._get_supertrend_signal(candle)

        # Exit on Supertrend red
        if signal == "RED":
            return True

        # Exit if entry candle low broken (full exit after 50% reduction)
        pos_state = self._positions.get(symbol)
        if pos_state and pos_state.reduced and pos_state.entry_candle_low > 0:
            if float(candle.get("low", 0)) < pos_state.entry_candle_low:
                return True

        return False

    def on_position_exit(self, pos, candle, ctx):
        """Generate exit intents for position."""
        symbol = pos.symbol if hasattr(pos, "symbol") else pos.get("symbol", "")
        pos_state = self._positions.get(symbol)

        if not pos_state:
            return []

        from core.events.types import Intent, IntentType

        intent = Intent(
            strategy=self.name,
            symbol=symbol,
            intent_type=IntentType.EXIT,
            side="SELL",
            qty=pos_state.qty,
            price=0,
            order_type="MARKET",
            tag="ST_EXIT",
            metadata={"reason": "supertrend_exit"},
        )

        # Reset position state
        pos_state.qty = 0
        pos_state.entry_price = 0.0
        pos_state.entry_candle_low = 0.0
        pos_state.entry_date = None
        pos_state.reduced = False
        pos_state.supertrend_green = False

        return [intent]