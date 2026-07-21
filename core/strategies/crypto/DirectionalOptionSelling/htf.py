"""Higher-timeframe SuperTrend helpers for DirectionalOptionSelling."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from core.strategies.deltaMktMixins import _delta_source_from_ctx
from core.utils import indicator_history as ind_hist

from .constants import HTF_LOOKBACK_DAYS, HTF_TIMEFRAMES

logger = logging.getLogger(__name__)


class DosHtfMixin:
    """1D/4H SuperTrend fetch, cache, stamp, and entry alignment filters."""

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

    def _latest_closed_st_from_indicator_history(
        self, timeframe: str, as_of_utc: pd.Timestamp
    ) -> Optional[Tuple[int, float, pd.Timestamp]]:
        """
        Last fully closed SuperTrend from live ``indicator_history.jsonl``.

        Preferred over REST for trailing: live_append already has the new 4H ST
        while get_intraday can lag and leave MAIN_SL stuck at entry ST.
        """
        bar_sec = self._tf_bar_seconds(timeframe)
        if bar_sec <= 0:
            return None
        as_of = pd.Timestamp(as_of_utc)
        if as_of.tzinfo is None:
            as_of = as_of.tz_localize("UTC")
        else:
            as_of = as_of.tz_convert("UTC")
        try:
            rows = ind_hist.load_indicator_history_rows(
                "BTCUSD", timeframe, max_rows=80
            )
        except Exception as exc:
            logger.debug(
                "%s indicator history read failed tf=%s: %s",
                self.name,
                timeframe,
                exc,
            )
            return None
        best: Optional[Tuple[int, float, pd.Timestamp]] = None
        for row in rows or []:
            ts = row.get("timestamp")
            if ts is None:
                continue
            bar_open = pd.Timestamp(ts)
            if bar_open.tzinfo is None:
                bar_open = bar_open.tz_localize("UTC")
            else:
                bar_open = bar_open.tz_convert("UTC")
            close_at = bar_open + pd.Timedelta(seconds=bar_sec)
            if close_at > as_of:
                continue
            ind = row.get("indicators") if isinstance(row.get("indicators"), dict) else {}
            direction = self._normal_direction(
                ind.get("supertrend_direction")
                if ind
                else row.get("supertrend_direction")
            )
            try:
                st = float(
                    (ind.get("supertrend") if ind else None)
                    or row.get("supertrend")
                    or 0
                )
            except (TypeError, ValueError):
                continue
            if direction is None or pd.isna(st) or st <= 0:
                continue
            best = (int(direction), float(st), bar_open)
        return best

    def _htf_supertrend(
        self, ctx: Any, timeframe: str, candle: dict
    ) -> Optional[Tuple[int, float, pd.Timestamp]]:
        """Cached last-closed SuperTrend for ``timeframe`` (4h / 1d)."""
        as_of = self._as_of_utc(candle)
        cached = self._htf_st_cache.get(timeframe)
        bar_sec = self._tf_bar_seconds(timeframe)
        # Prefer live indicator history (updated on 4h/1d close) over REST.
        hist = self._latest_closed_st_from_indicator_history(timeframe, as_of)
        if hist is not None:
            if cached is None or hist[2] > cached[2] or abs(hist[1] - cached[1]) > 1e-6:
                self._htf_st_cache[timeframe] = hist
            return self._htf_st_cache[timeframe]
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
