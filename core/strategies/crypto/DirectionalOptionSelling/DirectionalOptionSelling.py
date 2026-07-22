"""BTC SuperTrend directional option selling on Delta Exchange."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, replace
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
    META_KEY,
    MIN_PREMIUM_USD,
    ORDER_QTY_LOTS,
    ORDER_QTY_LOTS_DAILY,
    ORDER_QTY_LOTS_WEEKLY,
    ROLLOVER_MIN_STRIKE_DISTANCE,
    ROLLOVER_TIME,
    SLEEVE_DAILY,
    SLEEVE_WEEKLY,
    STRIKE_PROXIMITY_EXIT_POINTS,
    SUPER_TREND_FACTOR,
    SUPER_TREND_LENGTH,
    # Re-exported for tests / callers that import from this module.
    TRAIL_SL_PENDING_RETRY_GAP_SEC,
    TRAIL_SL_POINTS,
    WEEKLY_MIN_DTE,
)
from .htf import DosHtfMixin
from .trail_sl import DosTrailSlMixin, PendingTrailRetry as _PendingTrailRetry

logger = logging.getLogger(__name__)

# Sleeve entry switches (flip to False to stop new entries / SL re-entries for
# that sleeve). Open positions still trail SL, force-exit, and roll as usual.
ENABLE_WEEKLY_TRADES = False
ENABLE_INTRADAY_TRADES = True


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
    Dual-sleeve BTC SuperTrend option selling:

    - Weekly: when 1D and 4H SuperTrend agree, sell near 4H SuperTrend on the
      weekly Friday (skip to next week if DTE <= 2).
    - Daily (0DTE/1DTE): only on a confirmed 1H SuperTrend flip (no mid-regime
      catch-up), and only when 1D and 4H agree with that 1H direction; sell near
      1H SuperTrend (0DTE before 17:25 IST, else 1DTE).

    Both sleeves may be open together. Broker MAIN_SL trails at ST±100.

    Toggle ``ENABLE_WEEKLY_TRADES`` / ``ENABLE_INTRADAY_TRADES`` at module top
    to disable new entries (and SL re-entries) per sleeve.
    """

    name = "DirectionalOptionSelling"
    underlying_symbols = ["BTCUSD"]
    timeframe = "60"
    # Subscribe WS/REST for HTF bars used by the entry filter.
    extra_timeframes = list(HTF_TIMEFRAMES)
    required_context = ["option_chain"]
    api = "DELTA"
    expiryType = "Daily"
    order_qty_lots = ORDER_QTY_LOTS
    order_qty_lots_weekly = ORDER_QTY_LOTS_WEEKLY
    order_qty_lots_daily = ORDER_QTY_LOTS_DAILY
    supertrend_length = SUPER_TREND_LENGTH
    supertrend_factor = SUPER_TREND_FACTOR
    bracket_leg_tags = ["MAIN_SL"]

    @staticmethod
    def _sleeve_entries_enabled(sleeve: str) -> bool:
        """Whether new entries / SL re-entries are allowed for this sleeve."""
        sleeve_u = str(sleeve or SLEEVE_DAILY).strip().lower()
        if sleeve_u == SLEEVE_WEEKLY:
            return bool(ENABLE_WEEKLY_TRADES)
        return bool(ENABLE_INTRADAY_TRADES)

    def _entry_qty_lots(self, sleeve: str) -> int:
        """Lots for a new ENTRY: weekly (4H) vs daily (1H)."""
        sleeve_u = str(sleeve or SLEEVE_DAILY).strip().lower()
        if sleeve_u == SLEEVE_WEEKLY:
            return max(1, int(getattr(self, "order_qty_lots_weekly", ORDER_QTY_LOTS_WEEKLY) or 1))
        return max(1, int(getattr(self, "order_qty_lots_daily", ORDER_QTY_LOTS_DAILY) or 1))

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._confirmed_direction: Optional[int] = None
        self._current_supertrend: Optional[float] = None
        self._latest_candle: Optional[dict] = None
        self._meta_by_structure_id: Dict[str, _PositionMeta] = {}
        self._pending_exit_structure_ids: set[str] = set()
        self._pending_transition: Optional[_PendingTransition] = None
        # After reversal EXIT fill: wait for the next closed 60m bar before entering.
        self._pending_closed_entry: Optional[_PendingClosedEntry] = None
        # After any SL: wait for the next 1hr close, then enter current SuperTrend direction.
        # Stores the direction at SL time so same vs flip can be logged.
        self._sl_reentry_direction: Optional[int] = None
        self._sl_reentry_after: Optional[pd.Timestamp] = None
        self._sl_reentry_sleeve: Optional[str] = None
        self._evaluated_bars: set[str] = set()
        self._rollover_dates: set[date] = set()
        # Cache last closed HTF SuperTrend per timeframe: {tf: (dir, st, bar_open_utc)}.
        self._htf_st_cache: Dict[str, Tuple[int, float, pd.Timestamp]] = {}
        self._confirmed_4h_direction: Optional[int] = None
        self._confirmed_1d_direction: Optional[int] = None
        self._last_seen_4h_bar_open: Optional[pd.Timestamp] = None
        self._current_4h_supertrend: Optional[float] = None
        # structure_id → pending broker trail SL retry after failed modify.
        self._pending_trail_retries: Dict[str, _PendingTrailRetry] = {}

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
        while (exp - trade_date).days < WEEKLY_MIN_DTE:
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

        Weekly sleeve must use 4H ST only (never 1H). Daily uses 1H.
        """
        sleeve_u = str(sleeve or SLEEVE_DAILY).strip().lower()
        if sleeve_u == SLEEVE_WEEKLY:
            for candidate in (
                self._current_4h_supertrend,
                meta.supertrend if meta is not None else None,
            ):
                try:
                    st = float(candidate) if candidate is not None else 0.0
                except (TypeError, ValueError):
                    continue
                if st > 0:
                    return st
            return None
        for candidate in (
            self._current_supertrend,
            meta.supertrend if meta is not None else None,
        ):
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
        if not self._sleeve_entries_enabled(sleeve_u):
            logger.info(
                "%s deferred entry skipped sleeve=%s disabled reason=%s",
                self.name,
                sleeve_u,
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
        if self._open_main_positions(ctx, sleeve=sleeve):
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
        if str(candle.get("symbol") or "").strip().upper() != "BTCUSD":
            return False
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
            },
        )

    @staticmethod
    def _sleeve_from_structure_id(structure_id: str) -> Optional[str]:
        """Parse sleeve from sid like DirectionalOptionSelling:BTCUSD:weekly:..."""
        parts = [p.strip().lower() for p in str(structure_id or "").split(":")]
        for part in parts:
            if part in (SLEEVE_WEEKLY, SLEEVE_DAILY):
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
        if sleeve_u not in (SLEEVE_WEEKLY, SLEEVE_DAILY):
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
            # Weekly sleeve trails 4H ST; daily trails 1H ST.
            if sleeve == SLEEVE_WEEKLY:
                st = float(
                    self._current_4h_supertrend
                    or self._current_supertrend
                    or 0
                )
            else:
                st = float(self._current_supertrend or 0)
            return _PositionMeta(
                symbol="BTCUSD",
                direction=direction,
                option_type=option_type,
                supertrend=st,
                strike=strike,
                expiry=expiry,
                entry_premium=float(getattr(position, "avg_price", 0) or 0),
                entry_reason="restored",
                sleeve=sleeve,
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
                meta = self._meta_by_structure_id[sid]
                self._confirmed_direction = meta.direction
                # Do NOT seed _current_4h_supertrend from entry meta — that froze
                # weekly trail at entry ST after restart. Hydrate live 4H below.
                self._current_supertrend = meta.supertrend
        # After restore, load live last-closed 4H ST so weekly trail can catch up.
        live_4h = self._hydrate_4h_from_history()
        if live_4h is not None:
            logger.info(
                "%s hydrated live 4H SuperTrend=%.2f after startup restore",
                self.name,
                live_4h,
            )
        else:
            logger.warning(
                "%s could not hydrate live 4H SuperTrend after startup restore "
                "(weekly trail catch-up deferred until next closed 4h/1h bar)",
                self.name,
            )
        # Catch up broker MAIN_SL immediately when engine provides a ctx
        # (otherwise wait for the next 60m/4h BarClosed).
        if ctx is not None and live_4h is not None:
            try:
                candle = {
                    "symbol": "BTCUSD",
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
                    "%s startup trail catch-up failed: %s", self.name, exc
                )
    def _open_main_positions(
        self, ctx: Any, *, sleeve: Optional[str] = None
    ) -> List[Any]:
        out: List[Any] = []
        for position in (
            ctx.position_store.get_open_positions(strategy=self.name) or []
        ):
            if getattr(position, "tag", None) != "MAIN":
                continue
            if int(getattr(position, "net_qty", 0) or 0) == 0:
                continue
            if sleeve is not None:
                meta = self._ensure_meta(position, ctx)
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

    def _open_main_has_expiry(self, ctx: Any, expiry: str) -> bool:
        want = str(expiry or "").strip()
        if not want:
            return False
        for position in self._open_main_positions(ctx):
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
                # Fallback: next listed expiry after the weekly target.
                if not ordered:
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
    ) -> Optional[tuple[float, float, pd.Series, str]]:
        source = _delta_source_from_ctx(ctx)
        if source is None:
            return None
        opt_letter = option_type[0].upper()
        products = source.get_products(use_cache=True) or []
        matching = [
            product
            for product in products
            if str(product.get("symbol") or "").upper().startswith(f"{opt_letter}-BTC-")
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
                distance = abs(strike - supertrend)
                if distance >= float(min_strike_distance):
                    candidates.append((distance, strike, symbol, product))
            candidates.sort(key=lambda item: (item[0], item[1]))
            try:
                tickers = source.get_option_tickers_for_expiry("BTC", expiry, opt_letter) or {}
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
                if quote is None or quote[0] < MIN_PREMIUM_USD:
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
    ) -> Optional[tuple[float, float, pd.Series, str]]:
        df = self.load_delta_data_for_candle(candle, ctx)
        if df is None or df.empty:
            return None
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
        )
        for expiry in expiry_order:
            latest = (
                work[work["expiry"] == expiry]
                .sort_values("timestamp")
                .groupby("strike", as_index=False)
                .last()
            )
            latest["price"] = pd.to_numeric(latest["price"], errors="coerce")
            latest = latest[(latest["price"] >= MIN_PREMIUM_USD) & (latest["qty"] > 0)]
            if latest.empty:
                continue
            latest = latest.copy()
            latest = latest[
                latest["strike"].apply(
                    lambda strike: self._is_strictly_otm(option_type, strike, spot)
                    and self._is_outside_supertrend(option_type, strike, supertrend)
                )
            ]
            if latest.empty:
                continue
            latest["distance"] = (latest["strike"] - supertrend).abs()
            latest = latest[latest["distance"] >= float(min_strike_distance)]
            if latest.empty:
                continue
            row = latest.sort_values(["distance", "strike"]).iloc[0]
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
            )
        return self._select_live_contract(
            candle,
            ctx,
            option_type,
            supertrend,
            min_dte=min_dte,
            min_strike_distance=min_strike_distance,
            target_expiry=target_expiry,
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
        sleeve_u = str(sleeve or SLEEVE_DAILY).strip().lower()
        if sleeve_u not in (SLEEVE_WEEKLY, SLEEVE_DAILY):
            sleeve_u = SLEEVE_DAILY
        if not self._sleeve_entries_enabled(sleeve_u):
            return None
        if self._open_main_positions(ctx, sleeve=sleeve_u):
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
            entry_min_dte = WEEKLY_MIN_DTE
            # Even if sleeve meta was lost and the open leg looks "daily", never
            # stack another weekly MAIN on the same Friday expiry.
            if target_expiry and self._open_main_has_expiry(ctx, target_expiry):
                logger.info(
                    "%s skip weekly ENTRY: already open on expiry=%s",
                    self.name,
                    target_expiry,
                )
                return None
        selected = self._select_contract(
            candle,
            ctx,
            direction,
            supertrend,
            min_dte=entry_min_dte,
            min_strike_distance=min_strike_distance,
            target_expiry=target_expiry,
        )
        if selected is None:
            logger.warning(
                "%s: no %s %s contract premium >= %.2f near SuperTrend %.2f",
                self.name,
                sleeve_u,
                self._option_type(direction),
                MIN_PREMIUM_USD,
                supertrend,
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
            f"{self.name}:BTCUSD:{sleeve_u}:"
            f"{self._timestamp_ist(candle['timestamp']).date()}:"
            f"{option_type}:{uuid.uuid4().hex[:8]}"
        )
        meta = _PositionMeta(
            symbol="BTCUSD",
            direction=direction,
            option_type=option_type,
            supertrend=supertrend,
            strike=strike,
            expiry=expiry,
            entry_premium=premium,
            entry_reason=reason,
            sleeve=sleeve_u,
        )
        intent = self.map_instrument_to_intent(
            inst=inst,
            strike_row=row,
            strategy=self.name,
            side="SELL",
            structure_id=structure_id,
            candle_ts=candle["timestamp"],
            tag="MAIN",
            symbol="BTCUSD",
            action="ENTRY",
            metadata_extras=self._strategy_meta(meta),
        )
        qty_lots = self._entry_qty_lots(sleeve_u)
        intent = replace(intent, qty=qty_lots)
        self._meta_by_structure_id[structure_id] = meta
        logger.info(
            "%s ENTRY signaled reason=%s sleeve=%s direction=%s opt=%s strike=%.2f "
            "expiry=%s premium=%.2f qty=%s ST=%.2f ST_4h=%s ST_1d=%s sid=%s",
            self.name,
            reason,
            sleeve_u,
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
    ) -> None:
        """
        After SL, re-enter on the close of the 1hr candle that contained the SL.

        Example: SL at 11:01 inside the 10:30→11:30 bar → decide at 11:30 close
        (same SuperTrend → same direction; flipped → opposite).
        """
        if direction is None:
            return
        sleeve_u = str(sleeve or SLEEVE_DAILY)
        if not self._sleeve_entries_enabled(sleeve_u):
            logger.info(
                "%s SL reentry skipped sleeve=%s disabled",
                self.name,
                sleeve_u,
            )
            return
        self._sl_reentry_direction = int(direction)
        self._sl_reentry_after = self._timestamp_ist(exit_ts)
        self._sl_reentry_sleeve = sleeve_u
        logger.info(
            "%s SL reentry armed direction=%s sleeve=%s after=%s "
            "(reenter on that bar's close)",
            self.name,
            self._sl_reentry_direction,
            self._sl_reentry_sleeve,
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
            symbol="BTCUSD",
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
    ) -> Any:
        """
        Broker stop-limit on the option: trigger off BTC spot (ST ± 100),
        buy-to-cover LIMIT on the option (never market). Open limits are
        re-quoted to best ask every 30s by the engine exit refresher.
        """
        level = self._trail_sl_level(direction, supertrend)
        limit_px = float(option_limit)
        if limit_px <= 0:
            limit_px = 1.0
        return self.create_order_intent(
            inst=instrument,
            side="BUY",
            qty=max(1, int(qty)),
            price=limit_px,
            order_type="SL",
            strategy=self.name,
            candle_ts=candle_ts,
            structure_id=structure_id,
            tag="MAIN_SL",
            symbol="BTCUSD",
            action="FORCE_EXIT",
            parent_intent_id=parent_intent_id,
            trigger_price=level,
            metadata_extras={
                "stop_trigger_method": "spot_price",
                "direction": int(direction),
                "trigger_symbol": "BTCUSD",
                "trail_sl_level": float(level),
                "supertrend": float(supertrend),
                "option_limit": float(limit_px),
                "exit_reason": "broker_main_sl",
            },
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
        if self._sleeve_entries_enabled(sleeve_u):
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
                "%s transition EXIT only (no re-entry) sleeve=%s disabled sid=%s",
                self.name,
                sleeve_u,
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
        positions = self._open_main_positions(ctx)
        today_positions = [
            position
            for position in positions
            if self._expiry_date(getattr(position.instrument, "expiry", None)) == now.date()
        ]
        if not today_positions:
            # Only mark done when flat — keep retrying if a today-expiry leg is open.
            if not positions:
                self._rollover_dates.add(now.date())
            return None
        position = today_positions[0]
        meta = self._ensure_meta(position, ctx)
        direction = (
            self._confirmed_direction
            if self._confirmed_direction is not None
            else (meta.direction if meta is not None else 1)
        )
        # Use last confirmed SuperTrend for next-expiry strike selection after EXIT fills.
        work_candle = self._candle_with_supertrend(candle)
        self._latest_candle = dict(work_candle)
        if self._current_supertrend is None and meta is not None:
            self._current_supertrend = float(meta.supertrend)
            work_candle["supertrend"] = float(meta.supertrend)
        # Re-opening today's contract would defeat settlement protection, so rollover
        # deliberately starts from the next listed daily expiry.
        intent = self._begin_transition(
            position,
            work_candle,
            ctx,
            direction=int(direction),
            reason="expiry_rollover",
            min_dte=1,
            min_strike_distance=ROLLOVER_MIN_STRIKE_DISTANCE,
            sleeve=str(meta.sleeve) if meta is not None else SLEEVE_DAILY,
        )
        if intent is not None:
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
    ) -> None:
        """Trail broker MAIN_SL: weekly on live 4H ST, daily on 1H ST."""
        positions = self._open_main_positions(ctx)
        if not positions:
            logger.debug(
                "%s trail skip source=%s reason=no_open_main",
                self.name,
                source,
            )
            return
        weekly_st = self._resolve_weekly_trail_st(ctx, candle)
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
            if sleeve == SLEEVE_WEEKLY:
                ref_st = float(weekly_st) if weekly_st is not None else 0.0
                if ref_st <= 0:
                    logger.error(
                        "%s TRAIL_SKIP_WEEKLY sid=%s source=%s reason=no_live_4h_st "
                        "meta_ST=%s (will not fall back to 1H/entry ST)",
                        self.name,
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
                self._trail_sl_level(pos_dir, ref_st),
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

    def on_candle(self, candle: dict, ctx: Any) -> Optional[List[Any]]:
        if str(candle.get("symbol") or "").strip().upper() != "BTCUSD":
            return None
        tf = self._candle_timeframe(candle)
        # 4H/1D closed bars: trail weekly SL only — do not treat HTF ST as 1H signal.
        if tf.lower() in ("4h", "4", "240", "1d", "d"):
            if RUN_MODE != RunMode.BACKTEST and not self._bar_is_fully_closed(candle):
                return None
            self._trail_open_sleeves(
                ctx,
                candle,
                one_h_st=self._current_supertrend,
                previous_st=self._current_supertrend,
                source=f"htf_bar:{tf}",
            )
            return None
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

        htf = self._refresh_htf_state(ctx, candle)
        one_h_signal = previous is not None and direction != previous
        intents: List[Any] = []

        self._trail_open_sleeves(
            ctx,
            candle,
            one_h_st=supertrend,
            previous_st=previous_st,
            source="1h_bar",
        )

        deferred = self._consume_pending_closed_entry(candle, ctx, direction)
        if deferred is not None:
            intents.append(deferred)
        elif self._pending_closed_entry is not None:
            rollover = self._rollover_intent_if_due(candle, ctx, closed_bar=True)
            return [rollover] if rollover is not None else None

        # SL reentry for the sleeve that was stopped out.
        entered_sleeves: set[str] = set()
        if self._sl_reentry_ready(candle):
            sleeve = str(self._sl_reentry_sleeve or SLEEVE_DAILY)
            if not self._open_main_positions(ctx, sleeve=sleeve):
                direction_at_sl = int(self._sl_reentry_direction or 0)
                if sleeve == SLEEVE_WEEKLY and self._confirmed_4h_direction is not None:
                    enter_dir = int(self._confirmed_4h_direction)
                else:
                    enter_dir = int(direction)
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
                    min_dte=(
                        WEEKLY_MIN_DTE
                        if sleeve == SLEEVE_WEEKLY
                        else self._min_dte_for_candle(candle)
                    ),
                    sleeve=sleeve,
                )
                if intent is not None:
                    self._clear_sl_reentry()
                    intents.append(intent)
                    entered_sleeves.add(sleeve)

        # Exit weekly when 1D or 4H no longer agrees with the open weekly direction.
        weekly_positions = self._open_main_positions(ctx, sleeve=SLEEVE_WEEKLY)
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

        # Exit daily on confirmed 1H SuperTrend flip against the open daily direction.
        daily_positions = self._open_main_positions(ctx, sleeve=SLEEVE_DAILY)
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

        # Weekly entry: 1D + 4H already green/red together → weekly near 4H ST.
        if (
            SLEEVE_WEEKLY not in entered_sleeves
            and htf is not None
            and htf["4h"][0] == htf["1d"][0]
        ):
            want = int(htf["4h"][0])
            if not self._open_main_positions(ctx, sleeve=SLEEVE_WEEKLY):
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
                    entered_sleeves.add(SLEEVE_WEEKLY)

        # Daily 0DTE/1DTE: only on a confirmed 1H ST flip (no mid-regime entries).
        # HTF filter (1D+4H must match 1H) is enforced inside _build_entry.
        if (
            SLEEVE_DAILY not in entered_sleeves
            and one_h_signal
            and not self._open_main_positions(ctx, sleeve=SLEEVE_DAILY)
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

    def on_quote(self, quote: dict, ctx: Any) -> Optional[List[Any]]:
        if str(quote.get("symbol") or "").strip().upper() != "BTCUSD":
            return None
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
            "symbol": "BTCUSD",
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
        positions = self._open_main_positions(ctx)
        if not positions:
            return None
        # Risk-check every open sleeve (weekly and/or daily).
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
                spot=spot, strike=pos_strike
            ):
                if not self._broker_still_has_position(ctx, position):
                    continue
                self._arm_sl_reentry(
                    meta.direction if meta is not None else self._confirmed_direction,
                    tick_dt,
                    sleeve=sleeve,
                )
                self._pending_exit_structure_ids.add(sid)
                logger.warning(
                    "%s FORCE EXIT (strike proximity ±%.0f) sleeve=%s "
                    "spot=%.2f strike=%.2f",
                    self.name,
                    STRIKE_PROXIMITY_EXIT_POINTS,
                    sleeve,
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
                int(position_direction), float(trail_st)
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
                int(position_direction), tick_dt, sleeve=sleeve
            )
            self._pending_exit_structure_ids.add(sid)
            logger.warning(
                "%s FORCE EXIT (strategy 300) sleeve=%s spot=%.2f ST=%.2f "
                "level=%.2f direction=%s",
                self.name,
                sleeve,
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
        sleeve = str(meta.sleeve) if meta is not None else SLEEVE_DAILY
        pos_strike = self._position_strike(position, meta)
        spot = float(candle.get("close") or 0)
        low = float(candle.get("low") or spot or 0)
        high = float(candle.get("high") or spot or 0)
        if pos_strike is not None and self._spot_near_position_strike(
            spot=spot, strike=pos_strike, low=low, high=high
        ):
            return True
        supertrend = self._risk_supertrend_for_sleeve(sleeve, meta)
        position_direction = (
            meta.direction
            if meta is not None
            else (
                self._confirmed_4h_direction
                if sleeve == SLEEVE_WEEKLY
                else self._confirmed_direction
            )
        )
        if position_direction is None or supertrend is None:
            return False
        force_level = self._force_exit_level(int(position_direction), float(supertrend))
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
        self._pending_exit_structure_ids.add(sid)
        meta = self._ensure_meta(position, ctx)
        sleeve = str(meta.sleeve) if meta is not None else SLEEVE_DAILY
        self._arm_sl_reentry(
            meta.direction if meta is not None else self._confirmed_direction,
            candle["timestamp"],
            sleeve=sleeve,
        )
        pos_strike = self._position_strike(position, meta)
        spot = float(candle.get("close") or 0)
        low = float(candle.get("low") or spot or 0)
        high = float(candle.get("high") or spot or 0)
        reason = "strategy_force_exit_300"
        if pos_strike is not None and self._spot_near_position_strike(
            spot=spot, strike=pos_strike, low=low, high=high
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
        instrument = kwargs.get("instrument")
        qty = kwargs.get("qty")
        parent_intent_id = kwargs.get("intent_id")
        candle_ts = kwargs.get("candle_ts")
        if instrument is None:
            positions = self._open_main_positions(ctx) if ctx is not None else []
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
        intent = self._build_main_sl_intent(
            instrument=instrument,
            qty=fill_qty,
            structure_id=sid,
            parent_intent_id=str(parent_intent_id) if parent_intent_id else None,
            candle_ts=candle_ts or datetime.now(),
            direction=int(direction),
            supertrend=float(supertrend),
            option_limit=float(option_limit or 1.0),
        )
        logger.info(
            "%s arm broker MAIN_SL sid=%s spot_trigger=%.2f option_limit=%.2f ST=%.2f direction=%s",
            self.name,
            sid,
            self._trail_sl_level(int(direction), float(supertrend)),
            float(option_limit or 1.0),
            float(supertrend),
            direction,
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
                base["symbol"] = "BTCUSD"
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
        if tag == "MAIN_SL" and direction_at_exit is not None:
            self._arm_sl_reentry(
                direction_at_exit,
                kwargs.get("candle_ts") or datetime.now(),
                sleeve=exit_sleeve,
            )
            logger.info(
                "%s after EXIT filled: SL reentry armed direction=%s sleeve=%s "
                "(wait for hour close; entry_reason will be sl_reentry_*)",
                self.name,
                direction_at_exit,
                exit_sleeve,
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
            )
            logger.info(
                "%s after EXIT filled: reentry armed direction=%s sleeve=%s "
                "(wait for hour close; entry_reason will be sl_reentry_*)",
                self.name,
                direction_at_exit,
                exit_sleeve,
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
        self._arm_sl_reentry(int(direction), exit_ts, sleeve=sleeve)
        logger.info(
            "%s after forced/external close: SL reentry armed direction=%s "
            "source=%s sid=%s",
            self.name,
            direction,
            kwargs.get("execution_source") or kwargs.get("exit_reason") or "forced",
            sid,
        )
        if sid:
            self._meta_by_structure_id.pop(sid, None)

    def on_structure_exit(self, structure_id: str, **kwargs: Any) -> None:
        super().on_structure_exit(structure_id=structure_id, **kwargs)
        self._pending_exit_structure_ids.discard(str(structure_id))

