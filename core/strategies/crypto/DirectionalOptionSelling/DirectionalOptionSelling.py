"""BTC SuperTrend directional option selling on Delta Exchange."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from run.config import RUN_MODE, RunMode
from core.strategies.base import BaseStrategy
from core.strategies.IndiaMktMixins import IST, IndiaMktMixins
from core.strategies.deltaMktMixins import DeltaMktMixins, _delta_source_from_ctx
from core.strategies.meta import pack_strategy_meta, unpack_strategy_meta
from core.utils.structure.supertrend import add_supertrend, supertrend_column_names

logger = logging.getLogger(__name__)

SUPER_TREND_LENGTH = 16
SUPER_TREND_FACTOR = 1.5
MIN_PREMIUM_USD = 120
# Broker MAIN_SL trails SuperTrend on the spot index: bullish ST-100 / bearish ST+100.
TRAIL_SL_POINTS = 100.0
# Strategy emergency: if spot breaches ST±300 and the position is still open, fire LIMIT exit.
FORCE_EXIT_POINTS = 300.0
# Extra risk: if spot trades within ±50 of the open option strike, exit immediately.
STRIKE_PROXIMITY_EXIT_POINTS = 50.0
ROLLOVER_TIME = time(17, 25)
ROLLOVER_MIN_STRIKE_DISTANCE = 200.0
ORDER_QTY_LOTS = 2
META_KEY = "directional_option_selling"
# Higher-TF SuperTrend: weekly on 1D+4H align; daily on 1H with 1D+4H filter.
HTF_TIMEFRAMES = ("4h", "1d")
HTF_LOOKBACK_DAYS = {"4h": 45, "1d": 120}
SLEEVE_WEEKLY = "weekly"
SLEEVE_DAILY = "daily"
# Weekly entry: if selected Friday is within 2 DTE, roll to next weekly Friday.
WEEKLY_MIN_DTE = 3


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


class DirectionalOptionSelling(IndiaMktMixins, DeltaMktMixins, BaseStrategy):
    """
    Dual-sleeve BTC SuperTrend option selling:

    - Weekly: when 1D and 4H SuperTrend agree, sell near 4H SuperTrend on the
      weekly Friday (skip to next week if DTE <= 2).
    - Daily (0DTE/1DTE): only on a confirmed 1H SuperTrend flip (no mid-regime
      catch-up), and only when 1D and 4H agree with that 1H direction; sell near
      1H SuperTrend (0DTE before 17:25 IST, else 1DTE).

    Both sleeves may be open together. Broker MAIN_SL trails at ST±100.
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
    supertrend_length = SUPER_TREND_LENGTH
    supertrend_factor = SUPER_TREND_FACTOR
    bracket_leg_tags = ["MAIN_SL"]

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

    @staticmethod
    def _tf_bar_seconds(timeframe: str) -> int:
        from core.data.candle_aggregator import TIMEFRAME_SECONDS

        key = str(timeframe or "").strip()
        return int(TIMEFRAME_SECONDS.get(key) or TIMEFRAME_SECONDS.get(key.lower()) or 0)

    def _as_of_utc(self, candle: dict) -> pd.Timestamp:
        """Evaluation instant: prefer closed 1H bar time, else candle timestamp."""
        try:
            if self._bar_is_fully_closed(candle):
                return self._closed_bar_time_ist(candle).tz_convert("UTC")
        except Exception:
            pass
        ts = self._timestamp_ist(candle["timestamp"]).tz_convert("UTC")
        return ts

    def _latest_closed_st_from_df(
        self, df: pd.DataFrame, *, timeframe: str, as_of_utc: pd.Timestamp
    ) -> Optional[Tuple[int, float, pd.Timestamp]]:
        """Return (direction, supertrend, bar_open_utc) for the last fully closed HTF bar."""
        if df is None or df.empty:
            return None
        bar_sec = self._tf_bar_seconds(timeframe)
        if bar_sec <= 0:
            return None
        work = df.copy()
        work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
        work = work.sort_values("timestamp").reset_index(drop=True)
        work = self.prepare_indicators(work)
        if "supertrend" not in work.columns or "supertrend_direction" not in work.columns:
            return None
        close_at = work["timestamp"] + pd.Timedelta(seconds=bar_sec)
        as_of = pd.Timestamp(as_of_utc)
        if as_of.tzinfo is None:
            as_of = as_of.tz_localize("UTC")
        else:
            as_of = as_of.tz_convert("UTC")
        closed = work.loc[close_at <= as_of]
        if closed.empty:
            return None
        row = closed.iloc[-1]
        direction = self._normal_direction(row.get("supertrend_direction"))
        try:
            st = float(row.get("supertrend"))
        except (TypeError, ValueError):
            return None
        if direction is None or pd.isna(st) or st <= 0:
            return None
        return direction, st, pd.Timestamp(row["timestamp"]).tz_convert("UTC")

    def _fetch_htf_ohlc(
        self, ctx: Any, timeframe: str, as_of_utc: pd.Timestamp
    ) -> Optional[pd.DataFrame]:
        source = _delta_source_from_ctx(ctx)
        if source is None or not hasattr(source, "get_intraday"):
            return None
        lookback = int(HTF_LOOKBACK_DAYS.get(timeframe, 60))
        end_d = pd.Timestamp(as_of_utc).tz_convert("UTC").date()
        start_d = end_d - timedelta(days=lookback)
        try:
            return source.get_intraday(
                "BTCUSD",
                start_d.isoformat(),
                end_d.isoformat(),
                timeframe,
                force_refresh_tail=True,
            )
        except Exception as exc:
            logger.warning(
                "%s HTF fetch failed tf=%s: %s", self.name, timeframe, exc
            )
            return None

    def _htf_supertrend(
        self, ctx: Any, timeframe: str, candle: dict
    ) -> Optional[Tuple[int, float, pd.Timestamp]]:
        """Cached last-closed SuperTrend for ``timeframe`` (4h / 1d)."""
        as_of = self._as_of_utc(candle)
        cached = self._htf_st_cache.get(timeframe)
        bar_sec = self._tf_bar_seconds(timeframe)
        if cached is not None and bar_sec > 0:
            _dir, _st, bar_open = cached
            next_close = bar_open + pd.Timedelta(seconds=bar_sec)
            # Still on the same closed HTF bar — reuse cache.
            if as_of < next_close + pd.Timedelta(seconds=bar_sec):
                return cached
        df = self._fetch_htf_ohlc(ctx, timeframe, as_of)
        snap = self._latest_closed_st_from_df(df, timeframe=timeframe, as_of_utc=as_of)
        if snap is not None:
            self._htf_st_cache[timeframe] = snap
        return snap

    def _htf_snapshot(
        self, ctx: Any, candle: dict
    ) -> Optional[Dict[str, Tuple[int, float]]]:
        """
        Return ``{"4h": (dir, st), "1d": (dir, st)}`` when both HTFs are available.
        """
        out: Dict[str, Tuple[int, float]] = {}
        for tf in HTF_TIMEFRAMES:
            snap = self._htf_supertrend(ctx, tf, candle)
            if snap is None:
                return None
            direction, st, _bar = snap
            out[tf] = (int(direction), float(st))
        return out

    def _htf_entry_allowed(
        self, direction: int, ctx: Any, candle: dict
    ) -> bool:
        """Backward-compatible alias: weekly-style 1D+4H alignment."""
        return self._weekly_htf_aligned(direction, ctx, candle)

    def _stamp_htf_on_candle(
        self, candle: dict, snap: Dict[str, Tuple[int, float]]
    ) -> None:
        d4, st4 = snap["4h"]
        d1d, st1d = snap["1d"]
        candle["supertrend_4h"] = st4
        candle["supertrend_4h_direction"] = d4
        candle["supertrend_1d"] = st1d
        candle["supertrend_1d_direction"] = d1d

    def _weekly_htf_aligned(
        self, direction: int, ctx: Any, candle: dict
    ) -> bool:
        """Weekly sleeve: 1D and 4H SuperTrend must both match direction."""
        want = self._normal_direction(direction)
        if want is None:
            return False
        snap = self._htf_snapshot(ctx, candle)
        if snap is None:
            logger.info(
                "%s weekly entry blocked: missing 1D/4H SuperTrend",
                self.name,
            )
            return False
        self._stamp_htf_on_candle(candle, snap)
        d4, st4 = snap["4h"]
        d1d, st1d = snap["1d"]
        if d4 != want or d1d != want:
            logger.info(
                "%s weekly entry blocked: want=%s 4h=%s (%.2f) 1d=%s (%.2f)",
                self.name,
                want,
                d4,
                st4,
                d1d,
                st1d,
            )
            return False
        logger.info(
            "%s weekly HTF aligned direction=%s 4h_ST=%.2f 1d_ST=%.2f",
            self.name,
            want,
            st4,
            st1d,
        )
        return True

    def _daily_htf_aligned(
        self, direction: int, ctx: Any, candle: dict
    ) -> bool:
        """
        Daily sleeve filter: long only if 1D+4H green; short only if 1D+4H red.
        Entry/exit timing itself is driven by the 1H SuperTrend.
        """
        want = self._normal_direction(direction)
        if want is None:
            return False
        snap = self._htf_snapshot(ctx, candle)
        if snap is None:
            logger.info(
                "%s daily entry blocked: missing 1D/4H SuperTrend",
                self.name,
            )
            return False
        self._stamp_htf_on_candle(candle, snap)
        d4, st4 = snap["4h"]
        d1d, st1d = snap["1d"]
        if d4 != want or d1d != want:
            logger.info(
                "%s daily entry blocked: 1H want=%s needs 4h+1d same; "
                "4h=%s (%.2f) 1d=%s (%.2f)",
                self.name,
                want,
                d4,
                st4,
                d1d,
                st1d,
            )
            return False
        logger.info(
            "%s daily HTF aligned with 1H direction=%s 4h_ST=%.2f 1d_ST=%.2f",
            self.name,
            want,
            st4,
            st1d,
        )
        return True

    def _refresh_htf_state(
        self, ctx: Any, candle: dict
    ) -> Optional[Dict[str, Tuple[int, float]]]:
        """Update cached 1D/4H directions. Returns snapshot or None."""
        snap = self._htf_snapshot(ctx, candle)
        if snap is None:
            return None
        self._stamp_htf_on_candle(candle, snap)
        d4, st4 = snap["4h"]
        d1d, _st1d = snap["1d"]
        self._current_4h_supertrend = float(st4)
        bar_open = None
        cached = self._htf_st_cache.get("4h")
        if cached is not None:
            bar_open = cached[2]
        if bar_open is not None:
            self._last_seen_4h_bar_open = bar_open
        self._confirmed_4h_direction = int(d4)
        self._confirmed_1d_direction = int(d1d)
        return snap

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
    def _trail_sl_level(direction: int, supertrend: float) -> float:
        """Broker SL level. Bullish: ST - 100. Bearish: ST + 100."""
        st = float(supertrend)
        if direction > 0:
            return st - TRAIL_SL_POINTS
        return st + TRAIL_SL_POINTS

    @staticmethod
    def _force_exit_level(direction: int, supertrend: float) -> float:
        """Strategy emergency exit level. Bullish: ST - 300. Bearish: ST + 300."""
        st = float(supertrend)
        if direction > 0:
            return st - FORCE_EXIT_POINTS
        return st + FORCE_EXIT_POINTS

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
        """Hourly candle timestamps are bucket starts; return confirmed close time."""
        bt = candle.get("bucket_ts")
        if bt is not None:
            try:
                open_utc = pd.Timestamp(int(float(bt)), unit="s", tz="UTC")
                return open_utc.tz_convert(IST) + pd.Timedelta(minutes=60)
            except (TypeError, ValueError, OverflowError):
                pass
        return self._timestamp_ist(candle["timestamp"]) + pd.Timedelta(minutes=60)

    def _bar_is_fully_closed(self, candle: dict, now: Optional[Any] = None) -> bool:
        """
        True only after the 60m bar close (e.g. 14:30 bar → evaluate at/after 15:30).
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
            sleeve=str(sleeve or SLEEVE_DAILY),
        )
        logger.info(
            "%s deferred entry armed direction=%s reason=%s sleeve=%s after=%s "
            "(wait for next closed 60m bar)",
            self.name,
            direction,
            reason,
            sleeve,
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
        bt = candle.get("bucket_ts")
        if bt is not None:
            try:
                return f"{symbol}|{int(float(bt))}"
            except (TypeError, ValueError):
                pass
        return f"{symbol}|{self._timestamp_ist(candle['timestamp']).isoformat()}"

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
            sleeve = str(raw.get("sleeve") or SLEEVE_DAILY).strip().lower()
            if sleeve not in (SLEEVE_WEEKLY, SLEEVE_DAILY):
                sleeve = SLEEVE_DAILY
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

    def _ensure_meta(self, position: Any, ctx: Any) -> Optional[_PositionMeta]:
        sid = str(getattr(position, "structure_id", "") or "")
        meta = self._meta_by_structure_id.get(sid)
        if meta is not None:
            return meta
        intent_store = getattr(ctx, "intent_store", None)
        intent_id = getattr(position, "intent_id", None)
        if intent_store is not None and intent_id and callable(getattr(intent_store, "get", None)):
            record = intent_store.get(intent_id) or {}
            payload = record.get("payload") or {}
            strategy_meta = payload.get("strategy_meta") or payload.get("metadata_extras") or {}
            if self._restore_meta(sid, strategy_meta):
                return self._meta_by_structure_id.get(sid)
        inst = getattr(position, "instrument", None)
        option_type = str(getattr(inst, "option_type", "") or "").upper()
        direction = 1 if option_type.startswith("P") else -1
        try:
            fallback = _PositionMeta(
                symbol="BTCUSD",
                direction=direction,
                option_type="PE" if direction > 0 else "CE",
                supertrend=float(self._current_supertrend or 0),
                strike=float(getattr(inst, "strike", 0) or 0),
                expiry=str(getattr(inst, "expiry", "") or ""),
                entry_premium=float(getattr(position, "avg_price", 0) or 0),
                entry_reason="restored",
                sleeve=SLEEVE_DAILY,
            )
        except (TypeError, ValueError):
            return None
        self._meta_by_structure_id[sid] = fallback
        return fallback

    def restore_state_on_startup(
        self, position_manager: Any, intent_store: Any = None
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
            if sid and self._restore_meta(sid, raw):
                meta = self._meta_by_structure_id[sid]
                self._confirmed_direction = meta.direction
                self._current_supertrend = meta.supertrend

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
        intent = replace(intent, qty=ORDER_QTY_LOTS)
        self._meta_by_structure_id[structure_id] = meta
        logger.info(
            "%s ENTRY signaled reason=%s sleeve=%s direction=%s opt=%s strike=%.2f "
            "expiry=%s premium=%.2f ST=%.2f ST_4h=%s ST_1d=%s sid=%s",
            self.name,
            reason,
            sleeve_u,
            direction,
            option_type,
            strike,
            expiry,
            premium,
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
        self._sl_reentry_direction = int(direction)
        self._sl_reentry_after = self._timestamp_ist(exit_ts)
        self._sl_reentry_sleeve = str(sleeve or SLEEVE_DAILY)
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

    def _find_main_sl_record(self, ctx: Any, structure_id: str) -> Optional[dict]:
        intent_store = getattr(ctx, "intent_store", None)
        if intent_store is None or not callable(getattr(intent_store, "list_by_status", None)):
            return None
        from core.orderExecution.intent_store import IntentStatus

        pending = []
        for status in (
            IntentStatus.SENT,
            IntentStatus.ACKED,
            IntentStatus.VALIDATED,
        ):
            pending.extend(intent_store.list_by_status(status) or [])
        for rec in pending:
            payload = rec.get("payload") or {}
            if str(payload.get("structure_id") or rec.get("structure_id") or "") != str(
                structure_id
            ):
                continue
            if str(payload.get("tag") or rec.get("tag") or "").upper() != "MAIN_SL":
                continue
            if str(payload.get("strategy") or rec.get("strategy") or "") not in {
                "",
                self.name,
            }:
                if str(payload.get("strategy_id") or "") != self.name:
                    continue
            return rec
        return None

    def _modify_broker_trail_sl(
        self, ctx: Any, position: Any, *, direction: int, supertrend: float
    ) -> bool:
        """Update resting broker MAIN_SL stop_price to the latest SuperTrend trail level."""
        level = self._trail_sl_level(direction, supertrend)
        router = getattr(ctx, "order_router", None)
        broker = getattr(router, "broker", None) if router is not None else None
        if broker is None:
            return False
        sid = str(getattr(position, "structure_id", "") or "")
        qty = abs(int(getattr(position, "net_qty", 0) or 0)) or 1
        inst = getattr(position, "instrument", None)
        trading_symbol = str(getattr(inst, "trading_symbol", "") or "")

        # Simulated / paper: update pending SL book directly when available.
        update_pending = getattr(broker, "update_pending_sl_trigger", None)
        if callable(update_pending) and sid:
            if update_pending(sid, level):
                logger.info(
                    "%s broker trail SL updated sid=%s level=%.2f (sim)",
                    self.name,
                    sid,
                    level,
                )
                return True

        order_id = None
        product_id = getattr(inst, "product_id", None) if inst is not None else None
        find_oid = getattr(broker, "find_bracket_leg_order_id", None)
        if callable(find_oid) and trading_symbol:
            order_id = find_oid(trading_symbol, "MAIN_SL")
        rec = self._find_main_sl_record(ctx, sid)
        if not order_id and rec is not None:
            order_id = rec.get("broker_order_id")
        if product_id is None and trading_symbol:
            api = getattr(broker, "api", None)
            pid_fn = getattr(api, "product_id_for_symbol", None) if api is not None else None
            if callable(pid_fn):
                product_id = pid_fn(trading_symbol)
        update_fn = getattr(broker, "update_order_stop_price", None)
        if not callable(update_fn) or not order_id or product_id is None:
            return False
        ok = bool(
            update_fn(
                product_id=int(product_id),
                order_id=str(order_id),
                new_stop_price=float(level),
                size=int(qty),
            )
        )
        if ok:
            logger.info(
                "%s broker trail SL updated sid=%s order=%s level=%.2f ST=%.2f",
                self.name,
                sid,
                order_id,
                level,
                float(supertrend),
            )
            if rec is not None:
                payload = rec.get("payload") or {}
                payload["trigger_price"] = float(level)
                payload["price"] = float(level)
                meta = dict(payload.get("strategy_meta") or {})
                meta["trail_sl_level"] = float(level)
                meta["supertrend"] = float(supertrend)
                payload["strategy_meta"] = meta
                rec["payload"] = payload
        return ok

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
        self._pending_transition = _PendingTransition(
            previous_structure_id=sid,
            direction=direction,
            reason=reason,
            min_dte=min_dte,
            min_strike_distance=min_strike_distance,
            sleeve=sleeve_u,
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

    def on_candle(self, candle: dict, ctx: Any) -> Optional[List[Any]]:
        if str(candle.get("symbol") or "").strip().upper() != "BTCUSD":
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

        # Trail broker SL: weekly on 4H ST, daily on 1H ST.
        for position in self._open_main_positions(ctx):
            meta = self._ensure_meta(position, ctx)
            pos_dir = int(meta.direction) if meta is not None else int(direction)
            sleeve = (
                str(meta.sleeve) if meta is not None else SLEEVE_DAILY
            )
            if sleeve == SLEEVE_WEEKLY:
                ref_st = float(
                    candle.get("supertrend_4h")
                    or self._current_4h_supertrend
                    or supertrend
                )
            else:
                ref_st = float(supertrend)
            prev_ref = float(meta.supertrend) if meta is not None else previous_st
            if prev_ref is not None and abs(ref_st - float(prev_ref)) > 1e-9:
                self._modify_broker_trail_sl(
                    ctx,
                    position,
                    direction=pos_dir,
                    supertrend=ref_st,
                )
                if meta is not None:
                    sid = str(getattr(position, "structure_id", "") or "")
                    if sid:
                        self._meta_by_structure_id[sid] = replace(
                            meta, supertrend=ref_st
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
            trail_st = float(
                (meta.supertrend if meta is not None else 0)
                or self._current_4h_supertrend
                or self._current_supertrend
                or 0
            )
            if trail_st <= 0 or self._confirmed_direction is None:
                continue
            position_direction = (
                meta.direction if meta is not None else self._confirmed_direction
            )
            force_level = self._force_exit_level(
                int(position_direction), trail_st
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
                trail_st,
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
        pos_strike = self._position_strike(position, meta)
        spot = float(candle.get("close") or 0)
        low = float(candle.get("low") or spot or 0)
        high = float(candle.get("high") or spot or 0)
        if pos_strike is not None and self._spot_near_position_strike(
            spot=spot, strike=pos_strike, low=low, high=high
        ):
            return True
        direction = self._confirmed_direction
        supertrend = self._current_supertrend
        if direction is None or supertrend is None:
            return False
        position_direction = meta.direction if meta is not None else direction
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
        logger.info(
            "%s ENTRY filled reason=%s direction=%s symbol=%s sid=%s qty=%s ST=%.2f",
            self.name,
            entry_reason,
            direction,
            inst_sym,
            sid,
            int(qty or ORDER_QTY_LOTS),
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
            qty=int(qty or ORDER_QTY_LOTS),
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

