"""
Gautham liquidity sweep — PDH/PDL sweep + two-candle reversal entry on 1m.

Rules (IST calendar day)
- Levels: previous day high / low (``pdh`` / ``pdl`` + ``sweep_pdh`` / ``sweep_pdl``).
- SHORT: PDH swept → 1st red 1m bar → 2nd red breaks 1st red low → enter; SL = 1st red high.
- LONG: PDL swept → 1st green 1m bar → 2nd green breaks 1st green high → enter; SL = 1st green low.
- Max 2 stop-outs per day; after each SL, require a fresh sweep before re-entry.
- Parent handles 1:1 partial (50%) + trail on remainder.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import pandas as pd

from core.utils import indicator_history as ind_hist

if TYPE_CHECKING:
    from core.models.strategy_context import StrategyContext

logger = logging.getLogger(__name__)

MAX_SL_PER_DAY = 2
SUB_NAME = "GauthamLiquiditySweep"


@dataclass
class GauthamEntrySignal:
    side: str  # LONG | SHORT
    entry_price: float
    stop_price: float
    target_price: float
    risk: float
    substrategy: str = SUB_NAME


@dataclass
class _SymbolDayState:
    ist_date: Optional[date] = None
    sl_hits: int = 0
    setup_side: Optional[str] = None
    phase: str = "idle"
    first_rev_high: float = 0.0
    first_rev_low: float = 0.0
    sweep_bar_key: Optional[str] = None
    consumed_sweeps: set = field(default_factory=set)


class GauthamLiquiditySweep:
    """Sub-strategy logic for PDH/PDL sweep + dual reversal candle entries."""

    name = SUB_NAME

    def __init__(self) -> None:
        self._day: Dict[str, _SymbolDayState] = {}

    @staticmethod
    def _ist_date(candle: dict) -> Optional[date]:
        ts = candle.get("timestamp")
        if ts is None:
            return None
        try:
            return pd.to_datetime(ts, utc=True).tz_convert(ind_hist.IST).date()
        except (TypeError, ValueError):
            return ind_hist.row_timestamp_to_ist(ts).date() if ind_hist.row_timestamp_to_ist(ts) else None

    @staticmethod
    def _bar_key(candle: dict) -> Optional[str]:
        k = candle.get("candle_timestamp_ist")
        if k:
            return ind_hist.normalize_ist_bar_key(k)
        ts = candle.get("timestamp")
        if ts is None:
            return None
        try:
            ist = pd.to_datetime(ts, utc=True).tz_convert(ind_hist.IST)
            return ind_hist.normalize_ist_bar_key(ist.strftime("%Y-%m-%d %H:%M"))
        except (TypeError, ValueError):
            return None

    def _state(self, symbol: str) -> _SymbolDayState:
        sym = symbol.strip().upper()
        if sym not in self._day:
            self._day[sym] = _SymbolDayState()
        return self._day[sym]

    def _roll_day(self, st: _SymbolDayState, d: date) -> None:
        if st.ist_date == d:
            return
        st.ist_date = d
        st.sl_hits = 0
        st.setup_side = None
        st.phase = "idle"
        st.first_rev_high = 0.0
        st.first_rev_low = 0.0
        st.sweep_bar_key = None
        st.consumed_sweeps = set()

    @staticmethod
    def _flag(val: Any) -> bool:
        n = pd.to_numeric(val, errors="coerce")
        if pd.isna(n):
            return bool(val)
        try:
            return int(n) != 0
        except (TypeError, ValueError):
            return bool(val)

    @staticmethod
    def _is_red(candle: dict) -> bool:
        try:
            o = float(candle.get("open"))
            c = float(candle.get("close"))
        except (TypeError, ValueError):
            return False
        return c < o

    @staticmethod
    def _is_green(candle: dict) -> bool:
        try:
            o = float(candle.get("open"))
            c = float(candle.get("close"))
        except (TypeError, ValueError):
            return False
        return c > o

    def on_sl_hit(self, symbol: str, candle: dict) -> None:
        """Reset sweep arm after SL; count toward daily SL budget."""
        sym = str(symbol or "").strip().upper()
        if not sym:
            return
        st = self._state(sym)
        d = self._ist_date(candle)
        if d is not None:
            self._roll_day(st, d)
        st.sl_hits += 1
        st.setup_side = None
        st.phase = "idle"
        st.sweep_bar_key = None
        logger.info(
            "GauthamLiquiditySweep SL hit %s sl_hits=%s/%s — await fresh PDH/PDL sweep",
            sym,
            st.sl_hits,
            MAX_SL_PER_DAY,
        )

    def _has_open_position(self, symbol: str, ctx: "StrategyContext", strategy_name: str) -> bool:
        for p in ctx.position_store.get_open_positions(
            underlying=symbol, strategy=strategy_name
        ) or []:
            if p and int(getattr(p, "net_qty", 0) or 0) != 0:
                return True
        return False

    def _detect_sweep(self, candle: dict, st: _SymbolDayState) -> Optional[str]:
        bar_key = self._bar_key(candle)
        if not bar_key or bar_key in st.consumed_sweeps:
            return None
        if self._flag(candle.get("sweep_pdh")):
            pdh = pd.to_numeric(candle.get("pdh"), errors="coerce")
            if not pd.isna(pdh):
                return "SHORT"
        if self._flag(candle.get("sweep_pdl")):
            pdl = pd.to_numeric(candle.get("pdl"), errors="coerce")
            if not pd.isna(pdl):
                return "LONG"
        return None

    def _arm_setup(self, st: _SymbolDayState, side: str, candle: dict) -> None:
        bar_key = self._bar_key(candle)
        st.setup_side = side
        st.phase = "idle"
        st.first_rev_high = 0.0
        st.first_rev_low = 0.0
        st.sweep_bar_key = bar_key
        if bar_key:
            st.consumed_sweeps.add(bar_key)
        logger.info(
            "GauthamLiquiditySweep armed %s side=%s pdh=%s pdl=%s bar=%s",
            candle.get("symbol"),
            side,
            candle.get("pdh"),
            candle.get("pdl"),
            bar_key,
        )

    def evaluate(
        self,
        candle: dict,
        ctx: "StrategyContext",
        *,
        strategy_name: str,
    ) -> Optional[GauthamEntrySignal]:
        symbol = str(candle.get("symbol") or "").strip().upper()
        if not symbol or candle.get("close") is None:
            return None

        st = self._state(symbol)
        d = self._ist_date(candle)
        if d is None:
            return None
        self._roll_day(st, d)

        if st.sl_hits >= MAX_SL_PER_DAY:
            return None
        if self._has_open_position(symbol, ctx, strategy_name):
            return None

        sweep_side = self._detect_sweep(candle, st)
        if sweep_side and st.setup_side is None:
            self._arm_setup(st, sweep_side, candle)

        side = st.setup_side
        if not side:
            return None

        if side == "SHORT":
            if st.phase == "idle":
                if self._is_red(candle):
                    st.phase = "saw_first"
                    st.first_rev_high = float(candle["high"])
                    st.first_rev_low = float(candle["low"])
                return None
            if st.phase == "saw_first":
                if not self._is_red(candle):
                    st.setup_side = None
                    st.phase = "idle"
                    return None
                if float(candle["low"]) >= st.first_rev_low:
                    return None
                entry = float(candle["close"])
                stop = float(st.first_rev_high)
                risk = stop - entry
                if risk <= 0:
                    st.setup_side = None
                    st.phase = "idle"
                    return None
                st.setup_side = None
                st.phase = "idle"
                return GauthamEntrySignal(
                    side="SHORT",
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry - risk,
                    risk=risk,
                )
            return None

        # LONG
        if st.phase == "idle":
            if self._is_green(candle):
                st.phase = "saw_first"
                st.first_rev_high = float(candle["high"])
                st.first_rev_low = float(candle["low"])
            return None
        if st.phase == "saw_first":
            if not self._is_green(candle):
                st.setup_side = None
                st.phase = "idle"
                return None
            if float(candle["high"]) <= st.first_rev_high:
                return None
            entry = float(candle["close"])
            stop = float(st.first_rev_low)
            risk = entry - stop
            if risk <= 0:
                st.setup_side = None
                st.phase = "idle"
                return None
            st.setup_side = None
            st.phase = "idle"
            return GauthamEntrySignal(
                side="LONG",
                entry_price=entry,
                stop_price=stop,
                target_price=entry + risk,
                risk=risk,
            )
        return None
