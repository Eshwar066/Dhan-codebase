"""
Option-chain fetch, CSV snapshots, log replay, and OISnapshot extraction for OIPositionalBuy.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date, time as dt_time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import pandas as pd

from core.strategies.IndiaMktMixins import IST
from core.utils.expiry_resolver import ExpiryResolver
from core.utils.option_chain_snapshot_log import (
    log_option_chain_snapshot,
    snapshot_retry_should_attempt,
)

from .oi_types import (
    EOD_REVIEW_TIME,
    OISnapshot,
    PREMIUM_MAX,
    PREMIUM_MIN,
    PendingReferenceSnapshot,
    REFERENCE_SNAPSHOT_TIMES,
)

_LOGGER = logging.getLogger(__name__)


class OIOptionChainMixin:
    """Mixin: DHAN option chain I/O, reference snapshots, and strike/OI parsing."""

    def _init_option_chain_state(self) -> None:
        self._oi_snapshot_completed_slots: set[str] = set()
        self._oi_snapshot_pending: Dict[str, PendingReferenceSnapshot] = {}
        self._snapshot_retry_lock = threading.Lock()
        self._snapshot_retry_candle: Optional[dict] = None
        self._snapshot_retry_ctx: Any = None
        self._snapshot_retry_thread: Optional[threading.Thread] = None
        self._full_chain_cache: Any = None
        self._full_chain_cache_key: Optional[tuple] = None

    # --- Candle / IST time (used by chain + strategy) ---

    def _candle_timestamp_utc(self, candle: dict) -> pd.Timestamp:
        bt = candle.get("bucket_ts")
        if bt is not None:
            return pd.Timestamp(int(bt), unit="s", tz="UTC")
        ts = pd.Timestamp(candle["timestamp"])
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts.tz_convert("UTC")

    def _bar_tf_minutes(self) -> int:
        try:
            return max(1, int(str(self.timeframe).strip()))
        except (TypeError, ValueError):
            return 15

    def _ist_time(self, candle: dict) -> dt_time:
        close_ist = self._candle_timestamp_utc(candle).tz_convert(IST) + pd.Timedelta(
            minutes=self._bar_tf_minutes()
        )
        return close_ist.time().replace(second=0, microsecond=0)

    def _trade_date(self, candle: dict) -> date:
        return self._candle_timestamp_utc(candle).tz_convert(IST).date()

    def _candle_ts_ist(self, candle: dict) -> pd.Timestamp:
        return self._candle_timestamp_utc(candle).tz_convert(IST)

    def _candle_close_ts_ist(self, candle: dict) -> pd.Timestamp:
        return self._candle_ts_ist(candle) + pd.Timedelta(minutes=self._bar_tf_minutes())

    # --- Snapshot scheduling / persistence ---

    def _target_time_to_slot(self, target: dt_time) -> str:
        return target.strftime("%H-%M")

    def _snapshot_slot_key(self, symbol: str, trade_date: date, target: dt_time) -> str:
        return "|".join([str(symbol or ""), trade_date.isoformat(), self._target_time_to_slot(target)])

    def _snapshot_on_disk(self, trade_date: date, target: dt_time) -> bool:
        path = self._oi_log_csv_path(trade_date, self._target_time_to_slot(target))
        if path is None:
            return False
        try:
            return path.stat().st_size > 0
        except OSError:
            return False

    def _mark_snapshot_complete(self, slot_key: str, *, target: Optional[dt_time] = None) -> None:
        self._oi_snapshot_completed_slots.add(slot_key)
        self._oi_snapshot_pending.pop(slot_key, None)
        if target == EOD_REVIEW_TIME:
            _LOGGER.info(
                "oi_positional_buy 15:15 snapshot complete; deferred EOD exit review "
                "can proceed on next position check"
            )

    def _update_snapshot_retry_context(self, candle: dict, ctx: Any) -> None:
        with self._snapshot_retry_lock:
            self._snapshot_retry_candle = dict(candle)
            self._snapshot_retry_ctx = ctx

    def _ensure_snapshot_retry_worker(self) -> None:
        with self._snapshot_retry_lock:
            if not self._oi_snapshot_pending:
                return
            t = self._snapshot_retry_thread
            if t is not None and t.is_alive():
                return
            self._snapshot_retry_thread = threading.Thread(
                target=self._snapshot_retry_worker_loop,
                name="oi_pos_snapshot_retry",
                daemon=True,
            )
            self._snapshot_retry_thread.start()

    def _snapshot_retry_worker_loop(self) -> None:
        while True:
            time.sleep(1.0)
            with self._snapshot_retry_lock:
                if not self._oi_snapshot_pending:
                    self._snapshot_retry_thread = None
                    return
                candle = self._snapshot_retry_candle
                ctx = self._snapshot_retry_ctx
            if candle is None or ctx is None:
                continue
            now = time.time()
            for slot_key in list(self._oi_snapshot_pending.keys()):
                pending = self._oi_snapshot_pending.get(slot_key)
                if pending is None:
                    continue
                should, reason = snapshot_retry_should_attempt(
                    pending.last_attempt_unix,
                    pending.first_attempt_unix,
                    now_unix=now,
                )
                if not should:
                    if reason == "max_window_expired":
                        _LOGGER.error(
                            "oi_positional_buy snapshot retry expired sym=%s slot=%s "
                            "attempts=%s last_error=%s",
                            pending.symbol,
                            self._target_time_to_slot(pending.target),
                            pending.attempts,
                            pending.last_error,
                        )
                        self._oi_snapshot_pending.pop(slot_key, None)
                    continue
                _LOGGER.info(
                    "oi_positional_buy snapshot retry (wall-clock) sym=%s slot=%s "
                    "reason=%s attempt=%s",
                    pending.symbol,
                    self._target_time_to_slot(pending.target),
                    reason,
                    pending.attempts + 1,
                )
                pending.last_attempt_unix = now
                self._attempt_reference_snapshot(candle, ctx, pending.target)

    def _snapshot_params_for_target(
        self, candle: dict, ctx: Any, target: dt_time
    ) -> Dict[str, Any]:
        trade_date = self._trade_date(candle)
        return {
            "exchange": getattr(ctx, "exchange", None) or "INDEX",
            "interval": self.timeframe,
            "expiry_code": getattr(ctx, "selected_expiry", None),
            "instrument": "OPTIDX",
            "expiry_flag": "MONTH",
            "snapshot": True,
            "snapshot_date": trade_date.isoformat(),
            "snapshot_time": self._target_time_to_slot(target),
            "snapshot_target": "oi_positional_buy",
            "api": self.api,
        }

    def _invalidate_full_chain_cache(self) -> None:
        self._full_chain_cache = None
        self._full_chain_cache_key = None

    def _fetch_chain_for_snapshot_write(self, candle: dict, ctx: Any) -> Any:
        self._invalidate_full_chain_cache()
        strikes = self.fetch_option_chain(candle, ctx, "CE")
        if not strikes:
            return None
        params: Dict[str, Any] = {
            "exchange": ctx.exchange,
            "interval": self.timeframe,
            "expiry_code": ctx.selected_expiry,
            "instrument": "OPTIDX",
            "expiry_flag": "MONTH",
        }
        if self.api != "DHAN":
            strike_param = [str(int(float(s))) for s in strikes]
            params.update(
                {
                    "strike": strike_param,
                    "option_type": "CE",
                    "exchangeSegment": "NSE_FNO",
                    "securityId": "13",
                }
            )
        chain = ctx.option_chain_service.get_chain(api=self.api, ctx=ctx, params=params)
        if chain is not None:
            self._full_chain_cache = chain
            self._full_chain_cache_key = (
                str(candle.get("symbol") or ""),
                candle.get("bucket_ts"),
                self._trade_date(candle),
            )
        return chain

    def _attempt_reference_snapshot(
        self,
        candle: dict,
        ctx: Any,
        target: dt_time,
        *,
        params_extra: Optional[Dict[str, Any]] = None,
    ) -> bool:
        symbol = str(candle.get("symbol") or getattr(ctx, "symbol", "") or "")
        trade_date = self._trade_date(candle)
        slot = self._target_time_to_slot(target)
        slot_key = self._snapshot_slot_key(symbol, trade_date, target)
        eval_close = self._candle_close_ts_ist(candle).strftime("%Y-%m-%d %H:%M")

        params = self._snapshot_params_for_target(candle, ctx, target)
        if params_extra:
            params.update(params_extra)

        try:
            self._ensure_selected_expiry(candle, ctx)
            chain = self._fetch_chain_for_snapshot_write(candle, ctx)
            if chain is None:
                raise RuntimeError("option chain API returned None")
            if isinstance(chain, dict):
                inner = chain.get("chain")
                if inner is None or (hasattr(inner, "empty") and inner.empty):
                    raise RuntimeError("option chain DataFrame empty")
            elif hasattr(chain, "empty") and chain.empty:
                raise RuntimeError("option chain DataFrame empty")

            ok = log_option_chain_snapshot(
                chain,
                ctx=ctx,
                strategy_name=self.name,
                api=self.api,
                params=params,
            )
            if not ok:
                raise RuntimeError("log_option_chain_snapshot returned False")
        except Exception as exc:
            now = time.time()
            pending = self._oi_snapshot_pending.get(slot_key)
            if pending is None:
                pending = PendingReferenceSnapshot(
                    symbol=symbol,
                    trade_date=trade_date,
                    target=target,
                    first_attempt_unix=now,
                    last_attempt_unix=now,
                )
            else:
                pending.last_attempt_unix = now
            pending.attempts += 1
            pending.last_error = f"{type(exc).__name__}: {exc}"
            self._oi_snapshot_pending[slot_key] = pending
            self._update_snapshot_retry_context(candle, ctx)
            self._ensure_snapshot_retry_worker()
            _LOGGER.warning(
                "oi_positional_buy snapshot failed sym=%s slot=%s eval_close=%s "
                "attempt=%s err=%s (retry worker active)",
                symbol,
                slot,
                eval_close,
                pending.attempts,
                pending.last_error,
                exc_info=True,
            )
            return False

        self._mark_snapshot_complete(slot_key, target=target)
        _LOGGER.info(
            "oi_positional_buy snapshot written sym=%s slot=%s eval_close=%s",
            symbol,
            slot,
            eval_close,
        )
        return True

    def _write_reference_snapshot(
        self,
        candle: dict,
        ctx: Any,
        target: dt_time,
        *,
        params_extra: Optional[Dict[str, Any]] = None,
    ) -> bool:
        symbol = str(candle.get("symbol") or getattr(ctx, "symbol", "") or "")
        trade_date = self._trade_date(candle)
        slot = self._target_time_to_slot(target)
        slot_key = self._snapshot_slot_key(symbol, trade_date, target)

        if self._snapshot_on_disk(trade_date, target):
            self._mark_snapshot_complete(slot_key, target=target)
            _LOGGER.info(
                "oi_positional_buy snapshot already on disk sym=%s slot=%s path_exists",
                symbol,
                slot,
            )
            return True
        if slot_key in self._oi_snapshot_completed_slots:
            return True

        pending = self._oi_snapshot_pending.get(slot_key)
        if pending is not None:
            should, reason = snapshot_retry_should_attempt(
                pending.last_attempt_unix,
                pending.first_attempt_unix,
            )
            if not should:
                if reason == "max_window_expired":
                    _LOGGER.error(
                        "oi_positional_buy snapshot give up sym=%s slot=%s attempts=%s",
                        symbol,
                        slot,
                        pending.attempts,
                    )
                    self._oi_snapshot_pending.pop(slot_key, None)
                else:
                    _LOGGER.debug(
                        "oi_positional_buy snapshot throttle sym=%s slot=%s %s",
                        symbol,
                        slot,
                        reason,
                    )
                return False
            pending.last_attempt_unix = time.time()

        return self._attempt_reference_snapshot(
            candle, ctx, target, params_extra=params_extra
        )

    def _persist_reference_snapshot(self, candle: dict, ctx: Any, target: dt_time) -> bool:
        return self._write_reference_snapshot(candle, ctx, target)

    def _full_chain_cache_lookup(self, candle: dict) -> Optional[Any]:
        key = (str(candle.get("symbol") or ""), candle.get("bucket_ts"), self._trade_date(candle))
        if self._full_chain_cache_key == key and self._full_chain_cache is not None:
            return self._full_chain_cache
        return None

    def _ist_log_slot_for_candle(self, candle: dict) -> Optional[str]:
        t = self._ist_time(candle)
        if t in REFERENCE_SNAPSHOT_TIMES:
            return f"{t.hour:02d}-{t.minute:02d}"
        return None

    def _chain_from_oi_logs(self, candle: dict, ctx: Any, trade_date: date) -> Optional[Any]:
        slot = self._ist_log_slot_for_candle(candle)
        if slot is None:
            return None
        df = self._read_oi_log_chain_df(trade_date, slot)
        if df is None:
            return None
        return {
            "symbol": candle.get("symbol"),
            "exchange": getattr(ctx, "exchange", None) or "INDEX",
            "chain": df,
            "atm_strike": None,
            "expiry": self._read_oi_log_chain_expiry(trade_date, slot),
        }

    def _fetch_full_option_chain(self, candle: dict, ctx: Any) -> Any:
        cached = self._full_chain_cache_lookup(candle)
        if cached is not None:
            return cached

        trade_date = self._trade_date(candle)
        log_chain = self._chain_from_oi_logs(candle, ctx, trade_date)
        if log_chain is not None:
            self._ensure_selected_expiry(candle, ctx, log_chain)
            self._full_chain_cache = log_chain
            self._full_chain_cache_key = (
                str(candle.get("symbol") or ""),
                candle.get("bucket_ts"),
                trade_date,
            )
            return log_chain

        strikes = self.fetch_option_chain(candle, ctx, "CE")
        if not strikes:
            return None

        params: Dict[str, Any] = {
            "exchange": ctx.exchange,
            "interval": self.timeframe,
            "expiry_code": ctx.selected_expiry,
            "instrument": "OPTIDX",
            "expiry_flag": "MONTH",
        }
        if self.api != "DHAN":
            strike_param = [str(int(float(s))) for s in strikes]
            params.update(
                {
                    "strike": strike_param,
                    "option_type": "CE",
                    "exchangeSegment": "NSE_FNO",
                    "securityId": "13",
                }
            )

        chain = ctx.option_chain_service.get_chain(api=self.api, ctx=ctx, params=params)

        if chain is not None:
            self._full_chain_cache = chain
            self._full_chain_cache_key = (
                str(candle.get("symbol") or ""),
                candle.get("bucket_ts"),
                self._trade_date(candle),
            )
        return chain

    def _take_reference_snapshots(self, candle: dict, ctx: Any, target: dt_time) -> bool:
        return self._persist_reference_snapshot(candle, ctx, target)

    # --- Chain parsing ---

    def _oi_column(self, df: pd.DataFrame, option_type: str) -> Optional[str]:
        opt = option_type.upper()
        candidates = []
        for c in df.columns:
            cu = str(c).upper()
            if "OI" not in cu and "OPEN INTEREST" not in cu:
                continue
            if opt in cu:
                candidates.append(c)
        if candidates:
            return candidates[0]
        for c in df.columns:
            cu = str(c).upper()
            if "OI" in cu or "OPEN INTEREST" in cu:
                return c
        return None

    def _fetch_chain_df(self, candle: dict, ctx: Any, option_type: str) -> Optional[pd.DataFrame]:
        _ = option_type
        chain = self._fetch_full_option_chain(candle, ctx)
        return self._chain_df_from_response(chain, candle)

    def _chain_df_from_response(self, chain: Any, candle: dict) -> Optional[pd.DataFrame]:
        df = chain.get("chain") if isinstance(chain, dict) else chain
        if not isinstance(df, pd.DataFrame) or df.empty:
            return None
        if "datetime" in df.columns:
            wall = pd.to_datetime(df["datetime"]).dt.strftime("%Y-%m-%d %H:%M")
            ts_ist = self._candle_ts_ist(candle)
            wall_c = ts_ist.strftime("%Y-%m-%d %H:%M")
            filt = df[wall == wall_c]
            if not filt.empty:
                df = filt
        return df

    def _snapshots_from_df(
        self,
        df: pd.DataFrame,
        candle: dict,
        option_type: str,
        strikes_filter: Optional[Set[int]] = None,
        apply_premium_filter: bool = True,
    ) -> List[OISnapshot]:
        strike_col = self._option_chain_strike_column(df)
        prem_col = self._option_chain_premium_column(df, option_type)
        oi_col = self._oi_column(df, option_type)
        if not strike_col or not prem_col or not oi_col:
            return []
        out: List[OISnapshot] = []
        ts = self._candle_timestamp_utc(candle)
        for _, row in df.iterrows():
            try:
                strike = int(float(row[strike_col]))
                premium = float(row[prem_col])
                oi = float(row[oi_col])
            except (TypeError, ValueError):
                continue
            if strike % 100 != 0:
                continue
            if strikes_filter is not None and strike not in strikes_filter:
                continue
            if apply_premium_filter and not (PREMIUM_MIN <= premium <= PREMIUM_MAX):
                continue
            out.append(
                OISnapshot(
                    option_type=option_type,
                    strike=strike,
                    premium=premium,
                    oi=oi,
                    ts=ts,
                )
            )
        return out

    def _snapshots_from_chain(
        self,
        chain: Any,
        candle: dict,
        option_type: str,
        strikes_filter: Optional[Set[int]] = None,
        apply_premium_filter: bool = True,
    ) -> List[OISnapshot]:
        df = self._chain_df_from_response(chain, candle)
        if df is None:
            return []
        return self._snapshots_from_df(
            df, candle, option_type, strikes_filter, apply_premium_filter
        )

    def _extract_snapshots(
        self,
        candle: dict,
        ctx: Any,
        option_type: str,
        strikes_filter: Optional[Set[int]] = None,
        apply_premium_filter: bool = True,
    ) -> List[OISnapshot]:
        df = self._fetch_chain_df(candle, ctx, option_type)
        if df is None or df.empty:
            return []
        return self._snapshots_from_df(
            df, candle, option_type, strikes_filter, apply_premium_filter
        )

    def _snapshot_for_strike(
        self, candle: dict, ctx: Any, option_type: str, strike: int
    ) -> Optional[OISnapshot]:
        rows = self._extract_snapshots(
            candle,
            ctx,
            option_type,
            {int(strike)},
            apply_premium_filter=False,
        )
        return rows[0] if rows else None

    # --- Log files on disk ---

    def _oi_logs_day_dir(self, trade_date: date) -> Path:
        root = Path(__file__).resolve().parents[4]
        return root / "logs" / "OIPositionalBuy" / trade_date.isoformat()

    def _oi_log_csv_path(self, trade_date: date, slot: str) -> Optional[Path]:
        day_dir = self._oi_logs_day_dir(trade_date)
        if not day_dir.is_dir():
            return None
        token = slot.strip().replace(":", "-")
        candidates = [
            day_dir / f"{token}.csv",
            day_dir / f"{token.replace('-', '')}.csv",
        ]
        path = next((p for p in candidates if p.is_file()), None)
        if path is None:
            matches = sorted(day_dir.glob(f"*{token}*.csv"))
            path = matches[0] if matches else None
        return path if path is not None and path.is_file() else None

    def _read_oi_log_chain_expiry(self, trade_date: date, slot: str) -> Optional[Any]:
        path = self._oi_log_csv_path(trade_date, slot)
        if path is None:
            return None
        try:
            meta = pd.read_csv(path, usecols=lambda c: str(c) == "_chain_expiry")
        except (OSError, ValueError, pd.errors.EmptyDataError):
            return None
        if meta.empty or "_chain_expiry" not in meta.columns:
            return None
        val = meta["_chain_expiry"].iloc[0]
        return None if pd.isna(val) else val

    def _read_oi_log_chain_df(self, trade_date: date, slot: str) -> Optional[pd.DataFrame]:
        path = self._oi_log_csv_path(trade_date, slot)
        if path is None:
            return None
        try:
            df = pd.read_csv(path)
        except (OSError, ValueError, pd.errors.EmptyDataError):
            return None
        if df.empty:
            return None
        drop_cols = [c for c in df.columns if str(c).startswith("_")]
        if drop_cols:
            df = df.drop(columns=drop_cols, errors="ignore")
        if "Strike Price" in df.columns:
            df = df.drop_duplicates(subset=["Strike Price"], keep="last")
        return df if not df.empty else None

    def _dhan_monthly_expiry_index(self, trade_date: date) -> int:
        rollover = getattr(self, "dhan_monthly_rollover_after_calendar_day", 16)
        return ExpiryResolver._derive_monthly_series(
            trade_date, calendar_rollover_day=rollover
        )

    def _dhan_monthly_target_expiry_date(self, trade_date: date) -> date:
        """
        Resolve OI monthly target as a calendar date, not a moving DHAN list index:
        - day <= rollover: current month expiry
        - day > rollover: next month expiry
        If current expiry already passed, always move to next month.
        """
        rollover = int(getattr(self, "dhan_monthly_rollover_after_calendar_day", 15))
        current_exp = ExpiryResolver.current_month_expiry(trade_date)
        if trade_date > current_exp:
            return ExpiryResolver.next_month_expiry(trade_date)
        if trade_date.day > rollover:
            return ExpiryResolver.next_month_expiry(trade_date)
        return current_exp

    def _ensure_selected_expiry(self, candle: dict, ctx: Any, chain: Any = None) -> None:
        if getattr(ctx, "selected_expiry", None) is not None:
            return
        trade_date = self._trade_date(candle)
        cal_exp = chain.get("expiry") if isinstance(chain, dict) else None
        if cal_exp is None:
            slot = self._ist_log_slot_for_candle(candle)
            if slot:
                cal_exp = self._read_oi_log_chain_expiry(trade_date, slot)
        if cal_exp is not None:
            ctx.selected_expiry = pd.Timestamp(cal_exp).date()
            return
        ctx.selected_expiry = self._dhan_monthly_target_expiry_date(trade_date)
        self.fetch_option_chain(candle, ctx, "CE")
