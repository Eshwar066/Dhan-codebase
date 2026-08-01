"""
Gautham liquidity sweep — 4H liquidity sweep + inside-zone entry on 5m.

Rules
- Levels: active 4H liquidity zones from indicator history.
- When ``enable_swing_mode`` is True: only confirmed ``swing_4h`` fractal highs/lows.
  When False: also trade prior-bar ``prev_4h`` highs/lows (legacy behaviour).
- SHORT: high zone swept on 5m → when candle trades back inside the zone, enter;
  SL = that candle's high (entry near the liquidation level).
- LONG: low zone swept on 5m → when candle trades back inside the zone, enter;
  SL = that candle's low.
- Max 2 stop-outs per day; after each SL, require a fresh 4H-zone sweep before re-entry.
- Parent handles 1:2 partial (50%) + trail on remainder.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, Optional, TYPE_CHECKING

import pandas as pd

from core.strategies.crypto.LiquiditySweepStrategy.four_hour_liquidity import (
    FourHourLiquidityBook,
    LiquidityZone,
)
from core.utils import indicator_history as ind_hist

if TYPE_CHECKING:
    from core.models.strategy_context import StrategyContext

logger = logging.getLogger(__name__)

MAX_SL_PER_DAY = 2
SUB_NAME = "GauthamLiquiditySweep"
# Used when enable_swing_mode is True.
SWING_ZONE_SOURCES = frozenset({"swing_4h"})


@dataclass
class GauthamEntrySignal:
    side: str  # LONG | SHORT
    entry_price: float
    stop_price: float
    target_price: float
    risk: float
    substrategy: str = SUB_NAME
    # Sweep context for trade logs
    zone_price: Optional[float] = None
    zone_side: Optional[str] = None  # high | low
    zone_source: Optional[str] = None
    zone_bar_key: Optional[str] = None  # 4H reference candle (IST)
    sweep_bar_key: Optional[str] = None  # entry-TF bar that swept the zone (IST)


@dataclass
class _SymbolDayState:
    ist_date: Optional[date] = None
    sl_hits: int = 0
    setup_side: Optional[str] = None
    sweep_bar_key: Optional[str] = None
    armed_zone: Optional[LiquidityZone] = None
    consumed_sweeps: set = field(default_factory=set)


class GauthamLiquiditySweep:
    """Sub-strategy: 4H zone sweep on 5m + inside-zone entry (SL = candle extreme)."""

    name = SUB_NAME

    def __init__(
        self,
        zones: Optional[FourHourLiquidityBook] = None,
        *,
        enable_high_entries: bool = True,
        enable_low_entries: bool = True,
        enable_swing_mode: bool = True,
    ) -> None:
        self.zones = zones or FourHourLiquidityBook()
        # high sweep → SHORT; low sweep → LONG
        self.enable_high_entries = bool(enable_high_entries)
        self.enable_low_entries = bool(enable_low_entries)
        # True → swing_4h only; False → prev_4h + swing_4h
        self.enable_swing_mode = bool(enable_swing_mode)
        self._day: Dict[str, _SymbolDayState] = {}

    def _allowed_zone_sources(self) -> Optional[frozenset]:
        if self.enable_swing_mode:
            return SWING_ZONE_SOURCES
        return None

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
        st.sweep_bar_key = None
        st.armed_zone = None
        st.consumed_sweeps = set()

    def _clear_setup(self, st: _SymbolDayState) -> None:
        st.setup_side = None
        st.sweep_bar_key = None
        st.armed_zone = None

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
        self._clear_setup(st)
        logger.info(
            "GauthamLiquiditySweep SL hit %s sl_hits=%s/%s — await fresh 4H liquidity sweep",
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

    def _detect_sweep(
        self, symbol: str, candle: dict, st: _SymbolDayState
    ) -> Optional[tuple[str, LiquidityZone]]:
        bar_key = self._bar_key(candle)
        if not bar_key or bar_key in st.consumed_sweeps:
            return None
        hit = self.zones.detect_1m_sweep(
            symbol,
            candle,
            enable_high=self.enable_high_entries,
            enable_low=self.enable_low_entries,
            allowed_sources=self._allowed_zone_sources(),
        )
        if hit is None:
            return None
        return hit

    def _arm_setup(
        self, st: _SymbolDayState, side: str, zone: LiquidityZone, candle: dict
    ) -> None:
        bar_key = self._bar_key(candle)
        st.setup_side = side
        st.sweep_bar_key = bar_key
        st.armed_zone = zone
        if bar_key:
            st.consumed_sweeps.add(bar_key)
        self.zones.mark_consumed(
            str(candle.get("symbol") or ""), zone, swept_at=bar_key
        )
        logger.info(
            "GauthamLiquiditySweep armed %s side=%s zone=%.2f (%s/%s) bar=%s",
            candle.get("symbol"),
            side,
            zone.price,
            zone.side,
            zone.source,
            bar_key,
        )

    @staticmethod
    def _trades_inside_zone(candle: dict, zone: LiquidityZone, side: str) -> bool:
        """
        True when the entry-TF bar trades back inside the swept liquidity level.

        High zone (SHORT): wick/range reaches the level and close is at/below it.
        Low zone (LONG): wick/range reaches the level and close is at/above it.
        """
        try:
            h = float(candle["high"])
            l = float(candle["low"])
            c = float(candle["close"])
            z = float(zone.price)
        except (KeyError, TypeError, ValueError):
            return False
        if side == "SHORT":
            return l <= z and c <= z
        if side == "LONG":
            return h >= z and c >= z
        return False

    def _signal_from_candle(
        self,
        st: _SymbolDayState,
        candle: dict,
        *,
        side: str,
    ) -> Optional[GauthamEntrySignal]:
        try:
            entry = float(candle["close"])
            if side == "SHORT":
                stop = float(candle["high"])
                risk = stop - entry
            else:
                stop = float(candle["low"])
                risk = entry - stop
        except (KeyError, TypeError, ValueError):
            self._clear_setup(st)
            return None
        if risk <= 0:
            self._clear_setup(st)
            return None

        zone = st.armed_zone
        sweep_key = st.sweep_bar_key
        self._clear_setup(st)
        # Provisional 1:2 target; parent recalculates from fill + PARTIAL_TARGET_RR.
        target = entry - 2.0 * risk if side == "SHORT" else entry + 2.0 * risk
        return GauthamEntrySignal(
            side=side,
            entry_price=entry,
            stop_price=stop,
            target_price=target,
            risk=risk,
            zone_price=float(zone.price) if zone is not None else None,
            zone_side=str(zone.side) if zone is not None else None,
            zone_source=str(zone.source) if zone is not None else None,
            zone_bar_key=str(zone.bar_key) if zone is not None else None,
            sweep_bar_key=str(sweep_key) if sweep_key else None,
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

        sweep = self._detect_sweep(symbol, candle, st)
        if sweep and st.setup_side is None:
            sweep_side, zone = sweep
            self._arm_setup(st, sweep_side, zone, candle)

        side = st.setup_side
        zone = st.armed_zone
        if not side or zone is None:
            return None
        if side == "SHORT" and not self.enable_high_entries:
            self._clear_setup(st)
            return None
        if side == "LONG" and not self.enable_low_entries:
            self._clear_setup(st)
            return None

        if not self._trades_inside_zone(candle, zone, side):
            return None

        return self._signal_from_candle(st, candle, side=side)
