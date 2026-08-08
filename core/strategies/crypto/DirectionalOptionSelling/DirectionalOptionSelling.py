"""Multi-symbol SuperTrend directional option selling on Delta Exchange."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from run.config import RUN_MODE, RunMode
from core.strategies.base import BaseStrategy
from core.strategies.IndiaMktMixins import IST, IndiaMktMixins
from core.strategies.deltaMktMixins import DeltaMktMixins, _delta_source_from_ctx
from core.strategies.meta import pack_strategy_meta, unpack_strategy_meta
from core.utils.structure.supertrend import add_supertrend, supertrend_column_names

from .constants import (
    HTF_TIMEFRAMES,
    MAIN_SL_LIMIT_ABOVE_TRIGGER_MAX,
    MAIN_SL_LIMIT_ABOVE_TRIGGER_MIN,
    META_KEY,
    MIN_PREMIUM_USD,
    MIN_PREMIUM_USD_MORNING,
    MIN_STRIKE_SPOT_DISTANCE,
    MONTHLY_MIN_DTE,
    MORNING_ENTRY_TIME,
    MORNING_MIN_STRIKE_DISTANCE,
    ORDER_QTY_LOTS,
    ORDER_QTY_LOTS_DAILY,
    ORDER_QTY_LOTS_MONTHLY,
    ORDER_QTY_LOTS_MORNING,
    ORDER_QTY_LOTS_WEEKLY,
    PREMIUM_SL_MULT,
    ROLLOVER_MIN_STRIKE_DISTANCE,
    ROLLOVER_TIME,
    SLEEVE_DAILY,
    SLEEVE_MONTHLY,
    SLEEVE_MORNING,
    SLEEVE_WEEKLY,
    SL_MODE_INDEX,
    SL_MODE_PREMIUM,
    STRIKE_PROXIMITY_EXIT_POINTS,
    SUPER_TREND_FACTOR,
    SUPER_TREND_LENGTH,
    SUPPORTED_UNDERLYINGS,
    # Re-exported for tests / callers that import from this module.
    TRAIL_SL_PENDING_RETRY_GAP_SEC,
    TRAIL_SL_POINTS,
    WEEKLY_MIN_DTE,
    normalize_underlying,
    option_root_for,
    symbol_config,
    underlying_from_option_symbol,
)
from .htf import DosHtfMixin
from .trail_sl import DosTrailSlMixin, PendingTrailRetry as _PendingTrailRetry

logger = logging.getLogger(__name__)

# Sleeve entry switches (flip to False to stop new entries / SL re-entries for
# that sleeve globally). Open positions still trail SL, force-exit, and roll.
# Per-symbol enable_* in SYMBOL_CONFIG can further disable a sleeve.
ENABLE_WEEKLY_TRADES = True
ENABLE_MONTHLY_TRADES = True
ENABLE_INTRADAY_TRADES = True
ENABLE_MORNING_0DTE_TRADES = True
# Per-underlying master switches (False = no new entries / SL re-entries for that
# symbol). Open risk still trails, force-exits, and rolls.
ENABLE_BTCUSD_TRADES = True
ENABLE_ETHUSD_TRADES = False
# Weekly / monthly strike pick: when True, skip nearest eligible OTM (OTM1) and take the
# next (OTM2); if that fails premium, fall through to OTM3+. Daily/morning
# sleeves always use nearest eligible (OTM1). Per-symbol deeper-OTM also applies.
ENABLE_WEEKLY_DEEPER_OTM = True


@dataclass
class _SymbolRuntime:
    """Per-underlying signal / pending state (BTC and ETH must not share)."""

    confirmed_direction: Optional[int] = None
    current_supertrend: Optional[float] = None
    confirmed_4h_direction: Optional[int] = None
    confirmed_1d_direction: Optional[int] = None
    current_4h_supertrend: Optional[float] = None
    current_1d_supertrend: Optional[float] = None
    last_seen_4h_bar_open: Optional[pd.Timestamp] = None
    htf_st_cache: Dict[str, Tuple[int, float, pd.Timestamp]] = field(
        default_factory=dict
    )
    pending_transition: Optional["_PendingTransition"] = None
    pending_closed_entry: Optional["_PendingClosedEntry"] = None
    sl_reentry_direction: Optional[int] = None
    sl_reentry_after: Optional[pd.Timestamp] = None
    sl_reentry_sleeve: Optional[str] = None
    morning_entry_dates: set = field(default_factory=set)
    rollover_dates: set = field(default_factory=set)


@dataclass(frozen=True)
class _PositionMeta:
    symbol: str
    direction: int
    option_type: str
    supertrend: float
    strike: float
    expiry: str
    entry_premium: float
    entry_reason: str
    sleeve: str = SLEEVE_DAILY
    # premium = option-mark SL at 2× entry; index = spot SuperTrend trail.
    sl_mode: str = SL_MODE_PREMIUM


@dataclass(frozen=True)
class _PendingTransition:
    previous_structure_id: str
    direction: int
    reason: str
    min_dte: int = 0
    min_strike_distance: float = 0.0
    sleeve: str = SLEEVE_DAILY


@dataclass(frozen=True)
class _PendingClosedEntry:
    """Entry retry after transition EXIT fill when immediate ENTRY could not be built."""

    direction: int
    reason: str
    armed_after: pd.Timestamp
    min_dte: int = 0
    min_strike_distance: float = 0.0
    sleeve: str = SLEEVE_DAILY


class DirectionalOptionSelling(DosHtfMixin, DosTrailSlMixin, IndiaMktMixins, DeltaMktMixins, BaseStrategy):
    """
    Multi-sleeve SuperTrend option selling for BTCUSD / ETHUSD:

    - Weekly: when 1D and 4H SuperTrend agree on a **closed 4H bar**, sell near
      4H SuperTrend on the weekly Friday (skip to next week if DTE too low).
    - Monthly: only on a confirmed **1D SuperTrend flip**, sell near 4H
      SuperTrend on the monthly (last Friday) expiry; trail / force-exit on
      **1D** SuperTrend. Gated by ``ENABLE_MONTHLY_TRADES`` (+ per-symbol
      ``enable_monthly``).
    - Daily (0DTE/1DTE): only on a confirmed 1H SuperTrend flip (no mid-regime
      catch-up), and only when 1D and 4H agree with that 1H direction; sell near
      1H SuperTrend (0DTE before 17:25 IST, else 1DTE).
    - Morning (0DTE): every day on the morning-slot closed 1H bar, short in the
      current 1H SuperTrend direction (no 4H/1D filter).

    Knobs (premium floors, trail/force points, lots, DTE, deeper OTM) live in
    ``SYMBOL_CONFIG`` per underlying. Sleeves may be open together per symbol.
    """

    name = "DirectionalOptionSelling"
    underlying_symbols = list(SUPPORTED_UNDERLYINGS)
    timeframe = "60"
    # Subscribe WS/REST for HTF bars used by the entry filter.
    extra_timeframes = list(HTF_TIMEFRAMES)
    required_context = ["option_chain"]
    api = "DELTA"
    expiryType = "Daily"
    order_qty_lots = ORDER_QTY_LOTS
    order_qty_lots_weekly = ORDER_QTY_LOTS_WEEKLY
    order_qty_lots_monthly = ORDER_QTY_LOTS_MONTHLY
    order_qty_lots_daily = ORDER_QTY_LOTS_DAILY
    order_qty_lots_morning = ORDER_QTY_LOTS_MORNING
    supertrend_length = SUPER_TREND_LENGTH
    supertrend_factor = SUPER_TREND_FACTOR
    bracket_leg_tags = ["MAIN_SL"]

    def _symbol_cfg(self, symbol: Any = None) -> Any:
        return symbol_config(symbol if symbol is not None else self._active_symbol)

    def _bind_symbol(self, symbol: Any) -> str:
        """Activate per-symbol runtime for the duration of this eval path."""
        self._active_symbol = normalize_underlying(symbol)
        return self._active_symbol

    def _rt(self, symbol: Any = None) -> _SymbolRuntime:
        sym = normalize_underlying(
            symbol if symbol is not None else self._active_symbol
        )
        rt = self._runtime_by_symbol.get(sym)
        if rt is None:
            rt = _SymbolRuntime()
            self._runtime_by_symbol[sym] = rt
        return rt

    @staticmethod
    def _underlying_from_structure_id(structure_id: str) -> Optional[str]:
        parts = str(structure_id or "").split(":")
        if len(parts) >= 2:
            cand = normalize_underlying(parts[1])
            if cand in SUPPORTED_UNDERLYINGS or cand.endswith("USD"):
                return cand
        return None

    def _resolve_underlying(
        self,
        *,
        candle: Optional[dict] = None,
        meta: Optional[_PositionMeta] = None,
        structure_id: str = "",
        trading_symbol: str = "",
        position: Any = None,
    ) -> str:
        if meta is not None and getattr(meta, "symbol", None):
            return normalize_underlying(meta.symbol)
        if candle is not None and candle.get("symbol"):
            return normalize_underlying(candle.get("symbol"))
        sid = structure_id or str(getattr(position, "structure_id", "") or "")
        from_sid = self._underlying_from_structure_id(sid)
        if from_sid:
            return from_sid
        ts = trading_symbol
        if not ts and position is not None:
            inst = getattr(position, "instrument", None)
            ts = str(getattr(inst, "trading_symbol", "") or "")
        from_opt = underlying_from_option_symbol(ts)
        if from_opt:
            return from_opt
        return normalize_underlying(self._active_symbol)

    # --- Per-symbol runtime shims (tests set these on the strategy instance) ---
    @property
    def _confirmed_direction(self) -> Optional[int]:
        return self._rt().confirmed_direction

    @_confirmed_direction.setter
    def _confirmed_direction(self, value: Optional[int]) -> None:
        self._rt().confirmed_direction = value

    @property
    def _current_supertrend(self) -> Optional[float]:
        return self._rt().current_supertrend

    @_current_supertrend.setter
    def _current_supertrend(self, value: Optional[float]) -> None:
        self._rt().current_supertrend = value

    @property
    def _confirmed_4h_direction(self) -> Optional[int]:
        return self._rt().confirmed_4h_direction

    @_confirmed_4h_direction.setter
    def _confirmed_4h_direction(self, value: Optional[int]) -> None:
        self._rt().confirmed_4h_direction = value

    @property
    def _confirmed_1d_direction(self) -> Optional[int]:
        return self._rt().confirmed_1d_direction

    @_confirmed_1d_direction.setter
    def _confirmed_1d_direction(self, value: Optional[int]) -> None:
        self._rt().confirmed_1d_direction = value

    @property
    def _current_4h_supertrend(self) -> Optional[float]:
        return self._rt().current_4h_supertrend

    @_current_4h_supertrend.setter
    def _current_4h_supertrend(self, value: Optional[float]) -> None:
        self._rt().current_4h_supertrend = value

    @property
    def _current_1d_supertrend(self) -> Optional[float]:
        return self._rt().current_1d_supertrend

    @_current_1d_supertrend.setter
    def _current_1d_supertrend(self, value: Optional[float]) -> None:
        self._rt().current_1d_supertrend = value

    @property
    def _last_seen_4h_bar_open(self) -> Optional[pd.Timestamp]:
        return self._rt().last_seen_4h_bar_open

    @_last_seen_4h_bar_open.setter
    def _last_seen_4h_bar_open(self, value: Optional[pd.Timestamp]) -> None:
        self._rt().last_seen_4h_bar_open = value

    @property
    def _htf_st_cache(self) -> Dict[str, Tuple[int, float, pd.Timestamp]]:
        return self._rt().htf_st_cache

    @_htf_st_cache.setter
    def _htf_st_cache(self, value: Dict[str, Tuple[int, float, pd.Timestamp]]) -> None:
        self._rt().htf_st_cache = value

    @property
    def _pending_transition(self) -> Optional[_PendingTransition]:
        return self._rt().pending_transition

    @_pending_transition.setter
    def _pending_transition(self, value: Optional[_PendingTransition]) -> None:
        self._rt().pending_transition = value

    @property
    def _pending_closed_entry(self) -> Optional[_PendingClosedEntry]:
        return self._rt().pending_closed_entry

    @_pending_closed_entry.setter
    def _pending_closed_entry(self, value: Optional[_PendingClosedEntry]) -> None:
        self._rt().pending_closed_entry = value

    @property
    def _sl_reentry_direction(self) -> Optional[int]:
        return self._rt().sl_reentry_direction

    @_sl_reentry_direction.setter
    def _sl_reentry_direction(self, value: Optional[int]) -> None:
        self._rt().sl_reentry_direction = value

    @property
    def _sl_reentry_after(self) -> Optional[pd.Timestamp]:
        return self._rt().sl_reentry_after

    @_sl_reentry_after.setter
    def _sl_reentry_after(self, value: Optional[pd.Timestamp]) -> None:
        self._rt().sl_reentry_after = value

    @property
    def _sl_reentry_sleeve(self) -> Optional[str]:
        return self._rt().sl_reentry_sleeve

    @_sl_reentry_sleeve.setter
    def _sl_reentry_sleeve(self, value: Optional[str]) -> None:
        self._rt().sl_reentry_sleeve = value

    @property
    def _morning_entry_dates(self) -> set:
        return self._rt().morning_entry_dates

    @_morning_entry_dates.setter
    def _morning_entry_dates(self, value: set) -> None:
        self._rt().morning_entry_dates = value

    @property
    def _rollover_dates(self) -> set:
        return self._rt().rollover_dates

    @_rollover_dates.setter
    def _rollover_dates(self, value: set) -> None:
        self._rt().rollover_dates = value

    @staticmethod
    def _symbol_entries_enabled(symbol: Any = None) -> bool:
        """Master per-underlying gate for new entries / SL re-entries."""
        under = normalize_underlying(symbol)
        cfg = symbol_config(under)
        if not bool(cfg.get("enabled", True)):
            return False
        if under == "BTCUSD":
            return bool(ENABLE_BTCUSD_TRADES)
        if under == "ETHUSD":
            return bool(ENABLE_ETHUSD_TRADES)
        return True

    @staticmethod
    def _sleeve_entries_enabled(sleeve: str, symbol: Any = None) -> bool:
        """Whether new entries / SL re-entries are allowed for this sleeve."""
        if not DirectionalOptionSelling._symbol_entries_enabled(symbol):
            return False
        sleeve_u = str(sleeve or SLEEVE_DAILY).strip().lower()
        cfg = symbol_config(symbol)
        if sleeve_u == SLEEVE_WEEKLY:
            return bool(ENABLE_WEEKLY_TRADES) and bool(cfg.get("enable_weekly", True))
        if sleeve_u == SLEEVE_MONTHLY:
            return bool(ENABLE_MONTHLY_TRADES) and bool(cfg.get("enable_monthly", True))
        if sleeve_u == SLEEVE_MORNING:
            return bool(ENABLE_MORNING_0DTE_TRADES) and bool(
                cfg.get("enable_morning", True)
            )
        return bool(ENABLE_INTRADAY_TRADES) and bool(cfg.get("enable_intraday", True))

    def _entry_qty_lots(self, sleeve: str, symbol: Any = None) -> int:
        """Lots for a new ENTRY: weekly / monthly / daily / morning."""
        sleeve_u = str(sleeve or SLEEVE_DAILY).strip().lower()
        cfg = self._symbol_cfg(symbol)
        inst = getattr(self, "__dict__", {})
        if sleeve_u == SLEEVE_WEEKLY:
            if "order_qty_lots_weekly" in inst:
                return max(1, int(inst["order_qty_lots_weekly"] or 1))
            return max(1, int(cfg.get("order_qty_lots_weekly") or ORDER_QTY_LOTS_WEEKLY))
        if sleeve_u == SLEEVE_MONTHLY:
            if "order_qty_lots_monthly" in inst:
                return max(1, int(inst["order_qty_lots_monthly"] or 1))
            return max(
                1, int(cfg.get("order_qty_lots_monthly") or ORDER_QTY_LOTS_MONTHLY)
            )
        if sleeve_u == SLEEVE_MORNING:
            if "order_qty_lots_morning" in inst:
                return max(1, int(inst["order_qty_lots_morning"] or 1))
            return max(
                1, int(cfg.get("order_qty_lots_morning") or ORDER_QTY_LOTS_MORNING)
            )
        if "order_qty_lots_daily" in inst:
            return max(1, int(inst["order_qty_lots_daily"] or 1))
        return max(1, int(cfg.get("order_qty_lots_daily") or ORDER_QTY_LOTS_DAILY))

    @staticmethod
    def _uses_4h_trail(sleeve: str) -> bool:
        """Weekly trails / force-exits off 4H SuperTrend."""
        return str(sleeve or "").strip().lower() == SLEEVE_WEEKLY

    @staticmethod
    def _uses_1d_trail(sleeve: str) -> bool:
        """Monthly trails / force-exits off 1D SuperTrend."""
        return str(sleeve or "").strip().lower() == SLEEVE_MONTHLY

    def _min_premium_for_sleeve(self, sleeve: str, symbol: Any = None) -> float:
        """Min sell premium: morning uses a lower floor; others use sleeve default."""
        sleeve_u = str(sleeve or SLEEVE_DAILY).strip().lower()
        cfg = self._symbol_cfg(symbol)
        if sleeve_u == SLEEVE_MORNING:
            return float(
                cfg.get("min_premium_usd_morning") or MIN_PREMIUM_USD_MORNING
            )
        return float(cfg.get("min_premium_usd") or MIN_PREMIUM_USD)

    def _weekly_min_dte(self, symbol: Any = None) -> int:
        return int(self._symbol_cfg(symbol).get("weekly_min_dte") or WEEKLY_MIN_DTE)

    def _monthly_min_dte(self, symbol: Any = None) -> int:
        return int(self._symbol_cfg(symbol).get("monthly_min_dte") or MONTHLY_MIN_DTE)

    def _deeper_otm_enabled(self, symbol: Any = None) -> bool:
        if not ENABLE_WEEKLY_DEEPER_OTM:
            return False
        return bool(self._symbol_cfg(symbol).get("enable_weekly_deeper_otm", True))

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._active_symbol: str = "BTCUSD"
        self._runtime_by_symbol: Dict[str, _SymbolRuntime] = {}
        self._latest_candle: Optional[dict] = None
        self._meta_by_structure_id: Dict[str, _PositionMeta] = {}
        self._pending_exit_structure_ids: set[str] = set()
        # structure_id → pending broker trail SL retry after failed modify.
        self._pending_trail_retries: Dict[str, _PendingTrailRetry] = {}
        self._evaluated_bars: set[str] = set()
        logger.info(
            "%s entry switches weekly=%s monthly=%s daily=%s morning=%s "
            "BTCUSD=%s ETHUSD=%s",
            self.name,
            ENABLE_WEEKLY_TRADES,
            ENABLE_MONTHLY_TRADES,
            ENABLE_INTRADAY_TRADES,
            ENABLE_MORNING_0DTE_TRADES,
            ENABLE_BTCUSD_TRADES,
            ENABLE_ETHUSD_TRADES,
        )

    def get_warmup_period(self) -> int:
        return max(50, SUPER_TREND_LENGTH * 4)

    def persisted_indicator_keys(self) -> List[str]:
        return supertrend_column_names()

    def prepare_indicators(self, df: Any) -> Any:
        """Keep backtest and live SuperTrend calculations identical."""
        if df is None or len(df) == 0:
            return df
        required = supertrend_column_names()
        if all(column in df.columns for column in required):
            return df
        return add_supertrend(
            df,
            length=self.supertrend_length,
            factor=self.supertrend_factor,
        )
    def _weekly_expiry_for_entry(self, candle: dict, ctx: Any) -> str:
        """
        Friday weekly expiry code. If DTE <= 2, shift to the next weekly Friday.
        """
        code = str(self.weeklyExpiry(candle, ctx) or "").strip()
        trade_date = self._timestamp_ist(candle["timestamp"]).date()
        exp = self._expiry_date(code)
        if exp is None:
            return code
        while (exp - trade_date).days < self._weekly_min_dte(candle.get("symbol")):
            exp = exp + timedelta(days=7)
            code = exp.strftime("%d%m%y")
        ctx.selected_expiry = code
        logger.info(
            "%s weekly expiry selected code=%s dte=%s",
            self.name,
            code,
            (exp - trade_date).days,
        )
        return code

    def _monthly_expiry_for_entry(self, candle: dict, ctx: Any) -> str:
        """
        Monthly (last Friday) expiry code. If DTE < MONTHLY_MIN_DTE, advance to
        the next month's last Friday.
        """
        import calendar as _cal

        code = str(self.monthlyExpiry(candle, ctx) or "").strip()
        trade_date = self._timestamp_ist(candle["timestamp"]).date()
        exp = self._expiry_date(code)
        if exp is None:
            return code

        def _last_friday(year: int, month: int) -> date:
            last_day = _cal.monthrange(year, month)[1]
            d = date(year, month, last_day)
            offset = (d.weekday() - 4) % 7
            return d - timedelta(days=offset)

        while (exp - trade_date).days < self._monthly_min_dte(candle.get("symbol")):
            if exp.month == 12:
                y, m = exp.year + 1, 1
            else:
                y, m = exp.year, exp.month + 1
            exp = _last_friday(y, m)
            code = exp.strftime("%d%m%y")
        ctx.selected_expiry = code
        logger.info(
            "%s monthly expiry selected code=%s dte=%s",
            self.name,
            code,
            (exp - trade_date).days,
        )
        return code

    @staticmethod
    def _normal_direction(value: Any) -> Optional[int]:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if pd.isna(number) or number == 0:
            return None
        return 1 if number > 0 else -1

    @staticmethod
    def _option_type(direction: int) -> str:
        return "PE" if direction > 0 else "CE"

    @staticmethod
    def _spot_hits_level(
        *,
        direction: int,
        level: float,
        spot: float,
        low: Optional[float] = None,
        high: Optional[float] = None,
    ) -> bool:
        if direction > 0:
            check = float(low if low is not None else spot)
            return check <= float(level)
        check = float(high if high is not None else spot)
        return check >= float(level)

    def _risk_supertrend_for_sleeve(
        self,
        sleeve: str,
        meta: Optional[_PositionMeta] = None,
    ) -> Optional[float]:
        """
        SuperTrend used for ST±300 force-exit / should_exit.

        Weekly → 4H; monthly → 1D; daily / morning → 1H.
        """
        sleeve_u = str(sleeve or SLEEVE_DAILY).strip().lower()
        if self._uses_4h_trail(sleeve_u):
            candidates = (
                self._current_4h_supertrend,
                meta.supertrend if meta is not None else None,
            )
        elif self._uses_1d_trail(sleeve_u):
            candidates = (
                self._current_1d_supertrend,
                meta.supertrend if meta is not None else None,
            )
        else:
            candidates = (
                self._current_supertrend,
                meta.supertrend if meta is not None else None,
            )
        for candidate in candidates:
            try:
                st = float(candidate) if candidate is not None else 0.0
            except (TypeError, ValueError):
                continue
            if st > 0:
                return st
        return None

    @staticmethod
    def _timestamp_ist(value: Any) -> pd.Timestamp:
        """
        Convert to IST. Naive values are treated as UTC (live engine stores UTC-naive).
        Localizing naive as IST made forming 60m bars look closed ~5.5h early.
        """
        ts = pd.Timestamp(value)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts.tz_convert(IST)

    def _closed_bar_time_ist(self, candle: dict) -> pd.Timestamp:
        """Candle timestamps are bucket starts; return confirmed close time for TF."""
        tf = self._candle_timeframe(candle)
        bar_sec = self._tf_bar_seconds(tf)
        if bar_sec <= 0:
            bar_sec = 3600
        bt = candle.get("bucket_ts")
        if bt is not None:
            try:
                open_utc = pd.Timestamp(int(float(bt)), unit="s", tz="UTC")
                return open_utc.tz_convert(IST) + pd.Timedelta(seconds=bar_sec)
            except (TypeError, ValueError, OverflowError):
                pass
        return self._timestamp_ist(candle["timestamp"]) + pd.Timedelta(seconds=bar_sec)

    def _bar_is_fully_closed(self, candle: dict, now: Optional[Any] = None) -> bool:
        """
        True only after the bar close for this candle's timeframe.
        Quote ticks never count as closed bars. A 2s buffer avoids race-at-close.
        """
        if candle.get("quote_tick"):
            return False
        close_ist = self._closed_bar_time_ist(candle)
        if now is None:
            now_ist = pd.Timestamp.now(tz=IST)
        else:
            now_ist = self._timestamp_ist(now)
        return now_ist >= (close_ist + pd.Timedelta(seconds=2))
    @staticmethod
    def _close_confirms_direction(
        direction: int, close: float, supertrend: float
    ) -> bool:
        """
        Closed-bar confirmation for a SuperTrend side.
        Bullish: close above ST; bearish: close below ST.
        Mid-bar risk is handled by broker MAIN_SL — do not reverse on flicker alone.
        """
        c = float(close)
        st = float(supertrend)
        if direction > 0:
            return c > st
        if direction < 0:
            return c < st
        return False

    def _arm_closed_entry(
        self,
        *,
        direction: int,
        reason: str,
        min_dte: int = 0,
        min_strike_distance: float = 0.0,
        armed_after: Optional[Any] = None,
        sleeve: str = SLEEVE_DAILY,
    ) -> None:
        sleeve_u = str(sleeve or SLEEVE_DAILY)
        if not self._sleeve_entries_enabled(sleeve_u, self._active_symbol):
            logger.info(
                "%s deferred entry skipped sleeve=%s symbol=%s disabled reason=%s",
                self.name,
                sleeve_u,
                self._active_symbol,
                reason,
            )
            return
        if armed_after is None:
            after = pd.Timestamp.now(tz=IST)
        else:
            after = self._timestamp_ist(armed_after)
        self._pending_closed_entry = _PendingClosedEntry(
            direction=int(direction),
            reason=str(reason),
            armed_after=after,
            min_dte=int(min_dte),
            min_strike_distance=float(min_strike_distance),
            sleeve=sleeve_u,
        )
        logger.info(
            "%s deferred entry armed direction=%s reason=%s sleeve=%s after=%s "
            "(wait for next closed 60m bar)",
            self.name,
            direction,
            reason,
            sleeve_u,
            after,
        )

    def _consume_pending_closed_entry(
        self, candle: dict, ctx: Any, direction: int
    ) -> Optional[Any]:
        pending = self._pending_closed_entry
        if pending is None:
            return None
        # Only fire on a bar that has actually closed after the EXIT fill.
        if not self._bar_is_fully_closed(candle):
            return None
        if self._closed_bar_time_ist(candle) <= pending.armed_after:
            return None
        sleeve = str(pending.sleeve or SLEEVE_DAILY)
        if self._open_main_positions(ctx, sleeve=sleeve, underlying=self._active_symbol):
            self._pending_closed_entry = None
            return None
        # Prefer the just-closed bar's SuperTrend direction if it still agrees;
        # otherwise follow the closed-bar signal (may have flipped again).
        enter_dir = int(direction) if direction else int(pending.direction)
        intent = self._build_entry(
            candle,
            ctx,
            enter_dir,
            reason=pending.reason,
            min_dte=pending.min_dte
            if pending.min_dte
            else self._min_dte_for_candle(candle),
            min_strike_distance=pending.min_strike_distance,
            sleeve=sleeve,
        )
        # Keep armed when HTF/contract selection blocks — retry next closed 1H bar.
        if intent is not None:
            self._pending_closed_entry = None
        return intent

    def _bar_key(self, candle: dict) -> str:
        symbol = str(candle.get("symbol") or "").strip().upper()
        tf = self._candle_timeframe(candle)
        bt = candle.get("bucket_ts")
        if bt is not None:
            try:
                return f"{symbol}|{tf}|{int(float(bt))}"
            except (TypeError, ValueError):
                pass
        return (
            f"{symbol}|{tf}|{self._timestamp_ist(candle['timestamp']).isoformat()}"
        )
    def should_evaluate(self, candle: dict) -> bool:
        sym = normalize_underlying(candle.get("symbol"))
        if sym not in SUPPORTED_UNDERLYINGS:
            return False
        self._bind_symbol(sym)
        # Do not mark the bar evaluated while it is still forming — wait for close.
        if not self._bar_is_fully_closed(candle):
            return False
        key = self._bar_key(candle)
        if key in self._evaluated_bars:
            return False
        self._evaluated_bars.add(key)
        if len(self._evaluated_bars) > 5000:
            self._evaluated_bars = set(sorted(self._evaluated_bars)[-2500:])
        return True

    def unmark_evaluated(self, candle: dict) -> None:
        """Allow retry when the engine accepted the bar but failed to queue on_candle."""
        try:
            self._evaluated_bars.discard(self._bar_key(candle))
        except Exception:
            pass

    @staticmethod
    def _is_strictly_otm(option_type: str, strike: float, spot: float) -> bool:
        """CE must be above spot; PE must be below spot (ATM/ITM rejected)."""
        ot = str(option_type or "").strip().upper()[:1]
        k = float(strike)
        s = float(spot)
        if ot == "C":
            return k > s
        if ot == "P":
            return k < s
        return False

    @staticmethod
    def _is_outside_supertrend(
        option_type: str, strike: float, supertrend: float
    ) -> bool:
        """
        Select strikes on the outer side of SuperTrend (not through / inside ST).
        CE: strike > SuperTrend; PE: strike < SuperTrend.
        """
        ot = str(option_type or "").strip().upper()[:1]
        k = float(strike)
        st = float(supertrend)
        if ot == "C":
            return k > st
        if ot == "P":
            return k < st
        return False

    @staticmethod
    def _spot_near_position_strike(
        *,
        spot: float,
        strike: float,
        low: Optional[float] = None,
        high: Optional[float] = None,
        band: float = STRIKE_PROXIMITY_EXIT_POINTS,
    ) -> bool:
        """True when spot (or bar range) is within ±band of the open option strike."""
        k = float(strike)
        b = float(band)
        if abs(float(spot) - k) <= b:
            return True
        if low is not None and high is not None:
            return float(low) <= k + b and float(high) >= k - b
        return False

    def _position_strike(self, position: Any, meta: Optional[_PositionMeta]) -> Optional[float]:
        if meta is not None:
            try:
                strike = float(meta.strike)
                if strike > 0:
                    return strike
            except (TypeError, ValueError):
                pass
        inst = getattr(position, "instrument", None)
        try:
            strike = float(getattr(inst, "strike", 0) or 0)
        except (TypeError, ValueError):
            return None
        return strike if strike > 0 else None

    @staticmethod
    def _spot_from_candle(candle: dict) -> Optional[float]:
        try:
            spot = float(candle.get("close"))
        except (TypeError, ValueError):
            return None
        if pd.isna(spot) or spot <= 0:
            return None
        return spot

    def _strategy_meta(self, meta: _PositionMeta) -> dict:
        return pack_strategy_meta(
            self.name,
            {
                "symbol": meta.symbol,
                "direction": meta.direction,
                "option_type": meta.option_type,
                "supertrend": meta.supertrend,
                "strike": meta.strike,
                "expiry": meta.expiry,
                "entry_premium": meta.entry_premium,
                "entry_reason": meta.entry_reason,
                "sleeve": meta.sleeve,
                "sl_mode": meta.sl_mode,
            },
        )

    @staticmethod
    def _sleeve_from_structure_id(structure_id: str) -> Optional[str]:
        """Parse sleeve from sid like DirectionalOptionSelling:BTCUSD:weekly:..."""
        parts = [p.strip().lower() for p in str(structure_id or "").split(":")]
        for part in parts:
            if part in (SLEEVE_WEEKLY, SLEEVE_DAILY, SLEEVE_MORNING, SLEEVE_MONTHLY):
                return part
        return None

    @staticmethod
    def _option_side_from_instrument(inst: Any, trading_symbol: str = "") -> tuple[str, int]:
        """
        Resolve PE/CE and direction from instrument fields or Delta symbol (P-/C-).
        Missing option_type previously defaulted to CE/direction=-1 and caused false
        bearish force-exits on restored puts.
        """
        raw_ot = str(getattr(inst, "option_type", "") or "").strip().upper()
        sym = str(
            trading_symbol
            or getattr(inst, "trading_symbol", "")
            or ""
        ).strip().upper()
        if raw_ot.startswith("P") or sym.startswith("P-"):
            return "PE", 1
        if raw_ot.startswith("C") or sym.startswith("C-"):
            return "CE", -1
        # Last resort: strike/expiry-only restore — treat as unknown put-safe no-op
        # only if symbol encoding is absent; prefer PE when structure_id says PE.
        return "CE", -1

    def _normalize_sleeve(self, sleeve: Any, structure_id: str = "") -> str:
        sleeve_u = str(sleeve or "").strip().lower()
        if sleeve_u not in (SLEEVE_WEEKLY, SLEEVE_DAILY, SLEEVE_MORNING, SLEEVE_MONTHLY):
            sleeve_u = ""
        sid_sleeve = self._sleeve_from_structure_id(structure_id)
        # Structure id is authoritative when present (survives meta loss on restart).
        if sid_sleeve:
            return sid_sleeve
        return sleeve_u or SLEEVE_DAILY

    def _restore_meta(self, structure_id: str, raw: Any) -> bool:
        if structure_id in self._meta_by_structure_id:
            return True
        canonical = unpack_strategy_meta(raw, self.name)
        if canonical is not None:
            raw = canonical
        if isinstance(raw, dict) and META_KEY in raw:
            raw = raw.get(META_KEY)
        if not isinstance(raw, dict):
            return False
        try:
            sleeve = self._normalize_sleeve(raw.get("sleeve"), structure_id)
            raw_mode = str(raw.get("sl_mode") or "").strip().lower()
            # Legacy restores (no sl_mode) were always on index/ST trail.
            if raw_mode not in (SL_MODE_PREMIUM, SL_MODE_INDEX):
                raw_mode = SL_MODE_INDEX
            meta = _PositionMeta(
                symbol=str(raw["symbol"]).upper(),
                direction=int(raw["direction"]),
                option_type=str(raw["option_type"]).upper(),
                supertrend=float(raw["supertrend"]),
                strike=float(raw["strike"]),
                expiry=str(raw["expiry"]),
                entry_premium=float(raw["entry_premium"]),
                entry_reason=str(raw.get("entry_reason") or "signal"),
                sleeve=sleeve,
                sl_mode=raw_mode,
            )
        except (KeyError, TypeError, ValueError):
            return False
        self._meta_by_structure_id[structure_id] = meta
        return True

    def _fallback_meta_from_position(self, position: Any) -> Optional[_PositionMeta]:
        """Build meta when CSV/intent strategy_meta is missing after restart."""
        sid = str(getattr(position, "structure_id", "") or "")
        inst = getattr(position, "instrument", None)
        trading_symbol = str(getattr(inst, "trading_symbol", "") or "")
        option_type, direction = self._option_side_from_instrument(
            inst, trading_symbol
        )
        # Prefer PE token embedded in structure_id when instrument fields are empty.
        sid_u = sid.upper()
        if ":PE:" in sid_u or sid_u.endswith(":PE"):
            option_type, direction = "PE", 1
        elif ":CE:" in sid_u or sid_u.endswith(":CE"):
            option_type, direction = "CE", -1
        sleeve = self._normalize_sleeve(None, sid)
        try:
            strike = float(getattr(inst, "strike", 0) or 0)
            expiry = str(getattr(inst, "expiry", "") or "")
            if (strike <= 0 or not expiry) and trading_symbol:
                parts = trading_symbol.split("-")
                if len(parts) >= 4:
                    if strike <= 0:
                        strike = float(parts[2])
                    if not expiry:
                        expiry = str(parts[3])
            # Weekly → 4H ST; monthly → 1D ST; daily / morning → 1H ST.
            if self._uses_4h_trail(sleeve):
                st = float(
                    self._current_4h_supertrend
                    or self._current_supertrend
                    or 0
                )
            elif self._uses_1d_trail(sleeve):
                st = float(
                    self._current_1d_supertrend
                    or self._current_supertrend
                    or 0
                )
            else:
                st = float(self._current_supertrend or 0)
            return _PositionMeta(
                symbol=self._resolve_underlying(
                    structure_id=sid, trading_symbol=trading_symbol, position=position
                ),
                direction=direction,
                option_type=option_type,
                supertrend=st,
                strike=strike,
                expiry=expiry,
                entry_premium=float(getattr(position, "avg_price", 0) or 0),
                entry_reason="restored",
                sleeve=sleeve,
                # Unknown history → assume already on index trail (pre-premium-SL).
                sl_mode=SL_MODE_INDEX,
            )
        except (TypeError, ValueError):
            return None

    def _ensure_meta(self, position: Any, ctx: Any) -> Optional[_PositionMeta]:
        sid = str(getattr(position, "structure_id", "") or "")
        meta = self._meta_by_structure_id.get(sid)
        if meta is not None:
            # Re-assert sleeve from structure_id if it was mis-tagged previously.
            sid_sleeve = self._sleeve_from_structure_id(sid)
            if sid_sleeve and meta.sleeve != sid_sleeve:
                meta = replace(meta, sleeve=sid_sleeve)
                self._meta_by_structure_id[sid] = meta
            return meta
        intent_store = getattr(ctx, "intent_store", None)
        intent_id = getattr(position, "intent_id", None)
        if intent_store is not None and intent_id and callable(getattr(intent_store, "get", None)):
            record = intent_store.get(intent_id) or {}
            payload = record.get("payload") or {}
            strategy_meta = payload.get("strategy_meta") or payload.get("metadata_extras") or {}
            if self._restore_meta(sid, strategy_meta):
                return self._meta_by_structure_id.get(sid)
        # Position-manager metadata (survives multi-strategy CSV merge).
        if ctx is not None:
            pm = getattr(ctx, "position_store", None)
            inst = getattr(position, "instrument", None)
            trading_symbol = str(getattr(inst, "trading_symbol", "") or "")
            if (
                trading_symbol
                and pm is not None
                and callable(getattr(pm, "get_position_metadata", None))
            ):
                stored = pm.get_position_metadata(trading_symbol) or {}
                raw = stored.get("strategy_meta") if isinstance(stored, dict) else None
                if self._restore_meta(sid, raw):
                    return self._meta_by_structure_id.get(sid)
        fallback = self._fallback_meta_from_position(position)
        if fallback is None:
            return None
        if sid:
            self._meta_by_structure_id[sid] = fallback
        return fallback

    def restore_state_on_startup(
        self,
        position_manager: Any,
        intent_store: Any = None,
        ctx: Any = None,
    ) -> None:
        """Restore open MAIN metadata so quote risk works before the next hourly bar."""
        if position_manager is None:
            return
        for position in list(getattr(position_manager, "positions", {}).values()):
            if int(getattr(position, "net_qty", 0) or 0) == 0:
                continue
            if getattr(position, "strategy", None) != self.name:
                continue
            if str(getattr(position, "tag", "") or "").upper() != "MAIN":
                continue
            sid = str(getattr(position, "structure_id", "") or "")
            instrument = getattr(position, "instrument", None)
            trading_symbol = str(
                getattr(instrument, "trading_symbol", "") or ""
            )
            stored = (
                position_manager.get_position_metadata(trading_symbol)
                if trading_symbol
                and callable(getattr(position_manager, "get_position_metadata", None))
                else None
            ) or {}
            raw = stored.get("strategy_meta") if isinstance(stored, dict) else None
            if raw is None and intent_store is not None:
                intent_id = getattr(position, "intent_id", None)
                record = intent_store.get(intent_id) if intent_id else None
                raw = (record or {}).get("payload", {}).get("strategy_meta")
            restored = bool(sid and self._restore_meta(sid, raw))
            if not restored:
                # CSV/intent meta missing (common when engine restores from another
                # strategy's open-positions file) — infer from structure_id + symbol.
                fallback = self._fallback_meta_from_position(position)
                if fallback is not None and sid:
                    self._meta_by_structure_id[sid] = fallback
                    restored = True
                    logger.info(
                        "%s restored MAIN meta from structure_id/symbol "
                        "sid=%s sleeve=%s direction=%s symbol=%s",
                        self.name,
                        sid,
                        fallback.sleeve,
                        fallback.direction,
                        trading_symbol,
                    )
            if restored:
                # Meta restored for quote risk / trail; 1H signal state is hydrated
                # from indicator history below (not from sleeve entry direction).
                pass
        # Seed 1H / 4H signal state per underlying from indicator history.
        for under in list(self.underlying_symbols):
            self._bind_symbol(under)
            seed = {"symbol": under, "timestamp": pd.Timestamp.now(tz="UTC")}
            live_1h = self._hydrate_1h_from_history({**seed, "timeframe": "60"})
            if live_1h is not None:
                logger.info(
                    "%s hydrated live 1H SuperTrend=%.2f direction=%s symbol=%s "
                    "after startup restore",
                    self.name,
                    live_1h,
                    self._confirmed_direction,
                    under,
                )
            else:
                logger.warning(
                    "%s could not hydrate live 1H SuperTrend for %s after startup "
                    "restore (daily flip detection deferred until first closed 1H bar)",
                    self.name,
                    under,
                )
            live_4h = self._hydrate_4h_from_history({**seed, "timeframe": "4h"})
            if live_4h is not None:
                logger.info(
                    "%s hydrated live 4H SuperTrend=%.2f symbol=%s after startup restore",
                    self.name,
                    live_4h,
                    under,
                )
            else:
                logger.warning(
                    "%s could not hydrate live 4H SuperTrend for %s after startup "
                    "restore (weekly trail catch-up deferred until next closed bar)",
                    self.name,
                    under,
                )
            if ctx is not None and live_4h is not None:
                try:
                    candle = {
                        "symbol": under,
                        "timestamp": pd.Timestamp.now(tz="UTC"),
                        "timeframe": "4h",
                        "close": float(live_4h),
                        "supertrend_4h": float(live_4h),
                    }
                    self._trail_open_sleeves(
                        ctx,
                        candle,
                        one_h_st=self._current_supertrend,
                        previous_st=self._current_supertrend,
                        source="startup_catchup",
                    )
                except Exception as exc:
                    logger.warning(
                        "%s startup trail catch-up failed symbol=%s: %s",
                        self.name,
                        under,
                        exc,
                    )

    def _open_main_positions(
        self,
        ctx: Any,
        *,
        sleeve: Optional[str] = None,
        underlying: Optional[str] = None,
    ) -> List[Any]:
        want_under = (
            normalize_underlying(underlying) if underlying is not None else None
        )
        out: List[Any] = []
        for position in (
            ctx.position_store.get_open_positions(strategy=self.name) or []
        ):
            if getattr(position, "tag", None) != "MAIN":
                continue
            if int(getattr(position, "net_qty", 0) or 0) == 0:
                continue
            meta = self._ensure_meta(position, ctx)
            if want_under is not None:
                pos_under = self._resolve_underlying(
                    meta=meta, position=position
                )
                if pos_under != want_under:
                    continue
            if sleeve is not None:
                pos_sleeve = (
                    str(meta.sleeve) if meta is not None else SLEEVE_DAILY
                )
                if pos_sleeve != str(sleeve):
                    continue
            out.append(position)
        return out

    def _main_trading_symbol(self, position: Any) -> str:
        inst = getattr(position, "instrument", None)
        return str(getattr(inst, "trading_symbol", "") or "").strip().upper()

    def _open_main_trading_symbols(self, ctx: Any) -> set[str]:
        """All open DOS MAIN symbols (any sleeve) — used to block duplicate entries."""
        out: set[str] = set()
        for position in self._open_main_positions(ctx):
            sym = self._main_trading_symbol(position)
            if sym:
                out.add(sym)
        return out

    def _open_main_has_expiry(
        self, ctx: Any, expiry: str, *, underlying: Optional[str] = None
    ) -> bool:
        want = str(expiry or "").strip()
        if not want:
            return False
        for position in self._open_main_positions(ctx, underlying=underlying):
            meta = self._ensure_meta(position, ctx)
            if meta is not None and str(meta.expiry) == want:
                return True
            inst = getattr(position, "instrument", None)
            if str(getattr(inst, "expiry", "") or "") == want:
                return True
            sym = self._main_trading_symbol(position)
            if sym.endswith(f"-{want}"):
                return True
        return False

    @staticmethod
    def _expiry_date(value: Any) -> Optional[date]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        raw = str(value).strip()
        for fmt in ("%d%m%y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _product_expiry(product: dict) -> str:
        symbol = str(product.get("symbol") or "").upper()
        parts = symbol.split("-")
        return str(parts[-1]).strip() if len(parts) >= 4 else ""

    @staticmethod
    def _product_strike(product: dict) -> Optional[float]:
        value = product.get("strike_price")
        if value is None:
            parts = str(product.get("symbol") or "").split("-")
            value = parts[2] if len(parts) >= 4 else None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _sell_premium(ticker: Any) -> Optional[tuple[float, float, float]]:
        if not isinstance(ticker, dict):
            return None
        quotes = ticker.get("quotes") or {}
        try:
            bid = float(quotes.get("best_bid") or 0)
        except (TypeError, ValueError):
            bid = 0.0
        try:
            ask = float(quotes.get("best_ask") or 0)
        except (TypeError, ValueError):
            ask = 0.0
        premium = bid
        if premium <= 0:
            for key in ("mark_price", "close", "price"):
                try:
                    premium = float(ticker.get(key) or 0)
                except (TypeError, ValueError):
                    premium = 0.0
                if premium > 0:
                    break
        return (premium, bid, ask) if premium > 0 else None

    @staticmethod
    def _ordered_expiries(
        expiries: List[str],
        trade_date: date,
        min_dte: int,
        target_expiry: Optional[str] = None,
        *,
        allow_next_expiry_fallback: bool = True,
    ) -> List[str]:
        dated = []
        for code in set(expiries):
            parsed = DirectionalOptionSelling._expiry_date(code)
            if parsed is not None and parsed >= trade_date:
                dated.append((parsed, code))
        dated.sort()
        if target_expiry:
            target = str(target_expiry).strip()
            target_d = DirectionalOptionSelling._expiry_date(target)
            ordered: List[str] = []
            if target_d is not None:
                for expiry, code in dated:
                    if expiry == target_d or code == target:
                        ordered.append(code)
                        break
                # Weekly may roll to the next listed Friday when the exact
                # code is missing. Morning / strict 0DTE must NOT fall through
                # to a weekly — empty list → skip the order.
                if not ordered and allow_next_expiry_fallback:
                    for expiry, code in dated:
                        if expiry > target_d:
                            ordered.append(code)
                            break
            elif target:
                ordered.append(target)
            return ordered[:2]
        if min_dte > 0:
            return [
                code
                for expiry, code in dated
                if (expiry - trade_date).days >= int(min_dte)
            ][:1] or [code for expiry, code in dated if expiry > trade_date][:1]
        today = [code for expiry, code in dated if expiry == trade_date]
        future = [code for expiry, code in dated if expiry > trade_date]
        return (today[:1] + future[:1])[:2]

    def _select_live_contract(
        self,
        candle: dict,
        ctx: Any,
        option_type: str,
        supertrend: float,
        *,
        min_dte: int,
        min_strike_distance: float,
        target_expiry: Optional[str] = None,
        min_premium: Optional[float] = None,
        otm_skip: int = 0,
        min_strike_spot_distance: float = 0.0,
        allow_next_expiry_fallback: bool = True,
    ) -> Optional[tuple[float, float, pd.Series, str]]:
        source = _delta_source_from_ctx(ctx)
        if source is None:
            return None
        under = self._resolve_underlying(candle=candle)
        root = option_root_for(under)
        cfg = self._symbol_cfg(under)
        floor = (
            float(min_premium)
            if min_premium is not None
            else float(cfg.get("min_premium_usd") or MIN_PREMIUM_USD)
        )
        skip_n = max(0, int(otm_skip or 0))
        spot_floor = max(0.0, float(min_strike_spot_distance or 0))
        opt_letter = option_type[0].upper()
        products = source.get_products(use_cache=True) or []
        prefix = f"{opt_letter}-{root}-"
        matching = [
            product
            for product in products
            if str(product.get("symbol") or "").upper().startswith(prefix)
        ]
        trade_date = self._timestamp_ist(candle["timestamp"]).date()
        spot = self._spot_from_candle(candle)
        if spot is None:
            return None
        expiry_order = self._ordered_expiries(
            [self._product_expiry(product) for product in matching],
            trade_date,
            min_dte,
            target_expiry=target_expiry,
            allow_next_expiry_fallback=allow_next_expiry_fallback,
        )
        # Strict target (morning 0DTE): if missing from cached products, refresh
        # once from the API before giving up — never substitute a weekly.
        if (
            target_expiry
            and not allow_next_expiry_fallback
            and str(target_expiry).strip() not in set(expiry_order)
        ):
            logger.warning(
                "%s target expiry %s missing from product cache; "
                "refreshing Delta products once (strict, no weekly fallback)",
                self.name,
                target_expiry,
            )
            products = source.get_products(use_cache=False) or []
            matching = [
                product
                for product in products
                if str(product.get("symbol") or "").upper().startswith(prefix)
            ]
            expiry_order = self._ordered_expiries(
                [self._product_expiry(product) for product in matching],
                trade_date,
                min_dte,
                target_expiry=target_expiry,
                allow_next_expiry_fallback=False,
            )
            if str(target_expiry).strip() not in set(expiry_order):
                logger.warning(
                    "%s skip ENTRY: strict target expiry %s still not listed "
                    "after product refresh",
                    self.name,
                    target_expiry,
                )
                return None
            # Keep instrument CSV in sync when the store supports refresh.
            store = getattr(ctx, "instrument_store", None)
            refresh_fn = getattr(store, "refresh_products", None)
            if callable(refresh_fn):
                try:
                    refresh_fn()
                except Exception:
                    logger.exception(
                        "%s instrument_store.refresh_products failed", self.name
                    )
        for expiry in expiry_order:
            candidates = []
            for product in matching:
                if self._product_expiry(product) != expiry:
                    continue
                strike = self._product_strike(product)
                symbol = str(product.get("symbol") or "").upper()
                if strike is None or not symbol:
                    continue
                if not self._is_strictly_otm(option_type, strike, spot):
                    continue
                if not self._is_outside_supertrend(option_type, strike, supertrend):
                    continue
                if abs(float(strike) - float(spot)) < spot_floor:
                    continue
                distance = abs(strike - supertrend)
                if distance >= float(min_strike_distance):
                    candidates.append((distance, strike, symbol, product))
            candidates.sort(key=lambda item: (item[0], item[1]))
            # Skip nearest N eligible OTMs (0=OTM1, 1=start at OTM2, ...).
            if skip_n:
                candidates = candidates[skip_n:]
            try:
                tickers = (
                    source.get_option_tickers_for_expiry(root, expiry, opt_letter)
                    or {}
                )
            except Exception:
                tickers = {}
            for _distance, strike, symbol, _product in candidates:
                ticker = tickers.get(symbol)
                if ticker is None:
                    try:
                        ticker = source.get_ticker(symbol)
                    except Exception:
                        ticker = None
                quote = self._sell_premium(ticker)
                if quote is None or quote[0] < floor:
                    continue
                premium, bid, ask = quote
                row = pd.Series(
                    {
                        "symbol": symbol,
                        "strike": strike,
                        "price": premium,
                        "close": premium,
                        "best_bid": bid,
                        "best_ask": ask,
                        "expiry": expiry,
                    }
                )
                return strike, premium, row, expiry
        return None

    def _select_backtest_contract(
        self,
        candle: dict,
        ctx: Any,
        option_type: str,
        supertrend: float,
        *,
        min_dte: int,
        min_strike_distance: float,
        target_expiry: Optional[str] = None,
        min_premium: Optional[float] = None,
        otm_skip: int = 0,
        min_strike_spot_distance: float = 0.0,
        allow_next_expiry_fallback: bool = True,
    ) -> Optional[tuple[float, float, pd.Series, str]]:
        df = self.load_delta_data_for_candle(candle, ctx)
        if df is None or df.empty:
            return None
        floor = (
            float(min_premium)
            if min_premium is not None
            else float(
                self._symbol_cfg(candle.get("symbol")).get("min_premium_usd")
                or MIN_PREMIUM_USD
            )
        )
        skip_n = max(0, int(otm_skip or 0))
        spot_floor = max(0.0, float(min_strike_spot_distance or 0))
        work = df.copy()
        work.columns = [
            "symbol", "price", "qty", "timestamp", "side", "opt_type", "strike", "expiry"
        ]
        work["timestamp"] = pd.to_datetime(work["timestamp"])
        parts = work["symbol"].astype(str).str.split("-", expand=True)
        work["opt_type"] = parts[0].str.upper()
        work["strike"] = pd.to_numeric(parts[2], errors="coerce")
        work["expiry"] = parts[3].astype(str)
        candle_time = pd.Timestamp(candle["timestamp"]).tz_localize(None)
        work = work[
            (work["opt_type"] == option_type[0].upper())
            & (work["timestamp"] >= candle_time - pd.Timedelta(minutes=5))
            & (work["timestamp"] <= candle_time + pd.Timedelta(minutes=5))
        ]
        if work.empty:
            return None
        spot = self._spot_from_candle(candle)
        if spot is None:
            return None
        expiry_order = self._ordered_expiries(
            work["expiry"].dropna().astype(str).tolist(),
            self._timestamp_ist(candle["timestamp"]).date(),
            min_dte,
            target_expiry=target_expiry,
            allow_next_expiry_fallback=allow_next_expiry_fallback,
        )
        for expiry in expiry_order:
            latest = (
                work[work["expiry"] == expiry]
                .sort_values("timestamp")
                .groupby("strike", as_index=False)
                .last()
            )
            latest["price"] = pd.to_numeric(latest["price"], errors="coerce")
            latest = latest[(latest["price"] >= floor) & (latest["qty"] > 0)]
            if latest.empty:
                continue
            latest = latest.copy()
            latest = latest[
                latest["strike"].apply(
                    lambda strike: self._is_strictly_otm(option_type, strike, spot)
                    and self._is_outside_supertrend(option_type, strike, supertrend)
                    and abs(float(strike) - float(spot)) >= spot_floor
                )
            ]
            if latest.empty:
                continue
            latest["distance"] = (latest["strike"] - supertrend).abs()
            latest = latest[latest["distance"] >= float(min_strike_distance)]
            if latest.empty:
                continue
            latest = latest.sort_values(["distance", "strike"])
            if skip_n:
                latest = latest.iloc[skip_n:]
            if latest.empty:
                continue
            row = latest.iloc[0]
            return float(row["strike"]), float(row["price"]), row, expiry
        return None

    def _select_contract(
        self,
        candle: dict,
        ctx: Any,
        direction: int,
        supertrend: float,
        *,
        min_dte: int = 0,
        min_strike_distance: float = 0.0,
        target_expiry: Optional[str] = None,
        min_premium: Optional[float] = None,
        otm_skip: int = 0,
        min_strike_spot_distance: float = 0.0,
        allow_next_expiry_fallback: bool = True,
    ) -> Optional[tuple[float, float, pd.Series, str]]:
        option_type = self._option_type(direction)
        if RUN_MODE == RunMode.BACKTEST:
            return self._select_backtest_contract(
                candle,
                ctx,
                option_type,
                supertrend,
                min_dte=min_dte,
                min_strike_distance=min_strike_distance,
                target_expiry=target_expiry,
                min_premium=min_premium,
                otm_skip=otm_skip,
                min_strike_spot_distance=min_strike_spot_distance,
                allow_next_expiry_fallback=allow_next_expiry_fallback,
            )
        return self._select_live_contract(
            candle,
            ctx,
            option_type,
            supertrend,
            min_dte=min_dte,
            min_strike_distance=min_strike_distance,
            target_expiry=target_expiry,
            min_premium=min_premium,
            otm_skip=otm_skip,
            min_strike_spot_distance=min_strike_spot_distance,
            allow_next_expiry_fallback=allow_next_expiry_fallback,
        )

    def _notify_premium_entry_skip(
        self,
        ctx: Any,
        *,
        sleeve: str,
        option_type: str,
        min_premium: float,
        supertrend: float,
        spot_gate: float,
        symbol: str,
        reason: str,
        direction: int,
    ) -> None:
        """Telegram when ENTRY is skipped because no contract clears the premium floor."""
        msg = (
            f"⚠️ {self.name} ENTRY skipped (premium/strike gate)\n"
            f"sleeve={sleeve} symbol={symbol} reason={reason}\n"
            f"opt={option_type} dir={direction} min_premium=${min_premium:.2f}\n"
            f"ST={supertrend:.2f} min_|strike-spot|={spot_gate:.0f}\n"
            f"No qualifying contract — order not placed."
        )
        eng = getattr(ctx, "engine_logger", None) if ctx is not None else None
        notify = getattr(eng, "notify_operator", None) if eng is not None else None
        if not callable(notify):
            return
        try:
            notify(msg)
        except Exception:
            logger.debug(
                "%s telegram premium-skip notify failed", self.name, exc_info=True
            )

    def _build_entry(
        self,
        candle: dict,
        ctx: Any,
        direction: int,
        *,
        reason: str,
        min_dte: int = 0,
        min_strike_distance: float = 0.0,
        sleeve: str = SLEEVE_DAILY,
    ) -> Optional[Any]:
        under = self._resolve_underlying(candle=candle)
        self._bind_symbol(under)
        cfg = self._symbol_cfg(under)
        sleeve_u = str(sleeve or SLEEVE_DAILY).strip().lower()
        if sleeve_u not in (
            SLEEVE_WEEKLY,
            SLEEVE_DAILY,
            SLEEVE_MORNING,
            SLEEVE_MONTHLY,
        ):
            sleeve_u = SLEEVE_DAILY
        if not self._sleeve_entries_enabled(sleeve_u, under):
            logger.info(
                "%s skip %s ENTRY: sleeve/symbol disabled symbol=%s "
                "(weekly=%s monthly=%s daily=%s morning=%s BTC=%s ETH=%s)",
                self.name,
                sleeve_u,
                under,
                ENABLE_WEEKLY_TRADES,
                ENABLE_MONTHLY_TRADES,
                ENABLE_INTRADAY_TRADES,
                ENABLE_MORNING_0DTE_TRADES,
                ENABLE_BTCUSD_TRADES,
                ENABLE_ETHUSD_TRADES,
            )
            return None
        if self._open_main_positions(ctx, sleeve=sleeve_u, underlying=under):
            return None
        if sleeve_u == SLEEVE_WEEKLY:
            if not self._weekly_htf_aligned(int(direction), ctx, candle):
                return None
            # Prefer 4H SuperTrend for weekly strike / trail reference.
            supertrend = float(
                candle.get("supertrend_4h")
                or self._current_4h_supertrend
                or self._current_supertrend
                or candle.get("supertrend")
                or 0
            )
        elif sleeve_u == SLEEVE_MONTHLY:
            # 1D flip entry: no continuous 1D+4H align gate; strike off 4H ST.
            supertrend = float(
                candle.get("supertrend_4h")
                or self._current_4h_supertrend
                or self._current_supertrend
                or candle.get("supertrend")
                or 0
            )
        elif sleeve_u == SLEEVE_MORNING:
            # Clock-slot 0DTE: 1H SuperTrend only — no 4H/1D filter.
            supertrend = float(
                self._current_supertrend
                or candle.get("supertrend")
                or 0
            )
        else:
            # Daily: 1H signal TF; require 1D+4H same color as 1H direction.
            if not self._daily_htf_aligned(int(direction), ctx, candle):
                return None
            supertrend = float(
                self._current_supertrend
                or candle.get("supertrend")
                or 0
            )
        if supertrend <= 0:
            return None
        target_expiry = None
        entry_min_dte = int(min_dte)
        if sleeve_u == SLEEVE_WEEKLY:
            target_expiry = self._weekly_expiry_for_entry(candle, ctx)
            entry_min_dte = self._weekly_min_dte(under)
            # Even if sleeve meta was lost and the open leg looks "daily", never
            # stack another weekly MAIN on the same Friday expiry for this under.
            if target_expiry and self._open_main_has_expiry(
                ctx, target_expiry, underlying=under
            ):
                logger.info(
                    "%s skip weekly ENTRY: already open on expiry=%s symbol=%s",
                    self.name,
                    target_expiry,
                    under,
                )
                return None
        elif sleeve_u == SLEEVE_MONTHLY:
            target_expiry = self._monthly_expiry_for_entry(candle, ctx)
            entry_min_dte = self._monthly_min_dte(under)
            if target_expiry and self._open_main_has_expiry(
                ctx, target_expiry, underlying=under
            ):
                logger.info(
                    "%s skip monthly ENTRY: already open on expiry=%s symbol=%s",
                    self.name,
                    target_expiry,
                    under,
                )
                return None
        elif sleeve_u == SLEEVE_MORNING:
            # Prefer today's daily expiry; never roll morning slot to next day /
            # weekly — if 0DTE is missing after refresh, skip the order.
            target_expiry = self._0dte_expiry_code(candle)
            entry_min_dte = 0
            if self._open_main_has_expiry(ctx, target_expiry, underlying=under):
                logger.info(
                    "%s skip morning ENTRY: already open on 0DTE expiry=%s symbol=%s",
                    self.name,
                    target_expiry,
                    under,
                )
                return None
            # Morning: enforce min |strike − SuperTrend| (BTC default 100).
            morning_st_floor = float(
                cfg.get("morning_min_strike_distance") or MORNING_MIN_STRIKE_DISTANCE
            )
            min_strike_distance = max(
                float(min_strike_distance or 0.0), morning_st_floor
            )
        # Morning / daily: keep strike far enough from spot to avoid immediate
        # proximity exits. Weekly / monthly use ST distance / deeper OTM.
        spot_gate = (
            float(cfg.get("min_strike_spot_distance") or MIN_STRIKE_SPOT_DISTANCE)
            if sleeve_u in (SLEEVE_MORNING, SLEEVE_DAILY)
            else 0.0
        )
        selected = self._select_contract(
            candle,
            ctx,
            direction,
            supertrend,
            min_dte=entry_min_dte,
            min_strike_distance=min_strike_distance,
            target_expiry=target_expiry,
            min_premium=self._min_premium_for_sleeve(sleeve_u, under),
            otm_skip=(
                1
                if sleeve_u in (SLEEVE_WEEKLY, SLEEVE_MONTHLY)
                and self._deeper_otm_enabled(under)
                else 0
            ),
            min_strike_spot_distance=spot_gate,
            # Morning 0DTE must not silently land on the next weekly.
            allow_next_expiry_fallback=sleeve_u != SLEEVE_MORNING,
        )
        if selected is None:
            opt = self._option_type(direction)
            floor = self._min_premium_for_sleeve(sleeve_u, under)
            logger.warning(
                "%s: no %s %s contract premium >= %.2f near SuperTrend %.2f"
                " (min |strike-spot|=%.0f) symbol=%s",
                self.name,
                sleeve_u,
                opt,
                floor,
                supertrend,
                spot_gate,
                under,
            )
            self._notify_premium_entry_skip(
                ctx,
                sleeve=sleeve_u,
                option_type=opt,
                min_premium=floor,
                supertrend=supertrend,
                spot_gate=spot_gate,
                symbol=under,
                reason=reason,
                direction=int(direction),
            )
            return None
        strike, premium, row, expiry = selected
        option_type = self._option_type(direction)
        trading_symbol = self.delta_option_trading_symbol(
            row, strike, option_type, expiry
        )
        open_syms = self._open_main_trading_symbols(ctx)
        if str(trading_symbol or "").strip().upper() in open_syms:
            logger.info(
                "%s skip %s ENTRY: already open on %s",
                self.name,
                sleeve_u,
                trading_symbol,
            )
            return None
        ctx.selected_expiry = expiry
        inst = ctx.instrument_store.intent_creation_details(
            trading_symbol, ctx.exchange, expiry, option_type, strike
        )
        if inst is None:
            return None
        structure_id = (
            f"{self.name}:{under}:{sleeve_u}:"
            f"{self._timestamp_ist(candle['timestamp']).date()}:"
            f"{option_type}:{uuid.uuid4().hex[:8]}"
        )
        meta = _PositionMeta(
            symbol=under,
            direction=direction,
            option_type=option_type,
            supertrend=supertrend,
            strike=strike,
            expiry=expiry,
            entry_premium=premium,
            entry_reason=reason,
            sleeve=sleeve_u,
            sl_mode=SL_MODE_PREMIUM,
        )
        intent = self.map_instrument_to_intent(
            inst=inst,
            strike_row=row,
            strategy=self.name,
            side="SELL",
            structure_id=structure_id,
            candle_ts=candle["timestamp"],
            tag="MAIN",
            symbol=under,
            action="ENTRY",
            metadata_extras=self._strategy_meta(meta),
        )
        qty_lots = self._entry_qty_lots(sleeve_u, under)
        intent = replace(intent, qty=qty_lots)
        self._meta_by_structure_id[structure_id] = meta
        logger.info(
            "%s ENTRY signaled reason=%s sleeve=%s symbol=%s direction=%s opt=%s "
            "strike=%.2f expiry=%s premium=%.2f qty=%s ST=%.2f ST_4h=%s ST_1d=%s "
            "sid=%s",
            self.name,
            reason,
            sleeve_u,
            under,
            direction,
            option_type,
            strike,
            expiry,
            premium,
            qty_lots,
            supertrend,
            candle.get("supertrend_4h"),
            candle.get("supertrend_1d"),
            structure_id,
        )
        return intent

    def _arm_sl_reentry(
        self,
        direction: Optional[int],
        exit_ts: Any,
        *,
        sleeve: str = SLEEVE_DAILY,
        symbol: Any = None,
    ) -> None:
        """
        After SL, re-enter on the close of the 1hr candle that contained the SL.

        Example: SL at 11:01 inside the 10:30→11:30 bar → decide at 11:30 close
        (same SuperTrend → same direction; flipped → opposite).
        """
        if direction is None:
            return
        if symbol is not None:
            self._bind_symbol(symbol)
        sleeve_u = str(sleeve or SLEEVE_DAILY)
        if not self._sleeve_entries_enabled(sleeve_u, self._active_symbol):
            logger.info(
                "%s SL reentry skipped sleeve=%s symbol=%s disabled",
                self.name,
                sleeve_u,
                self._active_symbol,
            )
            return
        self._sl_reentry_direction = int(direction)
        self._sl_reentry_after = self._timestamp_ist(exit_ts)
        self._sl_reentry_sleeve = sleeve_u
        logger.info(
            "%s SL reentry armed direction=%s sleeve=%s symbol=%s after=%s "
            "(reenter on that bar's close)",
            self.name,
            self._sl_reentry_direction,
            self._sl_reentry_sleeve,
            self._active_symbol,
            self._sl_reentry_after,
        )

    def _clear_sl_reentry(self) -> None:
        self._sl_reentry_direction = None
        self._sl_reentry_after = None
        self._sl_reentry_sleeve = None

    def _sl_reentry_ready(self, candle: dict) -> bool:
        """True once this candle's close time is after the SL fill time."""
        if self._sl_reentry_direction is None or self._sl_reentry_after is None:
            return False
        if not self._bar_is_fully_closed(candle):
            return False
        # SL at 11:01 on the 10:30 bar → closed_bar_time 11:30 > 11:01 → ready.
        return self._closed_bar_time_ist(candle) > self._sl_reentry_after

    def _min_dte_for_candle(self, candle: dict) -> int:
        return 1 if self._closed_bar_time_ist(candle).time() >= ROLLOVER_TIME else 0

    def _0dte_expiry_code(self, candle: dict) -> str:
        """Today's daily expiry code (DDMMYY) for morning / 0DTE preference."""
        return self._closed_bar_time_ist(candle).date().strftime("%d%m%y")

    def _is_morning_entry_slot(self, candle: dict) -> bool:
        """True when this closed 1H bar's close time is 08:30 IST."""
        close_t = self._closed_bar_time_ist(candle).time().replace(
            second=0, microsecond=0
        )
        return close_t == MORNING_ENTRY_TIME

    def _exit_intent(self, position: Any, candle: dict, ctx: Any, reason: str) -> Any:
        price = None
        if RUN_MODE == RunMode.BACKTEST:
            price = self.get_option_price_at_candle(
                candle,
                ctx,
                position.instrument.strike,
                position.instrument.option_type,
                position.instrument.expiry,
                trading_symbol=position.instrument.trading_symbol,
            )
        elif RUN_MODE != RunMode.BACKTEST:
            # Aggressive buy-to-cover limit for emergency exits.
            price = self._live_exit_limit_price(position, ctx)
        sid = str(getattr(position, "structure_id", "") or "")
        meta = self._meta_by_structure_id.get(sid) if sid else None
        entry_reason = meta.entry_reason if meta is not None else None
        inst = getattr(position, "instrument", None)
        logger.info(
            "%s EXIT signaled reason=%s entry_reason=%s symbol=%s strike=%s "
            "sid=%s qty=%s",
            self.name,
            reason,
            entry_reason or "unknown",
            getattr(inst, "trading_symbol", None),
            getattr(inst, "strike", None),
            sid,
            abs(int(getattr(position, "net_qty", 0) or 0)) or 1,
        )
        return self.create_order_intent(
            inst=position.instrument,
            side="BUY" if int(position.net_qty) < 0 else "SELL",
            qty=abs(int(position.net_qty or 0)) or 1,
            price=price,
            order_type="LIMIT",
            strategy=self.name,
            candle_ts=candle["timestamp"],
            structure_id=position.structure_id,
            tag="MAIN_EXIT",
            symbol=self._resolve_underlying(
                candle=candle, meta=meta, structure_id=sid, position=position
            ),
            action="EXIT",
            metadata_extras={
                "exit_reason": reason,
                "entry_reason": entry_reason or "unknown",
            },
        )

    @staticmethod
    def _exit_reason_from_fill(
        *,
        tag: str,
        metadata_extras: Any,
        transition_reason: Optional[str] = None,
    ) -> str:
        extras = metadata_extras if isinstance(metadata_extras, dict) else {}
        nested = extras.get("strategy_meta") if isinstance(extras.get("strategy_meta"), dict) else {}
        for source in (extras, nested):
            er = source.get("exit_reason")
            if er:
                return str(er)
        tag_u = str(tag or "").upper()
        if transition_reason:
            return str(transition_reason)
        if tag_u == "MAIN_SL":
            return "broker_main_sl"
        if tag_u == "MAIN_EXIT":
            return "main_exit"
        return tag_u or "unknown"

    def _live_exit_limit_price(self, position: Any, ctx: Any) -> Optional[float]:
        """Best ask (BUY cover) or best bid (SELL) when available."""
        inst = getattr(position, "instrument", None)
        side = "BUY" if int(getattr(position, "net_qty", 0) or 0) < 0 else "SELL"
        return self._live_option_limit_price(inst, ctx, side=side)

    def _live_option_limit_price(
        self, instrument: Any, ctx: Any, *, side: str = "BUY"
    ) -> Optional[float]:
        """Best ask for BUY / best bid for SELL on an option symbol."""
        symbol = str(getattr(instrument, "trading_symbol", "") or "")
        if not symbol:
            return None
        source = _delta_source_from_ctx(ctx)
        ticker = None
        if source is not None:
            try:
                ticker = source.get_ticker(symbol)
            except Exception:
                ticker = None
        if not isinstance(ticker, dict):
            return None
        quotes = ticker.get("quotes") or {}
        key = "best_ask" if str(side).upper() == "BUY" else "best_bid"
        try:
            px = float(quotes.get(key) or 0)
        except (TypeError, ValueError):
            px = 0.0
        if px <= 0:
            for fallback in ("mark_price", "close", "price"):
                try:
                    px = float(ticker.get(fallback) or 0)
                except (TypeError, ValueError):
                    px = 0.0
                if px > 0:
                    break
        return px if px > 0 else None

    def _live_option_mark_price(
        self, instrument: Any, ctx: Any
    ) -> Optional[float]:
        """Option mark / mid for short unrealized P&L (premium decay = green)."""
        symbol = str(getattr(instrument, "trading_symbol", "") or "")
        if not symbol:
            return None
        source = _delta_source_from_ctx(ctx)
        ticker = None
        if source is not None:
            try:
                ticker = source.get_ticker(symbol)
            except Exception:
                ticker = None
        if not isinstance(ticker, dict):
            return None
        quotes = ticker.get("quotes") or {}
        try:
            bid = float(quotes.get("best_bid") or 0)
        except (TypeError, ValueError):
            bid = 0.0
        try:
            ask = float(quotes.get("best_ask") or 0)
        except (TypeError, ValueError):
            ask = 0.0
        if bid > 0 and ask > 0:
            return (bid + ask) / 2.0
        for key in ("mark_price", "close", "price"):
            try:
                px = float(ticker.get(key) or 0)
            except (TypeError, ValueError):
                px = 0.0
            if px > 0:
                return px
        if bid > 0:
            return bid
        if ask > 0:
            return ask
        return None

    @staticmethod
    def _short_premium_pnl_positive(entry_premium: float, mark: float) -> bool:
        """Short option is green when mark has decayed below entry premium."""
        try:
            entry = float(entry_premium)
            m = float(mark)
        except (TypeError, ValueError):
            return False
        return entry > 0 and m > 0 and m < entry

    @staticmethod
    def _st_moved_favorably(
        direction: int, prev_st: float, new_st: float
    ) -> bool:
        """PE short (dir>0): ST rising; CE short (dir<0): ST falling."""
        try:
            prev = float(prev_st)
            cur = float(new_st)
        except (TypeError, ValueError):
            return False
        if direction > 0:
            return cur > prev + 1e-9
        if direction < 0:
            return cur < prev - 1e-9
        return False

    def _premium_sl_trigger(
        self, entry_premium: float, *, symbol: Any = None
    ) -> float:
        mult = float(
            self._symbol_cfg(symbol).get("premium_sl_mult") or PREMIUM_SL_MULT
        )
        return max(0.01, float(entry_premium) * mult)

    @staticmethod
    def _buy_cover_sl_limit(
        trigger: float,
        option_limit: float = 0.0,
        *,
        max_above: float = MAIN_SL_LIMIT_ABOVE_TRIGGER_MAX,
        min_above: float = MAIN_SL_LIMIT_ABOVE_TRIGGER_MIN,
    ) -> float:
        """
        Buy-to-cover stop-LIMIT price for MAIN_SL.

        Delta needs limit > trigger for a buy stop-limit. Cap the gap at
        ``max_above`` (default 10 pts) so limit never races far above trigger.
        """
        trig = max(0.01, float(trigger or 0))
        ceiling = float(max_above)
        floor_bump = min(float(min_above), ceiling) if ceiling > 0 else 0.0
        try:
            lim = float(option_limit or 0)
        except (TypeError, ValueError):
            lim = 0.0
        if lim <= trig:
            lim = trig + floor_bump
        if lim > trig + ceiling:
            lim = trig + ceiling
        # Final guard: always strictly above trigger when ceiling allows.
        if lim <= trig and ceiling > 0:
            lim = trig + min(floor_bump if floor_bump > 0 else ceiling, ceiling)
        return float(lim)

    def _build_main_sl_intent(
        self,
        *,
        instrument: Any,
        qty: int,
        structure_id: str,
        parent_intent_id: Optional[str],
        candle_ts: Any,
        direction: int,
        supertrend: float,
        option_limit: float,
        strike: Optional[float] = None,
        option_type: Optional[str] = None,
        sl_mode: str = SL_MODE_PREMIUM,
        entry_premium: Optional[float] = None,
        symbol: Any = None,
    ) -> Any:
        """
        Broker stop-LIMIT cover on the option.

        - premium mode: trigger on option mark at mult × entry premium.
        - index mode: trigger on underlying spot (ST ± trail_points); CE/PE clamp.
        Limit is always > trigger and within +10 pts of trigger.
        """
        under = self._resolve_underlying(
            structure_id=structure_id,
            trading_symbol=str(getattr(instrument, "trading_symbol", "") or ""),
        )
        if symbol is not None:
            under = normalize_underlying(symbol)
        ot = str(option_type or self._option_type(int(direction))).upper()
        mode = str(sl_mode or SL_MODE_PREMIUM).strip().lower()
        if mode not in (SL_MODE_PREMIUM, SL_MODE_INDEX):
            mode = SL_MODE_PREMIUM

        if mode == SL_MODE_PREMIUM:
            try:
                entry = float(entry_premium or 0)
            except (TypeError, ValueError):
                entry = 0.0
            level = self._premium_sl_trigger(entry, symbol=under)
            stop_method = "mark_price"
            limit_px = self._buy_cover_sl_limit(level, float(option_limit or 0))
            extras = {
                "stop_trigger_method": stop_method,
                "direction": int(direction),
                "trigger_symbol": str(
                    getattr(instrument, "trading_symbol", "") or ""
                ),
                "sl_mode": SL_MODE_PREMIUM,
                "premium_sl_trigger": float(level),
                "entry_premium": float(entry),
                "option_limit": float(limit_px),
                "exit_reason": "broker_main_sl_premium",
            }
        else:
            level = self._trail_sl_level(
                int(direction),
                float(supertrend),
                strike=strike,
                option_type=ot,
                symbol=under,
            )
            stop_method = "spot_price"
            # Index SL still buys the option; keep cover limit near trigger band.
            # Use live option ask as base, but still clamp relative to a synthetic
            # floor from the ask itself (spot trigger is not an option price).
            raw_lim = float(option_limit or 0)
            if raw_lim <= 0:
                raw_lim = 1.0
            # For index mode, trigger is spot; option limit is independent.
            # Still enforce limit > 0 and keep a sane ask-based cover — if caller
            # passed an option mark/ask as option_limit, bump it into the +1..+10
            # band above that ask only when it looks like a mark stop. Otherwise
            # leave index cover as max(ask, 1) without comparing to spot trigger.
            limit_px = max(raw_lim, 1.0)
            extras = {
                "stop_trigger_method": stop_method,
                "direction": int(direction),
                "trigger_symbol": under,
                "sl_mode": SL_MODE_INDEX,
                "trail_sl_level": float(level),
                "supertrend": float(supertrend),
                "option_limit": float(limit_px),
                "exit_reason": "broker_main_sl",
            }

        return self.create_order_intent(
            inst=instrument,
            side="BUY",
            qty=max(1, int(qty)),
            price=float(limit_px),
            order_type="SL",
            strategy=self.name,
            candle_ts=candle_ts,
            structure_id=structure_id,
            tag="MAIN_SL",
            symbol=under,
            action="FORCE_EXIT",
            parent_intent_id=parent_intent_id,
            trigger_price=float(level),
            metadata_extras=extras,
        )
    def _broker_still_has_position(self, ctx: Any, position: Any) -> bool:
        """True when local MAIN is open; prefer live broker position check when available."""
        if int(getattr(position, "net_qty", 0) or 0) == 0:
            return False
        router = getattr(ctx, "order_router", None)
        broker = getattr(router, "broker", None) if router is not None else None
        if broker is None:
            return True
        trading_symbol = str(
            getattr(getattr(position, "instrument", None), "trading_symbol", "") or ""
        )
        get_pos = getattr(broker, "get_positions", None) or getattr(
            broker, "get_open_positions", None
        )
        if not callable(get_pos) or not trading_symbol:
            return True
        try:
            rows = get_pos() or []
        except Exception:
            return True
        for row in rows:
            if not isinstance(row, dict):
                continue
            sym = str(
                row.get("symbol")
                or row.get("product_symbol")
                or row.get("trading_symbol")
                or ""
            ).upper()
            if sym != trading_symbol.upper():
                continue
            try:
                size = float(
                    row.get("size")
                    or row.get("net_qty")
                    or row.get("quantity")
                    or 0
                )
            except (TypeError, ValueError):
                size = 0.0
            return abs(size) > 0
        # Broker list has no matching row — still treat local open as present.
        return True

    def _cancel_resting_main_sl(self, ctx: Any, position: Any) -> bool:
        """
        Cancel resting broker MAIN_SL (FORCE_EXIT) so MAIN_EXIT can be placed.
        Without this, expiry rollover / SuperTrend reversal stay blocked while SL is open.
        """
        sid = str(getattr(position, "structure_id", "") or "")
        inst = getattr(position, "instrument", None)
        trading_symbol = str(getattr(inst, "trading_symbol", "") or "")
        product_id = getattr(inst, "product_id", None) if inst is not None else None
        router = getattr(ctx, "order_router", None)
        broker = getattr(router, "broker", None) if router is not None else None
        intent_store = getattr(ctx, "intent_store", None)
        cancelled = False

        if broker is not None and sid:
            cancel_pending = getattr(broker, "cancel_pending_sl", None)
            if callable(cancel_pending):
                try:
                    cancel_pending(sid, detail="expiry_rollover")
                    cancelled = True
                except Exception:
                    pass
            cancel_bracket = getattr(broker, "cancel_pending_bracket", None)
            if callable(cancel_bracket):
                try:
                    cancel_bracket(sid, reason="expiry_rollover")
                    cancelled = True
                except Exception:
                    pass

        order_id = None
        find_oid = getattr(broker, "find_bracket_leg_order_id", None) if broker else None
        if callable(find_oid) and trading_symbol:
            try:
                order_id = find_oid(trading_symbol, "MAIN_SL")
            except Exception:
                order_id = None
        rec = self._find_main_sl_record(ctx, sid) if sid else None
        intent_id = None
        if rec is not None:
            order_id = order_id or rec.get("broker_order_id")
            intent_id = rec.get("intent_id")
            payload = rec.get("payload") or {}
            if product_id is None:
                try:
                    product_id = int(payload.get("product_id"))
                except (TypeError, ValueError):
                    product_id = None
            if not trading_symbol:
                trading_symbol = str(payload.get("trading_symbol") or "")

        if broker is not None and order_id and hasattr(broker, "cancel_order_by_id"):
            try:
                ok = broker.cancel_order_by_id(
                    str(order_id),
                    intent_id=str(intent_id) if intent_id else None,
                    reason=f"{self.name}_rollover_cancel_sl",
                    product_id=int(product_id) if product_id is not None else None,
                    trading_symbol=trading_symbol or None,
                )
                cancelled = bool(ok) or cancelled
            except TypeError:
                # Brokers without product_id/trading_symbol kwargs.
                try:
                    ok = broker.cancel_order_by_id(
                        str(order_id),
                        intent_id=str(intent_id) if intent_id else None,
                        reason=f"{self.name}_rollover_cancel_sl",
                    )
                    cancelled = bool(ok) or cancelled
                except Exception:
                    pass
            except Exception as exc:
                logger.warning(
                    "%s cancel MAIN_SL failed sid=%s order_id=%s: %s",
                    self.name,
                    sid,
                    order_id,
                    exc,
                )

        if intent_store is not None and intent_id:
            try:
                from core.orderExecution.intent_store import IntentStatus

                intent_store.update(
                    str(intent_id),
                    IntentStatus.CANCELLED,
                    order_state="CANCELLED",
                )
                cancelled = True
            except Exception:
                pass

        if router is not None and hasattr(router, "cancel_unfilled_strategy_orders"):
            try:
                n = router.cancel_unfilled_strategy_orders(
                    self.name,
                    tags=["MAIN_SL"],
                    actions=["FORCE_EXIT"],
                )
                cancelled = cancelled or int(n or 0) > 0
            except Exception:
                pass

        if cancelled:
            logger.info(
                "%s cancelled resting MAIN_SL sid=%s order_id=%s for transition",
                self.name,
                sid,
                order_id,
            )
        return cancelled

    def _begin_transition(
        self,
        position: Any,
        candle: dict,
        ctx: Any,
        *,
        direction: int,
        reason: str,
        min_dte: int = 0,
        min_strike_distance: float = 0.0,
        sleeve: Optional[str] = None,
        reenter: bool = True,
    ) -> Optional[Any]:
        sid = str(getattr(position, "structure_id", "") or "")
        if not sid or sid in self._pending_exit_structure_ids:
            return None
        meta = self._ensure_meta(position, ctx)
        sleeve_u = str(
            sleeve
            or (meta.sleeve if meta is not None else SLEEVE_DAILY)
            or SLEEVE_DAILY
        )
        # Resting MAIN_SL is action=FORCE_EXIT; cancel it so MAIN_EXIT can be placed
        # (17:25 rollover was blocked all afternoon by the open trail SL).
        self._cancel_resting_main_sl(ctx, position)
        intent_store = getattr(ctx, "intent_store", None)
        if intent_store is not None and intent_store.has_pending_intent(
            strategy=self.name,
            structure_id=sid,
            actions=["EXIT", "FORCE_EXIT"],
        ):
            logger.warning(
                "%s transition blocked by pending EXIT/FORCE_EXIT sid=%s reason=%s",
                self.name,
                sid,
                reason,
            )
            return None
        self._pending_exit_structure_ids.add(sid)
        under = self._resolve_underlying(
            candle=candle, structure_id=sid, position=position
        )
        allow_reenter = bool(reenter) and self._sleeve_entries_enabled(
            sleeve_u, under
        )
        if allow_reenter:
            self._pending_transition = _PendingTransition(
                previous_structure_id=sid,
                direction=direction,
                reason=reason,
                min_dte=min_dte,
                min_strike_distance=min_strike_distance,
                sleeve=sleeve_u,
            )
        else:
            self._pending_transition = None
            logger.info(
                "%s transition EXIT only (no re-entry) sleeve=%s reason=%s sid=%s",
                self.name,
                sleeve_u,
                reason,
                sid,
            )
        return self._exit_intent(position, candle, ctx, reason)

    def _candle_with_supertrend(self, candle: dict) -> dict:
        """Stamp the latest confirmed SuperTrend onto a tick/quote candle for strike pick."""
        out = dict(candle)
        if self._current_supertrend is not None:
            out["supertrend"] = float(self._current_supertrend)
        if self._confirmed_direction is not None:
            out["supertrend_direction"] = int(self._confirmed_direction)
        if self._latest_candle:
            for key in ("open", "high", "low", "close"):
                if out.get(key) in (None, 0) and self._latest_candle.get(key) not in (
                    None,
                    0,
                ):
                    out[key] = self._latest_candle[key]
            if out.get("close") in (None, 0) and self._latest_candle.get("close"):
                out["close"] = self._latest_candle["close"]
        return out

    def _rollover_intent_if_due(
        self, candle: dict, ctx: Any, *, closed_bar: bool = False
    ) -> Optional[Any]:
        now = (
            self._closed_bar_time_ist(candle)
            if closed_bar
            else self._timestamp_ist(candle["timestamp"])
        )
        if now.time() < ROLLOVER_TIME or now.date() in self._rollover_dates:
            return None
        under = self._resolve_underlying(candle=candle)
        self._bind_symbol(under)
        positions = self._open_main_positions(ctx, underlying=under)
        today_positions = [
            position
            for position in positions
            if self._expiry_date(getattr(position.instrument, "expiry", None))
            == now.date()
        ]
        if not today_positions:
            # Only mark done when flat — keep retrying if a today-expiry leg is open.
            if not positions:
                self._rollover_dates.add(now.date())
            return None

        # Prefer morning 0DTE flat-exit before daily/weekly roll of today-expiry.
        def _sleeve_of(pos: Any) -> str:
            meta = self._ensure_meta(pos, ctx)
            return str(meta.sleeve) if meta is not None else SLEEVE_DAILY

        morning_today = [
            p for p in today_positions if _sleeve_of(p) == SLEEVE_MORNING
        ]
        position = (morning_today or today_positions)[0]
        meta = self._ensure_meta(position, ctx)
        sleeve_u = str(meta.sleeve) if meta is not None else SLEEVE_DAILY
        direction = (
            self._confirmed_direction
            if self._confirmed_direction is not None
            else (meta.direction if meta is not None else 1)
        )
        work_candle = self._candle_with_supertrend(candle)
        self._latest_candle = dict(work_candle)
        if self._current_supertrend is None and meta is not None:
            self._current_supertrend = float(meta.supertrend)
            work_candle["supertrend"] = float(meta.supertrend)

        if sleeve_u == SLEEVE_MORNING:
            # Morning is always 0DTE: flatten at 17:25 — never roll to next expiry.
            intent = self._begin_transition(
                position,
                work_candle,
                ctx,
                direction=int(direction),
                reason="morning_0dte_flat",
                sleeve=SLEEVE_MORNING,
                reenter=False,
            )
            if intent is not None:
                remaining = [
                    p
                    for p in today_positions
                    if str(getattr(p, "structure_id", "") or "")
                    != str(getattr(position, "structure_id", "") or "")
                ]
                if not remaining:
                    self._rollover_dates.add(now.date())
                logger.info(
                    "%s morning 0DTE flat EXIT at 17:25 expiry=%s direction=%s "
                    "(no next-expiry rollover)",
                    self.name,
                    getattr(getattr(position, "instrument", None), "expiry", None),
                    direction,
                )
            return intent

        # Daily / weekly today-expiry: exit + re-enter next listed daily.
        intent = self._begin_transition(
            position,
            work_candle,
            ctx,
            direction=int(direction),
            reason="expiry_rollover",
            min_dte=1,
            min_strike_distance=float(
                self._symbol_cfg(under).get("rollover_min_strike_distance")
                or ROLLOVER_MIN_STRIKE_DISTANCE
            ),
            sleeve=sleeve_u,
        )
        if intent is not None:
            remaining = [
                p
                for p in today_positions
                if str(getattr(p, "structure_id", "") or "")
                != str(getattr(position, "structure_id", "") or "")
            ]
            if not remaining:
                self._rollover_dates.add(now.date())
            logger.info(
                "%s expiry rollover EXIT started expiry=%s direction=%s ST=%.2f",
                self.name,
                getattr(getattr(position, "instrument", None), "expiry", None),
                direction,
                float(self._current_supertrend or 0),
            )
        return intent

    def _trail_open_sleeves(
        self,
        ctx: Any,
        candle: dict,
        *,
        one_h_st: Optional[float],
        previous_st: Optional[float],
        source: str = "on_candle",
    ) -> List[Any]:
        """
        Manage broker MAIN_SL per open MAIN:

        - premium mode: keep 2× mark SL while red; when green + ST favorable,
          cancel premium SL and return a new index/ST MAIN_SL intent.
        - index mode: trail spot SL on SuperTrend as before.
        """
        switch_intents: List[Any] = []
        under = self._resolve_underlying(candle=candle)
        self._bind_symbol(under)
        positions = self._open_main_positions(ctx, underlying=under)
        if not positions:
            logger.debug(
                "%s trail skip source=%s reason=no_open_main",
                self.name,
                source,
            )
            return switch_intents
        weekly_st = self._resolve_weekly_trail_st(ctx, candle)
        monthly_st = self._resolve_1d_trail_st(ctx, candle)
        for position in positions:
            meta = self._ensure_meta(position, ctx)
            pos_dir = (
                int(meta.direction)
                if meta is not None
                else int(self._confirmed_direction or 0)
            )
            if not pos_dir:
                continue
            sleeve = str(meta.sleeve) if meta is not None else SLEEVE_DAILY
            sid = str(getattr(position, "structure_id", "") or "")
            sl_mode = (
                str(meta.sl_mode).strip().lower()
                if meta is not None
                else SL_MODE_INDEX
            )
            if sl_mode not in (SL_MODE_PREMIUM, SL_MODE_INDEX):
                sl_mode = SL_MODE_INDEX

            if self._uses_4h_trail(sleeve):
                ref_st = float(weekly_st) if weekly_st is not None else 0.0
                if ref_st <= 0:
                    logger.error(
                        "%s TRAIL_SKIP_%s sid=%s source=%s reason=no_live_4h_st "
                        "meta_ST=%s (will not fall back to 1H/entry ST)",
                        self.name,
                        str(sleeve).upper(),
                        sid,
                        source,
                        f"{float(meta.supertrend):.2f}" if meta is not None else "None",
                    )
                    continue
            elif self._uses_1d_trail(sleeve):
                ref_st = float(monthly_st) if monthly_st is not None else 0.0
                if ref_st <= 0:
                    logger.error(
                        "%s TRAIL_SKIP_%s sid=%s source=%s reason=no_live_1d_st "
                        "meta_ST=%s (will not fall back to 1H/entry ST)",
                        self.name,
                        str(sleeve).upper(),
                        sid,
                        source,
                        f"{float(meta.supertrend):.2f}" if meta is not None else "None",
                    )
                    continue
            else:
                try:
                    ref_st = float(one_h_st) if one_h_st is not None else 0.0
                except (TypeError, ValueError):
                    ref_st = 0.0
                if ref_st <= 0:
                    logger.warning(
                        "%s TRAIL_SKIP_DAILY sid=%s source=%s reason=no_1h_st",
                        self.name,
                        sid,
                        source,
                    )
                    continue
            prev_ref = float(meta.supertrend) if meta is not None else previous_st

            if sl_mode == SL_MODE_PREMIUM:
                switched = self._maybe_switch_premium_sl_to_index(
                    ctx,
                    position,
                    meta=meta,
                    ref_st=ref_st,
                    prev_ref=float(prev_ref) if prev_ref is not None else None,
                    candle=candle,
                    source=source,
                )
                if switched is not None:
                    switch_intents.append(switched)
                continue

            # Index / SuperTrend trail path.
            if prev_ref is None:
                self._apply_trail_sl_update(
                    ctx,
                    position,
                    direction=pos_dir,
                    ref_st=ref_st,
                    sleeve=sleeve,
                    prev_ref=None,
                )
                continue
            if abs(ref_st - float(prev_ref)) <= 1e-9:
                logger.debug(
                    "%s trail unchanged sid=%s sleeve=%s ST=%.2f source=%s",
                    self.name,
                    sid,
                    sleeve,
                    ref_st,
                    source,
                )
                continue
            logger.info(
                "%s trail ST moved sid=%s sleeve=%s %.2f -> %.2f desired_sl=%.2f "
                "source=%s",
                self.name,
                sid,
                sleeve,
                float(prev_ref),
                ref_st,
                self._trail_sl_level(
                    pos_dir,
                    ref_st,
                    strike=meta.strike if meta is not None else None,
                    option_type=meta.option_type if meta is not None else None,
                    symbol=self._resolve_underlying(
                        candle=candle, meta=meta, structure_id=sid
                    ),
                ),
                source,
            )
            self._apply_trail_sl_update(
                ctx,
                position,
                direction=pos_dir,
                ref_st=ref_st,
                sleeve=sleeve,
                prev_ref=float(prev_ref),
            )
        self._retry_pending_trail_sl(ctx)
        return switch_intents

    def _maybe_switch_premium_sl_to_index(
        self,
        ctx: Any,
        position: Any,
        *,
        meta: Optional[_PositionMeta],
        ref_st: float,
        prev_ref: Optional[float],
        candle: dict,
        source: str,
    ) -> Optional[Any]:
        """
        While on premium SL: if short is green and ST moved favorably, cancel
        the mark SL and return a new spot/ST MAIN_SL intent (one-way switch).
        """
        if meta is None:
            return None
        sid = str(getattr(position, "structure_id", "") or "")
        pos_dir = int(meta.direction)
        entry = float(meta.entry_premium or 0)
        if entry <= 0 or ref_st <= 0:
            return None
        mark = self._live_option_mark_price(getattr(position, "instrument", None), ctx)
        if mark is None or mark <= 0:
            logger.debug(
                "%s premium SL keep sid=%s source=%s reason=no_mark",
                self.name,
                sid,
                source,
            )
            return None
        green = self._short_premium_pnl_positive(entry, mark)
        if not green:
            logger.info(
                "%s premium SL keep sid=%s source=%s mark=%.2f entry=%.2f (red/flat)",
                self.name,
                sid,
                source,
                mark,
                entry,
            )
            return None
        if prev_ref is None:
            logger.info(
                "%s premium SL keep sid=%s source=%s green but no prev ST to compare",
                self.name,
                sid,
                source,
            )
            return None
        if not self._st_moved_favorably(pos_dir, float(prev_ref), float(ref_st)):
            logger.info(
                "%s premium SL keep sid=%s source=%s green but ST not favorable "
                "prev=%.2f new=%.2f dir=%s",
                self.name,
                sid,
                source,
                float(prev_ref),
                float(ref_st),
                pos_dir,
            )
            return None

        cancelled = self._cancel_resting_main_sl(ctx, position)
        logger.info(
            "%s switch MAIN_SL premium→index sid=%s source=%s mark=%.2f entry=%.2f "
            "ST %.2f→%.2f cancel_ok=%s",
            self.name,
            sid,
            source,
            mark,
            entry,
            float(prev_ref),
            float(ref_st),
            cancelled,
        )
        option_limit = self._live_option_limit_price(
            getattr(position, "instrument", None), ctx, side="BUY"
        )
        if option_limit is None or float(option_limit) <= 0:
            option_limit = max(mark, 1.0)
        qty = abs(int(getattr(position, "net_qty", 0) or 0)) or self._entry_qty_lots(
            meta.sleeve
        )
        intent = self._build_main_sl_intent(
            instrument=getattr(position, "instrument", None),
            qty=int(qty),
            structure_id=sid,
            parent_intent_id=None,
            candle_ts=candle.get("timestamp") or datetime.now(),
            direction=pos_dir,
            supertrend=float(ref_st),
            option_limit=float(option_limit),
            strike=float(meta.strike) if meta.strike else None,
            option_type=meta.option_type,
            sl_mode=SL_MODE_INDEX,
            entry_premium=entry,
            symbol=meta.symbol,
        )
        self._meta_by_structure_id[sid] = replace(
            meta,
            sl_mode=SL_MODE_INDEX,
            supertrend=float(ref_st),
        )
        self._clear_trail_sl_retry(sid)
        return intent

    def on_candle(self, candle: dict, ctx: Any) -> Optional[List[Any]]:
        sym = normalize_underlying(candle.get("symbol"))
        if sym not in SUPPORTED_UNDERLYINGS:
            return None
        self._bind_symbol(sym)
        tf = self._candle_timeframe(candle)
        tf_l = tf.lower()
        # 1D closed bars: trail HTF sleeves only.
        if tf_l in ("1d", "d"):
            if RUN_MODE != RunMode.BACKTEST and not self._bar_is_fully_closed(candle):
                return None
            switch = self._trail_open_sleeves(
                ctx,
                candle,
                one_h_st=self._current_supertrend,
                previous_st=self._current_supertrend,
                source=f"htf_bar:{tf}",
            )
            return switch or None
        # 4H closed bars: trail + weekly entry / exit / SL reentry (not 1H path).
        if tf_l in ("4h", "4", "240"):
            if RUN_MODE != RunMode.BACKTEST and not self._bar_is_fully_closed(candle):
                return None
            intents: List[Any] = []
            switch = self._trail_open_sleeves(
                ctx,
                candle,
                one_h_st=self._current_supertrend,
                previous_st=self._current_supertrend,
                source=f"htf_bar:{tf}",
            )
            if switch:
                intents.extend(switch)
            weekly = self._process_weekly_on_4h_close(candle, ctx)
            if weekly:
                intents.extend(weekly)
            return intents or None
        # Live only: never confirm flips / entries on a forming hour bar.
        # Mid-bar risk = broker MAIN_SL (+ quote proximity / ST±300). ST reverse only at close.
        if RUN_MODE != RunMode.BACKTEST and not self._bar_is_fully_closed(candle):
            logger.debug(
                "%s skip forming bar ts=%s close_at=%s",
                self.name,
                candle.get("timestamp"),
                self._closed_bar_time_ist(candle),
            )
            return None
        direction = self._normal_direction(candle.get("supertrend_direction"))
        try:
            supertrend = float(candle.get("supertrend"))
            _close = float(candle.get("close"))
        except (TypeError, ValueError):
            return None
        if direction is None or pd.isna(supertrend) or supertrend <= 0 or _close <= 0:
            return None

        previous = self._confirmed_direction
        previous_st = self._current_supertrend

        # Signal change: require closed-bar close on the new side of SuperTrend.
        # Ignore ephemeral indicator flips that leave close on the old side.
        if (
            previous is not None
            and direction != previous
            and not self._close_confirms_direction(direction, _close, supertrend)
        ):
            logger.info(
                "%s ignore unconfirmed ST flip prev=%s new=%s close=%.2f ST=%.2f "
                "(MAIN_SL covers mid-bar; reverse only when close confirms)",
                self.name,
                previous,
                direction,
                _close,
                supertrend,
            )
            return None

        self._confirmed_direction = direction
        self._current_supertrend = supertrend
        self._latest_candle = dict(candle)

        prev_1d = self._confirmed_1d_direction
        htf = self._refresh_htf_state(ctx, candle)
        one_h_signal = previous is not None and direction != previous
        one_d_signal = False
        one_d_dir: Optional[int] = None
        if htf is not None:
            one_d_dir = int(htf["1d"][0])
            one_d_signal = (
                prev_1d is not None and one_d_dir != int(prev_1d)
            )
        intents = []

        switch = self._trail_open_sleeves(
            ctx,
            candle,
            one_h_st=supertrend,
            previous_st=previous_st,
            source="1h_bar",
        )
        if switch:
            intents.extend(switch)

        deferred = self._consume_pending_closed_entry(candle, ctx, direction)
        if deferred is not None:
            intents.append(deferred)
        elif self._pending_closed_entry is not None:
            rollover = self._rollover_intent_if_due(candle, ctx, closed_bar=True)
            return [rollover] if rollover is not None else None

        # SL reentry for non-weekly sleeves (weekly reenters on 4H close only).
        entered_sleeves: set[str] = set()
        if self._sl_reentry_ready(candle):
            sleeve = str(self._sl_reentry_sleeve or SLEEVE_DAILY)
            if sleeve == SLEEVE_WEEKLY:
                logger.debug(
                    "%s defer weekly SL reentry until 4H close",
                    self.name,
                )
            elif not self._open_main_positions(ctx, sleeve=sleeve, underlying=self._active_symbol):
                direction_at_sl = int(self._sl_reentry_direction or 0)
                if (
                    sleeve == SLEEVE_MONTHLY
                    and self._confirmed_1d_direction is not None
                ):
                    enter_dir = int(self._confirmed_1d_direction)
                else:
                    enter_dir = int(direction)
                reason = (
                    "sl_reentry_same"
                    if enter_dir == direction_at_sl
                    else "sl_reentry_flip"
                )
                if sleeve == SLEEVE_MONTHLY:
                    reentry_min_dte = MONTHLY_MIN_DTE
                elif sleeve == SLEEVE_MORNING:
                    reentry_min_dte = 0
                else:
                    reentry_min_dte = self._min_dte_for_candle(candle)
                intent = self._build_entry(
                    candle,
                    ctx,
                    enter_dir,
                    reason=reason,
                    min_dte=reentry_min_dte,
                    sleeve=sleeve,
                )
                if intent is not None:
                    self._clear_sl_reentry()
                    intents.append(intent)
                    entered_sleeves.add(sleeve)

        # Exit monthly on confirmed 1D SuperTrend flip against the open monthly direction.
        monthly_positions = self._open_main_positions(ctx, sleeve=SLEEVE_MONTHLY, underlying=self._active_symbol)
        if monthly_positions and one_d_signal and one_d_dir is not None:
            mpos = monthly_positions[0]
            mmeta = self._ensure_meta(mpos, ctx)
            mdir = int(mmeta.direction) if mmeta is not None else 0
            if mdir and one_d_dir != mdir:
                sid = str(getattr(mpos, "structure_id", "") or "")
                if sid not in self._pending_exit_structure_ids:
                    intent = self._begin_transition(
                        mpos,
                        candle,
                        ctx,
                        direction=int(one_d_dir),
                        reason="one_d_reversal",
                        min_dte=MONTHLY_MIN_DTE,
                        sleeve=SLEEVE_MONTHLY,
                    )
                    if intent is not None:
                        intents.append(intent)

        # Exit daily on confirmed 1H SuperTrend flip against the open daily direction.
        daily_positions = self._open_main_positions(ctx, sleeve=SLEEVE_DAILY, underlying=self._active_symbol)
        if daily_positions and one_h_signal:
            dpos = daily_positions[0]
            dmeta = self._ensure_meta(dpos, ctx)
            ddir = int(dmeta.direction) if dmeta is not None else 0
            if ddir and direction != ddir:
                sid = str(getattr(dpos, "structure_id", "") or "")
                if sid not in self._pending_exit_structure_ids:
                    intent = self._begin_transition(
                        dpos,
                        candle,
                        ctx,
                        direction=int(direction),
                        reason="one_h_reversal",
                        min_dte=self._min_dte_for_candle(candle),
                        sleeve=SLEEVE_DAILY,
                    )
                    if intent is not None:
                        intents.append(intent)

        # Exit morning on confirmed 1H SuperTrend flip against the open morning direction.
        morning_positions = self._open_main_positions(ctx, sleeve=SLEEVE_MORNING, underlying=self._active_symbol)
        if morning_positions and one_h_signal:
            mpos = morning_positions[0]
            mmeta = self._ensure_meta(mpos, ctx)
            mdir = int(mmeta.direction) if mmeta is not None else 0
            if mdir and direction != mdir:
                sid = str(getattr(mpos, "structure_id", "") or "")
                if sid not in self._pending_exit_structure_ids:
                    intent = self._begin_transition(
                        mpos,
                        candle,
                        ctx,
                        direction=int(direction),
                        reason="morning_one_h_reversal",
                        min_dte=0,
                        sleeve=SLEEVE_MORNING,
                    )
                    if intent is not None:
                        intents.append(intent)

        # Monthly: only on a confirmed 1D ST flip → monthly last-Friday expiry.
        if (
            SLEEVE_MONTHLY not in entered_sleeves
            and one_d_signal
            and one_d_dir is not None
            and not self._open_main_positions(ctx, sleeve=SLEEVE_MONTHLY, underlying=self._active_symbol)
        ):
            intent = self._build_entry(
                candle,
                ctx,
                int(one_d_dir),
                reason="one_d_signal",
                min_dte=MONTHLY_MIN_DTE,
                sleeve=SLEEVE_MONTHLY,
            )
            if intent is not None:
                intents.append(intent)
                entered_sleeves.add(SLEEVE_MONTHLY)

        # Morning 0DTE: once per day on the 08:30 IST closed 1H bar (1H ST only).
        if (
            SLEEVE_MORNING not in entered_sleeves
            and self._is_morning_entry_slot(candle)
            and not self._open_main_positions(ctx, sleeve=SLEEVE_MORNING, underlying=self._active_symbol)
        ):
            slot_date = self._closed_bar_time_ist(candle).date()
            if slot_date not in self._morning_entry_dates:
                logger.info(
                    "%s morning slot hit date=%s direction=%s ST=%.2f close=%.2f",
                    self.name,
                    slot_date,
                    direction,
                    float(supertrend),
                    float(_close),
                )
                intent = self._build_entry(
                    candle,
                    ctx,
                    int(direction),
                    reason="morning_830",
                    min_dte=0,
                    sleeve=SLEEVE_MORNING,
                )
                if intent is not None:
                    # Consume the once-per-day slot only after a real ENTRY intent.
                    self._morning_entry_dates.add(slot_date)
                    if len(self._morning_entry_dates) > 60:
                        self._morning_entry_dates = set(
                            sorted(self._morning_entry_dates)[-30:]
                        )
                    intents.append(intent)
                    entered_sleeves.add(SLEEVE_MORNING)
                else:
                    logger.warning(
                        "%s morning slot missed date=%s direction=%s "
                        "(build_entry returned None; will retry if slot bar re-eval)",
                        self.name,
                        slot_date,
                        direction,
                    )

        # Daily 0DTE/1DTE: only on a confirmed 1H ST flip (no mid-regime entries).
        # HTF filter (1D+4H must match 1H) is enforced inside _build_entry.
        if (
            SLEEVE_DAILY not in entered_sleeves
            and one_h_signal
            and not self._open_main_positions(ctx, sleeve=SLEEVE_DAILY, underlying=self._active_symbol)
        ):
            intent = self._build_entry(
                candle,
                ctx,
                int(direction),
                reason="one_h_signal",
                min_dte=self._min_dte_for_candle(candle),
                sleeve=SLEEVE_DAILY,
            )
            if intent is not None:
                intents.append(intent)
                entered_sleeves.add(SLEEVE_DAILY)

        rollover = self._rollover_intent_if_due(candle, ctx, closed_bar=True)
        if rollover is not None:
            intents.append(rollover)
        return intents or None

    def _process_weekly_on_4h_close(
        self, candle: dict, ctx: Any
    ) -> List[Any]:
        """
        Weekly sleeve decisions only on closed 4H bars: SL reentry, HTF regime
        exit, and aligned entry. 1H bars never open a new weekly.
        """
        intents: List[Any] = []
        htf = self._refresh_htf_state(ctx, candle)
        if htf is None:
            # Still allow SL reentry direction from cached 4H if present.
            htf_dirs_ok = (
                self._confirmed_4h_direction is not None
                and self._confirmed_1d_direction is not None
                and int(self._confirmed_4h_direction)
                == int(self._confirmed_1d_direction)
            )
            if not htf_dirs_ok and not self._sl_reentry_ready(candle):
                return intents

        entered = False
        # Weekly SL reentry waits for the next closed 4H (not 1H).
        if (
            self._sl_reentry_ready(candle)
            and str(self._sl_reentry_sleeve or "") == SLEEVE_WEEKLY
            and not self._open_main_positions(ctx, sleeve=SLEEVE_WEEKLY, underlying=self._active_symbol)
        ):
            direction_at_sl = int(self._sl_reentry_direction or 0)
            if self._confirmed_4h_direction is not None:
                enter_dir = int(self._confirmed_4h_direction)
            elif htf is not None:
                enter_dir = int(htf["4h"][0])
            else:
                enter_dir = direction_at_sl
            reason = (
                "sl_reentry_same"
                if enter_dir == direction_at_sl
                else "sl_reentry_flip"
            )
            intent = self._build_entry(
                candle,
                ctx,
                enter_dir,
                reason=reason,
                min_dte=WEEKLY_MIN_DTE,
                sleeve=SLEEVE_WEEKLY,
            )
            if intent is not None:
                self._clear_sl_reentry()
                intents.append(intent)
                entered = True

        weekly_positions = self._open_main_positions(ctx, sleeve=SLEEVE_WEEKLY, underlying=self._active_symbol)
        if weekly_positions and htf is not None:
            wpos = weekly_positions[0]
            wmeta = self._ensure_meta(wpos, ctx)
            wdir = int(wmeta.direction) if wmeta is not None else 0
            if wdir and (
                htf["4h"][0] != wdir or htf["1d"][0] != wdir
            ):
                sid = str(getattr(wpos, "structure_id", "") or "")
                new_dir = (
                    int(htf["4h"][0])
                    if htf["4h"][0] == htf["1d"][0]
                    else int(htf["4h"][0])
                )
                if sid not in self._pending_exit_structure_ids:
                    intent = self._begin_transition(
                        wpos,
                        candle,
                        ctx,
                        direction=new_dir,
                        reason="weekly_htf_misaligned",
                        min_dte=WEEKLY_MIN_DTE,
                        sleeve=SLEEVE_WEEKLY,
                    )
                    if intent is not None:
                        intents.append(intent)

        # Entry: 1D + 4H agree on this closed 4H bar.
        aligned = False
        want = 0
        if htf is not None and htf["4h"][0] == htf["1d"][0]:
            aligned = True
            want = int(htf["4h"][0])
        elif (
            self._confirmed_4h_direction is not None
            and self._confirmed_1d_direction is not None
            and int(self._confirmed_4h_direction)
            == int(self._confirmed_1d_direction)
        ):
            aligned = True
            want = int(self._confirmed_4h_direction)

        if (
            not entered
            and aligned
            and want
            and not self._open_main_positions(ctx, sleeve=SLEEVE_WEEKLY, underlying=self._active_symbol)
        ):
            intent = self._build_entry(
                candle,
                ctx,
                want,
                reason="weekly_htf_aligned",
                min_dte=WEEKLY_MIN_DTE,
                sleeve=SLEEVE_WEEKLY,
            )
            if intent is not None:
                intents.append(intent)
        return intents

    def on_quote(self, quote: dict, ctx: Any) -> Optional[List[Any]]:
        sym = normalize_underlying(quote.get("symbol"))
        if sym not in SUPPORTED_UNDERLYINGS:
            return None
        self._bind_symbol(sym)
        # Broker trail SL may have failed on the last ST move — retry between bars.
        self._retry_pending_trail_sl(ctx)
        timestamp = quote.get("ts")
        try:
            tick_dt = datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            tick_dt = datetime.now().astimezone()
        price = quote.get("ltp")
        try:
            spot = float(price)
        except (TypeError, ValueError):
            return None
        candle = {
            "symbol": sym,
            "timestamp": tick_dt,
            "open": spot,
            "high": spot,
            "low": spot,
            "close": spot,
            "exchange": "DELTA",
        }

        rollover = self._rollover_intent_if_due(candle, ctx)
        if rollover is not None:
            return [rollover]
        positions = self._open_main_positions(ctx, underlying=sym)
        if not positions:
            return None
        prox_band = float(
            self._symbol_cfg(sym).get("strike_proximity_exit_points")
            or STRIKE_PROXIMITY_EXIT_POINTS
        )
        # Risk-check every open sleeve for this underlying.
        for position in positions:
            sid = str(getattr(position, "structure_id", "") or "")
            if sid in self._pending_exit_structure_ids:
                continue
            meta = self._ensure_meta(position, ctx)
            sleeve = (
                str(meta.sleeve)
                if meta is not None
                else SLEEVE_DAILY
            )
            pos_strike = self._position_strike(position, meta)
            if pos_strike is not None and self._spot_near_position_strike(
                spot=spot, strike=pos_strike, band=prox_band
            ):
                if not self._broker_still_has_position(ctx, position):
                    continue
                self._arm_sl_reentry(
                    meta.direction if meta is not None else self._confirmed_direction,
                    tick_dt,
                    sleeve=sleeve,
                    symbol=sym,
                )
                self._pending_exit_structure_ids.add(sid)
                logger.warning(
                    "%s FORCE EXIT (strike proximity ±%.0f) sleeve=%s symbol=%s "
                    "spot=%.2f strike=%.2f",
                    self.name,
                    prox_band,
                    sleeve,
                    sym,
                    spot,
                    pos_strike,
                )
                return [
                    self._exit_intent(
                        position, candle, ctx, "strategy_strike_proximity_exit"
                    )
                ]
            # Weekly force-exit ST = 4H only; daily = 1H. Never mix TFs.
            trail_st = self._risk_supertrend_for_sleeve(sleeve, meta)
            position_direction = (
                meta.direction if meta is not None else self._confirmed_direction
            )
            if trail_st is None or trail_st <= 0 or position_direction is None:
                continue
            force_level = self._force_exit_level(
                int(position_direction), float(trail_st), symbol=sym
            )
            if not self._spot_hits_level(
                direction=int(position_direction),
                level=force_level,
                spot=spot,
            ):
                continue
            if not self._broker_still_has_position(ctx, position):
                continue
            self._arm_sl_reentry(
                int(position_direction), tick_dt, sleeve=sleeve, symbol=sym
            )
            self._pending_exit_structure_ids.add(sid)
            logger.warning(
                "%s FORCE EXIT (strategy ST±force) sleeve=%s symbol=%s spot=%.2f "
                "ST=%.2f level=%.2f direction=%s",
                self.name,
                sleeve,
                sym,
                spot,
                float(trail_st),
                force_level,
                position_direction,
            )
            return [
                self._exit_intent(position, candle, ctx, "strategy_force_exit_300")
            ]
        return None

    def should_exit(self, position: Any, candle: dict, ctx: Any = None) -> bool:
        if ctx is None or getattr(position, "tag", None) != "MAIN":
            return False
        meta = self._ensure_meta(position, ctx)
        # Never compare a foreign underlying candle (e.g. ETHUSD) to this
        # position's ST±force / proximity bands (BTC morning false exits).
        pos_under = self._resolve_underlying(
            meta=meta,
            position=position,
            structure_id=str(getattr(position, "structure_id", "") or ""),
        )
        candle_under = normalize_underlying((candle or {}).get("symbol"))
        if (
            candle_under in SUPPORTED_UNDERLYINGS
            and pos_under in SUPPORTED_UNDERLYINGS
            and candle_under != pos_under
        ):
            return False
        sleeve = str(meta.sleeve) if meta is not None else SLEEVE_DAILY
        pos_strike = self._position_strike(position, meta)
        spot = float(candle.get("close") or 0)
        low = float(candle.get("low") or spot or 0)
        high = float(candle.get("high") or spot or 0)
        if pos_strike is not None and self._spot_near_position_strike(
            spot=spot,
            strike=pos_strike,
            low=low,
            high=high,
            band=float(
                self._symbol_cfg(pos_under).get("strike_proximity_exit_points")
                or STRIKE_PROXIMITY_EXIT_POINTS
            ),
        ):
            return True
        # Bind so 1H/4H risk ST comes from this position's underlying runtime.
        self._bind_symbol(pos_under)
        supertrend = self._risk_supertrend_for_sleeve(sleeve, meta)
        position_direction = (
            meta.direction
            if meta is not None
            else (
                self._confirmed_4h_direction
                if self._uses_4h_trail(sleeve)
                else (
                    self._confirmed_1d_direction
                    if self._uses_1d_trail(sleeve)
                    else self._confirmed_direction
                )
            )
        )
        if position_direction is None or supertrend is None:
            return False
        force_level = self._force_exit_level(
            int(position_direction),
            float(supertrend),
            symbol=pos_under,
        )
        return self._spot_hits_level(
            direction=int(position_direction),
            level=force_level,
            spot=spot,
            low=low,
            high=high,
        )

    def on_position_exit(self, position: Any, candle: dict, ctx: Any) -> List[Any]:
        sid = str(getattr(position, "structure_id", "") or "")
        if not sid or sid in self._pending_exit_structure_ids:
            return []
        meta = self._ensure_meta(position, ctx)
        under = self._resolve_underlying(
            meta=meta,
            position=position,
            structure_id=sid,
        )
        candle_under = normalize_underlying((candle or {}).get("symbol"))
        if (
            candle_under in SUPPORTED_UNDERLYINGS
            and under in SUPPORTED_UNDERLYINGS
            and candle_under != under
        ):
            logger.warning(
                "%s on_position_exit skipped cross-symbol candle=%s position=%s sid=%s",
                self.name,
                candle_under,
                under,
                sid,
            )
            return []
        self._pending_exit_structure_ids.add(sid)
        sleeve = str(meta.sleeve) if meta is not None else SLEEVE_DAILY
        self._bind_symbol(under)
        self._arm_sl_reentry(
            meta.direction if meta is not None else self._confirmed_direction,
            candle["timestamp"],
            sleeve=sleeve,
            symbol=under,
        )
        pos_strike = self._position_strike(position, meta)
        spot = float(candle.get("close") or 0)
        low = float(candle.get("low") or spot or 0)
        high = float(candle.get("high") or spot or 0)
        reason = "strategy_force_exit_300"
        prox_band = float(
            self._symbol_cfg(under).get("strike_proximity_exit_points")
            or STRIKE_PROXIMITY_EXIT_POINTS
        )
        if pos_strike is not None and self._spot_near_position_strike(
            spot=spot, strike=pos_strike, low=low, high=high, band=prox_band
        ):
            reason = "strategy_strike_proximity_exit"
        return [self._exit_intent(position, candle, ctx, reason)]

    def on_main_entry_filled(
        self,
        *,
        ctx: Any,
        structure_id: Optional[str],
        metadata_extras: Any = None,
        **kwargs: Any,
    ) -> List[Any]:
        sid = str(structure_id or "")
        if sid:
            self._restore_meta(sid, metadata_extras)
        meta = self._meta_by_structure_id.get(sid) if sid else None
        if meta is not None:
            self._bind_symbol(meta.symbol)
        instrument = kwargs.get("instrument")
        qty = kwargs.get("qty")
        parent_intent_id = kwargs.get("intent_id")
        candle_ts = kwargs.get("candle_ts")
        if instrument is None:
            positions = (
                self._open_main_positions(
                    ctx, underlying=self._active_symbol
                )
                if ctx is not None
                else []
            )
            for position in positions:
                if str(getattr(position, "structure_id", "") or "") == sid:
                    instrument = getattr(position, "instrument", None)
                    qty = abs(int(getattr(position, "net_qty", 0) or 0)) or qty
                    parent_intent_id = parent_intent_id or getattr(
                        position, "intent_id", None
                    )
                    break
        direction = (
            meta.direction
            if meta is not None
            else (self._confirmed_direction if self._confirmed_direction is not None else 0)
        )
        supertrend = (
            meta.supertrend
            if meta is not None
            else float(self._current_supertrend or 0)
        )
        if instrument is None or not direction or supertrend <= 0:
            return []
        try:
            strike = float(meta.strike) if meta is not None else 0.0
        except (TypeError, ValueError, AttributeError):
            strike = 0.0
        if strike <= 0:
            try:
                strike = float(getattr(instrument, "strike", 0) or 0)
            except (TypeError, ValueError):
                strike = 0.0
        if strike <= 0:
            from .trail_sl import DosTrailSlMixin

            parsed = DosTrailSlMixin._strike_from_trading_symbol(
                getattr(instrument, "trading_symbol", None)
            )
            if parsed:
                strike = float(parsed)
        option_type = (
            str(meta.option_type).upper()
            if meta is not None and meta.option_type
            else self._option_type(int(direction))
        )
        if not option_type:
            sym_u = str(getattr(instrument, "trading_symbol", "") or "").upper()
            if sym_u.startswith("P-"):
                option_type = "PE"
            elif sym_u.startswith("C-"):
                option_type = "CE"
        entry_reason = meta.entry_reason if meta is not None else "unknown"
        inst_sym = getattr(instrument, "trading_symbol", None)
        default_qty = self._entry_qty_lots(
            meta.sleeve if meta is not None else SLEEVE_DAILY
        )
        fill_qty = int(qty or default_qty)
        logger.info(
            "%s ENTRY filled reason=%s direction=%s symbol=%s sid=%s qty=%s ST=%.2f",
            self.name,
            entry_reason,
            direction,
            inst_sym,
            sid,
            fill_qty,
            float(supertrend),
        )
        # Option LIMIT (never market): prefer live ask; fall back to entry premium.
        option_limit = None
        if ctx is not None:
            option_limit = self._live_option_limit_price(instrument, ctx, side="BUY")
        if option_limit is None or float(option_limit) <= 0:
            try:
                option_limit = float(meta.entry_premium) if meta is not None else 0.0
            except (TypeError, ValueError, AttributeError):
                option_limit = 0.0
        if option_limit is None or float(option_limit) <= 0:
            try:
                option_limit = float(kwargs.get("price") or 0)
            except (TypeError, ValueError):
                option_limit = 0.0
        try:
            entry_prem = float(meta.entry_premium) if meta is not None else float(
                kwargs.get("price") or 0
            )
        except (TypeError, ValueError, AttributeError):
            entry_prem = float(option_limit or 0)
        if entry_prem <= 0:
            entry_prem = float(option_limit or 1.0)
        premium_trigger = self._premium_sl_trigger(
            entry_prem,
            symbol=meta.symbol if meta is not None else self._active_symbol,
        )
        # Cover LIMIT from live ask; _build_main_sl_intent clamps to
        # (trigger, trigger+10].
        cover_limit = float(option_limit or 0)
        if meta is not None:
            self._meta_by_structure_id[sid] = replace(
                meta,
                sl_mode=SL_MODE_PREMIUM,
                entry_premium=float(entry_prem),
            )
            meta = self._meta_by_structure_id[sid]
        intent = self._build_main_sl_intent(
            instrument=instrument,
            qty=fill_qty,
            structure_id=sid,
            parent_intent_id=str(parent_intent_id) if parent_intent_id else None,
            candle_ts=candle_ts or datetime.now(),
            direction=int(direction),
            supertrend=float(supertrend),
            option_limit=float(cover_limit),
            strike=float(strike) if strike > 0 else None,
            option_type=option_type,
            sl_mode=SL_MODE_PREMIUM,
            entry_premium=float(entry_prem),
        )
        logger.info(
            "%s arm broker MAIN_SL sid=%s mode=premium mark_trigger=%.2f "
            "option_limit=%.2f entry=%.2f ST=%.2f direction=%s opt=%s strike=%.2f",
            self.name,
            sid,
            float(premium_trigger),
            float(intent.price),
            float(entry_prem),
            float(supertrend),
            direction,
            option_type,
            float(strike or 0),
        )
        return [intent]

    def on_main_exit_filled(self, **kwargs: Any) -> List[Any]:
        sid = str(kwargs.get("structure_id") or "")
        if not sid:
            return []
        tag = str(kwargs.get("tag") or "").upper()
        meta = self._meta_by_structure_id.get(sid)
        direction_at_exit = (
            meta.direction
            if meta is not None
            else self._confirmed_direction
        )
        entry_reason = meta.entry_reason if meta is not None else "unknown"
        transition = self._pending_transition
        transition_reason = (
            transition.reason
            if transition is not None and transition.previous_structure_id == sid
            else None
        )
        exit_reason = self._exit_reason_from_fill(
            tag=tag,
            metadata_extras=kwargs.get("metadata_extras"),
            transition_reason=transition_reason,
        )
        inst = kwargs.get("instrument")
        logger.info(
            "%s EXIT filled reason=%s entry_reason=%s tag=%s symbol=%s sid=%s "
            "qty=%s price=%s direction_at_exit=%s",
            self.name,
            exit_reason,
            entry_reason,
            tag or "unknown",
            getattr(inst, "trading_symbol", None),
            sid,
            kwargs.get("qty"),
            kwargs.get("price"),
            direction_at_exit,
        )
        self._pending_exit_structure_ids.discard(sid)
        exit_sleeve = (
            str(meta.sleeve)
            if meta is not None
            else (
                str(transition.sleeve)
                if transition is not None
                else SLEEVE_DAILY
            )
        )
        self._meta_by_structure_id.pop(sid, None)
        self._clear_trail_sl_retry(sid)
        if transition is not None and transition.previous_structure_id == sid:
            self._pending_transition = None
            self._clear_sl_reentry()
            # Signal reversal/rollover: close then immediately open the new direction.
            # Engine expects (intent, candle) pairs from on_main_exit_filled.
            ctx = kwargs.get("ctx")
            candle_ts = kwargs.get("candle_ts") or datetime.now()
            base = dict(self._latest_candle or {})
            if not base.get("timestamp"):
                base["timestamp"] = candle_ts
            if not base.get("symbol"):
                base["symbol"] = self._resolve_underlying(
                    meta=meta, structure_id=sid
                ) or self._active_symbol
            self._bind_symbol(base["symbol"])
            if self._current_supertrend is not None:
                base["supertrend"] = float(self._current_supertrend)
            base["supertrend_direction"] = int(transition.direction)
            candle = self._candle_with_supertrend(base)
            intent = None
            if ctx is not None:
                intent = self._build_entry(
                    candle,
                    ctx,
                    int(transition.direction),
                    reason=transition.reason,
                    min_dte=transition.min_dte
                    if transition.min_dte
                    else self._min_dte_for_candle(candle),
                    min_strike_distance=transition.min_strike_distance,
                    sleeve=str(transition.sleeve or SLEEVE_DAILY),
                )
            if intent is not None:
                logger.info(
                    "%s after EXIT filled: ENTRY new direction reason=%s "
                    "direction=%s sleeve=%s",
                    self.name,
                    transition.reason,
                    transition.direction,
                    transition.sleeve,
                )
                return [(intent, candle)]
            # Contract selection / ctx failed — retry on the next fully closed bar.
            self._arm_closed_entry(
                direction=transition.direction,
                reason=transition.reason,
                min_dte=transition.min_dte,
                min_strike_distance=transition.min_strike_distance,
                armed_after=candle_ts,
                sleeve=str(transition.sleeve or SLEEVE_DAILY),
            )
            logger.warning(
                "%s after EXIT filled: ENTRY failed, deferred reason=%s "
                "direction=%s sleeve=%s",
                self.name,
                transition.reason,
                transition.direction,
                transition.sleeve,
            )
            return []

        # Broker MAIN_SL or strategy MAIN_EXIT: wait for next 1hr close, then follow signal.
        fill_under = self._resolve_underlying(meta=meta, structure_id=sid)
        self._bind_symbol(fill_under)
        if tag == "MAIN_SL" and direction_at_exit is not None:
            self._arm_sl_reentry(
                direction_at_exit,
                kwargs.get("candle_ts") or datetime.now(),
                sleeve=exit_sleeve,
                symbol=fill_under,
            )
            logger.info(
                "%s after EXIT filled: SL reentry armed direction=%s sleeve=%s "
                "symbol=%s (wait for hour close; entry_reason will be sl_reentry_*)",
                self.name,
                direction_at_exit,
                exit_sleeve,
                fill_under,
            )
        elif (
            tag == "MAIN_EXIT"
            and direction_at_exit is not None
            and self._sl_reentry_direction is None
        ):
            self._arm_sl_reentry(
                direction_at_exit,
                kwargs.get("candle_ts") or datetime.now(),
                sleeve=exit_sleeve,
                symbol=fill_under,
            )
            logger.info(
                "%s after EXIT filled: reentry armed direction=%s sleeve=%s "
                "symbol=%s (wait for hour close; entry_reason will be sl_reentry_*)",
                self.name,
                direction_at_exit,
                exit_sleeve,
                fill_under,
            )
        return []

    def on_forced_exit(self, **kwargs: Any) -> None:
        sid = str(kwargs.get("structure_id") or "")
        self._pending_exit_structure_ids.discard(sid)
        # Broker MAIN_SL fills are often classified as EXTERNAL_CLOSE (new broker
        # order id after trail modify). That path calls on_forced_exit with the
        # position tag MAIN — not MAIN_SL — so on_main_exit_filled never runs.
        # Arm the same post-SL hour-close reentry so we do not stay flat.
        if not kwargs.get("position_closed"):
            return
        if self._pending_transition is not None:
            return
        if self._sl_reentry_direction is not None:
            return
        meta = self._meta_by_structure_id.get(sid) if sid else None
        direction = (
            meta.direction
            if meta is not None
            else self._confirmed_direction
        )
        if direction is None:
            return
        exit_ts = kwargs.get("candle_ts") or datetime.now(timezone.utc)
        sleeve = str(meta.sleeve) if meta is not None else SLEEVE_DAILY
        under = self._resolve_underlying(meta=meta, structure_id=sid)
        self._bind_symbol(under)
        self._arm_sl_reentry(
            int(direction), exit_ts, sleeve=sleeve, symbol=under
        )
        logger.info(
            "%s after forced/external close: SL reentry armed direction=%s "
            "symbol=%s source=%s sid=%s",
            self.name,
            direction,
            under,
            kwargs.get("execution_source") or kwargs.get("exit_reason") or "forced",
            sid,
        )
        if sid:
            self._meta_by_structure_id.pop(sid, None)

    def on_structure_exit(self, structure_id: str, **kwargs: Any) -> None:
        super().on_structure_exit(structure_id=structure_id, **kwargs)
        self._pending_exit_structure_ids.discard(str(structure_id))

