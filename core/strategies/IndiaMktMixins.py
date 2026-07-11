"""
India market mixins: shared logic for India options/LEAPS strategies.

Use in any strategy that needs:
- Option chain fetch, strike selection, option pricing (Dhan backtests: local expired-option CSVs via ``IndiaMktMixins.load_dhan_expired_option_chain_dataframe`` / ``DhanSource.get_expired_optionchain``)
- Order intent creation and instrument-to-intent mapping
- Hedge entry/exit and rollover

Example:
    class MyStrategy(IndiaMktMixins, BaseStrategy):
        name = "MY_STRATEGY"
        ...
"""

import uuid
import calendar
import logging
import math
import pandas as pd
from datetime import date, timedelta, datetime, timezone
from typing import Any, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# India Standard Time (UTC+5:30) for strategy time-of-day filters.
IST = timezone(timedelta(hours=5, minutes=30))
from run.config import RUN_MODE, RunMode, ORDER_QTY_LOTS
from core.utils.expiry_resolver import ExpiryResolver
from core.models.order_intent import OrderIntent
from core.strategies.deltaMktMixins import (
    _delta_source_from_ctx,
    delta_option_trading_symbol,
    ltp_from_strike_row_live,
)
from core.utils.dhan_expired_option_chain_files import (
    atm_label_from_spot_strike,
    load_expired_option_chain_from_files,
)
from core.utils.option_chain_snapshot_log import (
    load_option_chain_snapshot,
    log_option_chain_snapshot,
)


class IndiaMktMixins:
    """
    Reusable India market broker logic for option-selling strategies:
    - Option chain & strike selection
    - Order intents & hedge lifecycle
    - Rollover handling
    """

    # Subclasses should set: name, timeframe, api, expiryType, required_context
    name = ""
    timeframe = "60"
    api = "NSE"
    expiryType = "QUARTERLY"
    required_context = ["option_chain"]
    # If set (e.g. 120), ``_is_valid_time`` returns False when candle IST lags system IST
    # by more than this many seconds (late feed / backlog). None = log only, no skip.
    max_signal_lag_seconds: Optional[int] = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rolled_hedges = set()

    def _entry_order_qty(self, inst) -> int:
        """Lots to trade (Dhan broker sends quantity = lots × lot_size to the exchange)."""
        lots = int(getattr(self, "order_qty_lots", ORDER_QTY_LOTS) or 1)
        return max(1, lots)

    def _dhan_option_security_id(self) -> str:
        """Dhan rolling-option ``securityId`` (NIFTY=13, BANKNIFTY=25). Override on strategy class."""
        return str(getattr(self, "dhan_option_security_id", None) or "13")

    def _dhan_expiry_flag(self) -> str:
        """Dhan option chain / rolling-option expiry flag (``MONTH`` or ``WEEK``)."""
        return str(getattr(self, "dhan_expiry_flag", "MONTH") or "MONTH")

    @staticmethod
    def _order_qty_in_lots(inst, qty: Any) -> int:
        """Normalize qty to whole lots: values ≥ lot_size that divide evenly are treated as units."""
        lot = int(getattr(inst, "lot_size", 0) or 0) or 1
        try:
            q = int(qty)
        except (TypeError, ValueError):
            return 1
        if q <= 0:
            return 1
        if lot > 1 and q >= lot and q % lot == 0:
            return max(1, q // lot)
        return max(1, q)

    @staticmethod
    def order_qty_units(inst, qty_lots: int) -> int:
        """Exchange quantity (units) for a given lot count."""
        lot = int(getattr(inst, "lot_size", 0) or 0) or 1
        return max(1, int(qty_lots)) * lot

    def _normalize_order_qty(self, inst, qty) -> int:
        if qty is None:
            return self._entry_order_qty(inst)
        return self._order_qty_in_lots(inst, qty)

    # ==================================================
    # DHAN EXPIRED OPTION CSV (BACKTEST) — same layout as data/dhan_expired_option_chain download scripts
    # ==================================================
    @staticmethod
    def dhan_expired_option_atm_folder_label(
        spot: float, strike: float, strike_step: int = 50
    ) -> str:
        """ATM folder name (``ATM``, ``ATM+2``, ``ATM-3``, …) for on-disk Dhan CSVs."""
        return atm_label_from_spot_strike(spot, strike, strike_step=strike_step)

    @staticmethod
    def load_dhan_expired_option_chain_dataframe(
        *,
        symbol: str,
        calendar_expiry: Any,
        strikes: Any,
        option_type: str,
        spot_price: float,
        from_date: str,
        to_date: str,
        root: Any = None,
        strike_step: int = 50,
    ):
        """Load merged CALL or PUT history from local expired-option CSVs (optional custom ``root``)."""
        return load_expired_option_chain_from_files(
            symbol=symbol,
            calendar_expiry=calendar_expiry,
            strikes=strikes,
            option_type=option_type,
            spot_price=spot_price,
            from_date=from_date,
            to_date=to_date,
            root=root,
            strike_step=strike_step,
        )

    # ==================================================
    # TIME FILTER (override valid_times in strategy)
    # ==================================================
    def _is_valid_time(self, ts, valid_times=None, candle=None):
        """
        Match candle clock time in IST against ``valid_times``.

        ``valid_times`` may be a set of ``"HH:MM"`` strings (legacy) or
        ``datetime.time`` values (recommended). Naive timestamps are treated as UTC
        then converted to IST for comparison.

        Pass optional ``candle`` to log raw ``timestamp`` for lag root-cause (late feed vs slow processing).

        Logs ``Now IST``, ``Candle IST``, ``lag_sec``. If ``max_signal_lag_seconds`` is set (>0)
        and lag exceeds it, returns False (late signal / skip entry).
        """
        times = (
            valid_times
            if valid_times is not None
            else getattr(self, "valid_times", set())
        )

        if not times:
            return False

        ts = pd.Timestamp(ts)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        ts_utc = ts
        ts_ist = ts.tz_convert(IST)

        print("Now IST:", datetime.now(IST))
        print("Candle IST:", ts_ist, candle)
        if candle is not None:
            print("Raw timestamp:", candle.get("timestamp"))

        delay = (datetime.now(IST) - ts_ist.to_pydatetime()).total_seconds()
        lag_limit = getattr(self, "max_signal_lag_seconds", None)
        if lag_limit is not None and lag_limit > 0 and delay > lag_limit:
            print(f"⚠️ Late signal, skipping (lag {delay:.1f}s > {lag_limit}s)")
            return False

        sample = next(iter(times))
        if isinstance(sample, str):
            current_time = ts_ist.strftime("%H:%M")
            match = current_time in times
        else:
            current_time = ts_ist.time().replace(second=0, microsecond=0)
            match = current_time in times

        print(
            ">>>>match",
            match,
        )
        return match

    # ==================================================
    # STRUCTURE ID
    # ==================================================
    def build_structure_id(self, candle, regime):
        return f"{self.name}:{candle['symbol']}:{regime}"

    # ==================================================
    # ORDER INTENT FACTORY
    # ==================================================
    def create_order_intent(
        self,
        inst,
        side,
        qty,
        price,
        order_type,
        strategy,
        candle_ts,
        structure_id,
        tag,
        symbol,
        action,
        parent_intent_id=None,
        metadata_extras=None,
        trigger_price=None,
    ):
        resolved_qty = self._normalize_order_qty(inst, qty)
        return OrderIntent(
            intent_id=uuid.uuid4().hex,
            instrument=inst,
            side=side,
            qty=resolved_qty,
            price=price,
            order_type=order_type,
            strategy=strategy,
            structure_id=structure_id,
            trade_type="MARGIN",
            tag=tag,
            candle_ts=candle_ts,
            parent_intent_id=parent_intent_id,
            symbol=symbol,
            action=action,
            metadata_extras=metadata_extras,
            trigger_price=trigger_price,
        )

    # ==================================================
    # OPTION PRICING (BACKTEST SAFE)
    # ==================================================
    def _delta_expiry_ddmmyy(self, expiry) -> str:
        if expiry is None:
            return ""
        s = str(expiry).strip()
        if len(s) == 6 and s.isdigit():
            return s
        try:
            return pd.to_datetime(expiry).strftime("%d%m%y")
        except (TypeError, ValueError):
            return s

    @staticmethod
    def _is_option_instrument(strike, option_type) -> bool:
        """True when strike/option_type identify an options leg (not futures/index)."""
        if strike is None and option_type is None:
            return False
        if strike is None or option_type is None:
            return False
        ot = str(option_type).strip().upper()
        return ot in ("CE", "CALL", "PE", "PUT")

    def get_option_price_at_candle(
        self,
        candle,
        ctx,
        strike,
        option_type,
        expiry,
        trading_symbol: Optional[str] = None,
    ):
        if getattr(self, "api", None) == "DELTA":
            source = _delta_source_from_ctx(ctx)
            if source is None:
                return None
            sym = (trading_symbol or "").strip()
            if not sym:
                if not self._is_option_instrument(strike, option_type):
                    return None
                exp_code = self._delta_expiry_ddmmyy(expiry)
                sym = delta_option_trading_symbol(
                    None,
                    float(strike),
                    option_type or "CE",
                    exp_code,
                )
            try:
                t = source.get_ticker(sym)
            except Exception:
                return None
            if not t or not isinstance(t, dict):
                return None
            px = t.get("mark_price") or t.get("last_price") or t.get("close")
            if px is None:
                return None
            try:
                return float(px)
            except (TypeError, ValueError):
                return None

        if not self._is_option_instrument(strike, option_type):
            return None

        if str(getattr(self, "api", "") or "").upper() == "DHAN":
            cached_px = self._option_price_from_resolved_chain(
                candle, ctx, strike, option_type
            )
            if cached_px is not None and cached_px > 0:
                return cached_px

        params = {
            "exchange": ctx.exchange,
            "interval": self.timeframe,
            "expiry_code": expiry,
            "strike": [str(int(float(strike)))],
            "option_type": option_type,
            "instrument": "OPTIDX",
            "exchangeSegment": "NSE_FNO",
            "expiry_flag": self._dhan_expiry_flag(),
            "securityId": self._dhan_option_security_id(),
        }

        chain = ctx.option_chain_service.get_chain(api=self.api, ctx=ctx, params=params)
        df = self._coerce_backtest_option_chain_df(chain, option_type)
        if df is None:
            if isinstance(chain, dict):
                df = chain.get("chain")
            elif isinstance(chain, pd.DataFrame):
                df = chain
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return None

        # DHAN rolling option bars: multiple timestamps — keep the current candle row only.
        if "datetime" in df.columns and len(df) > 0:
            wall = self._chain_datetime_wall_clock_keys(df)
            wall_c = self._candle_wall_clock_key(candle)
            filt = df[wall == wall_c]
            if not filt.empty:
                df = filt
            elif len(df) > 1:
                return None

        otp = option_type.upper()
        if otp in ("PUT", "PE"):
            cols = ["PE LTP", "PUT LTP"]
        else:
            cols = ["CE LTP", "CALL LTP"]

        for col in cols:
            if col in df.columns:
                return float(df[col].iloc[0])

        prem_col = self._option_chain_premium_column(
            df, "CE" if otp in ("CE", "CALL") else "PE"
        )
        if prem_col is not None and prem_col in df.columns:
            try:
                return float(df.iloc[0][prem_col])
            except (TypeError, ValueError):
                return None

        return None

    # ==================================================
    # OPTION CHAIN & STRIKE SELECTION
    # ==================================================

    def get_last_friday(self, year: int, month: int) -> datetime:
        # Get last day of month
        last_day = calendar.monthrange(year, month)[1]
        last_date = datetime(year, month, last_day)

        # Move backward to Friday
        offset = (last_date.weekday() - 4) % 7  # Friday = 4
        return last_date - timedelta(days=offset)

    def getExpiry(self, ctx):
        ocs = ctx.option_chain_service
        if self.api == "NSE":
            ctx.expiry_list = ocs.get_expiries(
                api=self.api, ctx=ctx, instrument="FUTIDX"
            )
            expiry_date = ExpiryResolver.resolve(
                expiry_list=ctx.get_expiry_list(),
                trade_date=ctx.timestamp,
                api=self.api,
                expiry_pref=self.expiryType,
            )

        elif self.api == "DELTA":

            trade_dt = ctx.timestamp

            year = trade_dt.year
            month = trade_dt.month

            expiry_date = self.get_last_friday(year, month)

            # If trade date already past expiry → move to next month
            if trade_dt.date() > expiry_date.date():

                if month == 12:
                    year += 1
                    month = 1
                else:
                    month += 1

                expiry_date = self.get_last_friday(year, month)

        return expiry_date

    

    @staticmethod
    def _option_chain_premium_column(
        chain: pd.DataFrame, option_type_upper: str
    ) -> Optional[str]:
        """
        Premium / LTP column for backtest chains.

        - NSE-style wide tables: ``CE LTP`` / ``PE LTP`` style columns.
        - DHAN rolling option bars: use ``close`` as option price (no separate LTP column).
        """
        if chain is None or not isinstance(chain, pd.DataFrame) or chain.empty:
            return None

        opt = str(option_type_upper or "").upper().strip()
        if opt in ("CALL", "CE"):
            opt_tokens = ("CE", "CALL")
            side_prefix = "CE"
        elif opt in ("PUT", "PE"):
            opt_tokens = ("PE", "PUT")
            side_prefix = "PE"
        else:
            opt_tokens = (opt,) if opt else tuple()
            side_prefix = ""

        cols = list(chain.columns)
        upper_map = {c: str(c).upper().strip() for c in cols}

        # 1) Preferred explicit LTP columns for the side, e.g. CE LTP / PE LTP.
        for token in opt_tokens:
            target = f"{token} LTP"
            for c, cu in upper_map.items():
                if cu == target:
                    return c

        # 2) Any side-specific LTP-style column (robust to separators/order).
        for c, cu in upper_map.items():
            if "LTP" not in cu:
                continue
            if any(token in cu for token in opt_tokens):
                return c

        # 3) Side-specific close/last columns.
        for c, cu in upper_map.items():
            if any(token in cu for token in opt_tokens) and (
                "CLOSE" in cu or "LAST" in cu
            ):
                return c

        # 4) Side-specific bid/ask fallback (midpoint is built downstream).
        if side_prefix:
            bid_target = f"{side_prefix} BID"
            ask_target = f"{side_prefix} ASK"
            bid_col = next((c for c, cu in upper_map.items() if cu == bid_target), None)
            ask_col = next((c for c, cu in upper_map.items() if cu == ask_target), None)
            if bid_col and ask_col:
                return bid_col

            # Handle alternatives like "CE Bid Price", "PE Ask Price", etc.
            bid_like = next(
                (
                    c
                    for c, cu in upper_map.items()
                    if side_prefix in cu and "BID" in cu and ("QTY" not in cu)
                ),
                None,
            )
            ask_like = next(
                (
                    c
                    for c, cu in upper_map.items()
                    if side_prefix in cu and "ASK" in cu and ("QTY" not in cu)
                ),
                None,
            )
            if bid_like and ask_like:
                return bid_like

        # 5) Last resort for rolling backtest option bars.
        if "close" in chain.columns:
            return "close"
        return None

    @staticmethod
    def _option_chain_strike_column(chain: pd.DataFrame) -> Optional[str]:
        if "Strike Price" in chain.columns:
            return "Strike Price"
        if "strike" in chain.columns:
            return "strike"
        return None

    @staticmethod
    def _strike_on_strike_grid(val, step: int = 100) -> bool:
        """Keep only strikes on ``step`` grid (e.g. 500 → 22000, 22500; 100 → exclude 25250)."""
        try:
            s = int(step)
            if s <= 0:
                return True
            return int(round(float(val))) % s == 0
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _strike_on_hundred_point_grid(val) -> bool:
        return IndiaMktMixins._strike_on_strike_grid(val, 100)

    def _option_chain_strike_grid_step(self) -> int:
        return int(getattr(self, "option_chain_strike_step", 100) or 100)

    def _filter_option_chain_strike_grid(
        self, df: pd.DataFrame, strike_col: str
    ) -> pd.DataFrame:
        step = self._option_chain_strike_grid_step()
        if step <= 0 or strike_col not in df.columns:
            return df
        mask = df[strike_col].apply(lambda v: self._strike_on_strike_grid(v, step))
        return df.loc[mask]

    def _sort_rows_by_ideal_premium(
        self, row: pd.DataFrame, premium_col: str
    ) -> pd.DataFrame:
        ideal = getattr(self, "option_chain_ideal_premium", None)
        if ideal is None or not isinstance(row, pd.DataFrame) or len(row) <= 1:
            return row
        prem_num = pd.to_numeric(row[premium_col], errors="coerce")
        return (
            row.assign(_prem_dist=(prem_num - float(ideal)).abs())
            .sort_values("_prem_dist")
            .drop(columns=["_prem_dist"])
        )

    @staticmethod
    def _option_chain_delta_column(df: pd.DataFrame, option_type: str) -> Optional[str]:
        """Column name for option delta (|delta| used for short-option strike band)."""
        opt = "CE" if option_type.upper() in ("CE", "CALL") else "PE"
        for c in df.columns:
            cu = str(c).upper()
            if "DELTA" in cu and opt in cu:
                return c
        for c in df.columns:
            if "DELTA" in str(c).upper():
                return c
        return None

    @staticmethod
    def _abs_delta_in_band(
        row: Union[pd.Series, pd.DataFrame],
        delta_col: str,
        d_min: float,
        d_max: float,
    ) -> bool:
        try:
            if isinstance(row, pd.DataFrame):
                if row.empty:
                    return False
                v = row.iloc[0][delta_col]
            else:
                v = row[delta_col]
            ad = abs(float(v or 0))
            return float(d_min) <= ad <= float(d_max)
        except (TypeError, ValueError, KeyError):
            return False

    @staticmethod
    def _backtest_can_compute_bs_delta(chain: pd.DataFrame) -> bool:
        """Expired Dhan CSV rows often have iv + strike but no DELTA column — BS delta can be used."""
        if chain is None or chain.empty:
            return False
        cols = {str(c).lower() for c in chain.columns}
        return "strike" in cols and "iv" in cols

    @staticmethod
    def _ts_to_utc_naive(ts: Any) -> pd.Timestamp:
        """Align timestamps for subtraction: tz-aware → UTC, then strip tz (naive UTC wall time)."""
        t = pd.Timestamp(ts)
        if t.tzinfo is not None:
            t = t.tz_convert("UTC").tz_localize(None)
        return t

    @staticmethod
    def _expiry_calendar_to_utc_naive_close(exp_cal: Union[date, datetime, Any]) -> pd.Timestamp:
        """
        Option expiry instant: same **calendar** day at **15:30 IST** (NIFTY cash close convention),
        converted to naive UTC for consistent ``T`` vs bar timestamps.
        """
        if isinstance(exp_cal, datetime):
            d = exp_cal.date()
        elif isinstance(exp_cal, date):
            d = exp_cal
        else:
            d = pd.Timestamp(exp_cal).date()
        t = pd.Timestamp(datetime(d.year, d.month, d.day, 15, 30, 0))
        t = t.tz_localize("Asia/Kolkata").tz_convert("UTC").tz_localize(None)
        return t

    @staticmethod
    def _years_to_expiry_bs(bar_ts_utc_naive: pd.Timestamp, exp_cal_date: Union[date, datetime]) -> float:
        """
        Year fraction for Black–Scholes: (expiry @ 15:30 IST in UTC) − (bar time in UTC naive).
        """
        exp_ts = IndiaMktMixins._expiry_calendar_to_utc_naive_close(exp_cal_date)
        dt_sec = (exp_ts - bar_ts_utc_naive).total_seconds()
        if dt_sec <= 0:
            dt_sec = 60.0
        return max(dt_sec / (365.0 * 24 * 3600.0), 1e-10)

    def _append_computed_delta_to_chain_df(
        self,
        chain: pd.DataFrame,
        option_type: str,
        candle: dict,
        ctx: Any,
    ) -> pd.DataFrame:
        """
        Append BS ``DELTA_CE`` / ``DELTA_PE`` (signed) and ``abs_delta`` when the chain has
        ``strike`` + ``iv`` but no column matching ``_option_chain_delta_column`` — typical for
        expired Dhan CSV backtests.
        """
        if chain is None or chain.empty:
            return chain
        if self._option_chain_delta_column(chain, option_type) is not None:
            return chain
        if not self._backtest_can_compute_bs_delta(chain):
            return chain

        from core.library.dhan_tradehull import _iv_to_sigma, bs_option_delta

        opt_u = str(option_type).upper()
        kind = "pe" if opt_u in ("PE", "PUT") else "ce"
        leg_col = f"DELTA_{'PE' if kind == 'pe' else 'CE'}"
        r_annual = 0.065
        ts = candle.get("timestamp")
        td = self._ts_to_utc_naive(ts)
        trade_d = td.date()
        exp = getattr(ctx, "selected_expiry", None)
        if isinstance(exp, int):
            exp_d = ExpiryResolver.dhan_expiry_index_to_date(trade_d, exp)
        elif exp is not None and hasattr(exp, "year"):
            exp_d = pd.Timestamp(exp).date()
        else:
            exp_d = ExpiryResolver.dhan_expiry_index_to_date(trade_d, 0)

        _sf = candle.get("spot", candle.get("underlying_price"))
        spot_fallback = float(_sf) if _sf is not None and _sf != "" else 0.0
        if spot_fallback <= 0:
            spot_fallback = float(candle.get("close", 0) or 0)

        ts_col = "datetime" if "datetime" in chain.columns else None

        out = chain.copy()
        d_signed: List[float] = []
        d_abs: List[float] = []
        for _, r in out.iterrows():
            try:
                spot = (
                    float(r["spot"])
                    if "spot" in out.columns and pd.notna(r.get("spot"))
                    else spot_fallback
                )
                if pd.isna(r.get("strike")) or pd.isna(r.get("iv")) or spot <= 0:
                    d_signed.append(float("nan"))
                    d_abs.append(float("nan"))
                    continue
                K = float(r["strike"])
                sigma = _iv_to_sigma(r["iv"])
                if sigma <= 0 or (isinstance(sigma, float) and math.isnan(sigma)):
                    d_signed.append(float("nan"))
                    d_abs.append(float("nan"))
                    continue
                bar_ts = pd.Timestamp(r[ts_col]) if ts_col else td
                bar_ts = self._ts_to_utc_naive(bar_ts)
                T = self._years_to_expiry_bs(bar_ts, exp_d)
                d = bs_option_delta(spot, K, T, r_annual, sigma, kind)
                fv = float(d)
                d_signed.append(fv)
                d_abs.append(abs(fv))
            except (TypeError, ValueError):
                d_signed.append(float("nan"))
                d_abs.append(float("nan"))

        if len(d_signed) > 5:
            vals = [x for x in d_signed if not math.isnan(x)]
            if vals and (max(vals) - min(vals)) < 0.05:
                logger.warning(
                    "Delta nearly flat across strikes (range < 0.05) — check T / expiry vs bar "
                    "time (timezone or expiry calendar mismatch). exp_d=%s",
                    exp_d,
                )

        out[leg_col] = d_signed
        out["abs_delta"] = d_abs
        return out

    def fetch_option_chain(self, candle, ctx, option_type, expiry_pref=None):
        ocs = ctx.option_chain_service
        pref = str(expiry_pref or getattr(self, "expiryType", "") or "").strip().upper()

        if self.api == "NSE":
            ctx.expiry_list = ocs.get_expiries(
                api=self.api, ctx=ctx, instrument="FUTIDX"
            )

        rollover = getattr(self, "dhan_monthly_rollover_after_calendar_day", None)
        if pref != "MONTHLY":
            rollover = None
        weekly_wd = getattr(self, "weekly_expiry_weekday", None)
        days_before_exp = getattr(self, "dhan_monthly_rollover_days_before_expiry", None)
        monthly_exp_wd = getattr(self, "dhan_monthly_expiry_weekday", None)
        expiry_code = ExpiryResolver.resolve(
            expiry_list=ctx.get_expiry_list(),
            trade_date=ctx.timestamp,
            api=self.api,
            expiry_pref=pref,
            dhan_calendar_rollover_day=rollover,
            weekly_expiry_weekday=weekly_wd,
            days_before_expiry_rollover=days_before_exp,
            monthly_expiry_weekday=monthly_exp_wd,
        )
        spot = candle["close"]
        step = getattr(self, "otm_strike_step", 500)
        count = int(getattr(self, "otm_strike_count", 4))
        otm_strikes = ExpiryResolver.get_otm_strikes(
            self, spot=spot, option_type=option_type, step=step, count=count
        )
        ctx.selected_expiry = expiry_code
        ctx.otm_strikes = otm_strikes

        return otm_strikes

    def _expiry_from_option_chain(self, chain: Any = None) -> Optional[date]:
        """Calendar expiry from DHAN chain dict (same as snapshot ``_chain_expiry``)."""
        if chain is None:
            chain = getattr(self, "_last_option_chain", None)
        if not isinstance(chain, dict):
            return None
        exp = chain.get("expiry")
        if exp is None or (isinstance(exp, float) and pd.isna(exp)):
            return None
        try:
            return pd.Timestamp(exp).date()
        except (TypeError, ValueError):
            return None

    def _selected_expiry_calendar_date(self, ctx) -> Optional[date]:
        sel = getattr(ctx, "selected_expiry", None)
        if sel is None:
            return None
        if ExpiryResolver.is_calendar_expiry(sel):
            return ExpiryResolver.as_calendar_date(sel)
        try:
            trade_d = pd.Timestamp(getattr(ctx, "timestamp")).date()
            return ExpiryResolver.dhan_expiry_index_to_date(trade_d, sel)
        except (TypeError, ValueError):
            return None

    def _can_reuse_cached_option_chain(self, ctx, expiry_pref=None) -> bool:
        """Reuse DHAN chain cache only when expiry matches (never across expiry_pref overrides)."""
        if expiry_pref is not None:
            return False
        cached = getattr(self, "_last_option_chain", None)
        if cached is None:
            return False
        if isinstance(cached, dict):
            inner = cached.get("chain")
            if isinstance(inner, pd.DataFrame):
                if inner.empty:
                    return False
            elif not cached:
                return False
        elif isinstance(cached, pd.DataFrame):
            if cached.empty:
                return False
        else:
            return False
        cached_exp = self._expiry_from_option_chain(cached)
        want_exp = self._selected_expiry_calendar_date(ctx)
        return cached_exp is not None and want_exp is not None and cached_exp == want_exp

    @staticmethod
    def _coerce_backtest_option_chain_df(
        chain: Any, option_type: str
    ) -> Optional[pd.DataFrame]:
        """
        Normalize DHAN rolling-option / NSE backtest payloads to one side's DataFrame.

        Handles ``{"chain": df}``, bare DataFrames, and DHAN API ``{"CE": df, "PE": df}``.
        """
        if chain is None:
            return None
        ot = str(option_type or "").upper()
        want_ce = ot in ("CE", "CALL")
        want_pe = ot in ("PUT", "PE")
        if isinstance(chain, dict):
            inner = chain.get("chain")
            if isinstance(inner, pd.DataFrame) and not inner.empty:
                return inner
            if want_ce:
                ce = chain.get("CE") or chain.get("ce")
                if isinstance(ce, pd.DataFrame) and not ce.empty:
                    return ce
            if want_pe:
                pe = chain.get("PE") or chain.get("pe")
                if isinstance(pe, pd.DataFrame) and not pe.empty:
                    return pe
            return None
        if isinstance(chain, pd.DataFrame):
            return chain if not chain.empty else None
        return None

    def _option_chain_df(
        self, chain: Any, option_type: str = ""
    ) -> Optional[pd.DataFrame]:
        if chain is None:
            return None
        if isinstance(chain, dict):
            inner = chain.get("chain")
            if isinstance(inner, pd.DataFrame):
                return inner if not inner.empty else None
            if option_type:
                return self._coerce_backtest_option_chain_df(chain, option_type)
            return None
        if isinstance(chain, pd.DataFrame):
            return chain if not chain.empty else None
        return None

    @staticmethod
    def _candle_wall_clock_key(candle: dict) -> str:
        """IST wall-clock ``YYYY-MM-DD HH:MM`` for matching rolling option bars."""
        ts = pd.Timestamp(candle["timestamp"])
        if ts.tzinfo is None:
            ts = ts.tz_localize(IST)
        else:
            ts = ts.tz_convert(IST)
        return ts.strftime("%Y-%m-%d %H:%M")

    @staticmethod
    def _chain_datetime_wall_clock_keys(chain: pd.DataFrame) -> pd.Series:
        ts = pd.to_datetime(chain["datetime"])
        if getattr(ts.dt, "tz", None) is not None:
            ts = ts.dt.tz_convert(IST)
        return ts.dt.strftime("%Y-%m-%d %H:%M")

    def _snapshot_slot_from_candle(self, candle: dict) -> Tuple[str, str]:
        """IST wall-clock slot ``(YYYY-MM-DD, HH-MM)`` at bar close (for snapshot CSV lookup)."""
        ts = pd.Timestamp(candle["timestamp"])
        if ts.tzinfo is None:
            ts = ts.tz_localize(IST)
        else:
            ts = ts.tz_convert(IST)
        bar_minutes = int(self.timeframe) if str(self.timeframe).isdigit() else 60
        close_ts = ts + pd.Timedelta(minutes=bar_minutes)
        return close_ts.strftime("%Y-%m-%d"), close_ts.strftime("%H-%M")

    def _remember_option_chain_snapshot_slot(
        self, extra_snapshot_params: Optional[dict]
    ) -> None:
        if not isinstance(extra_snapshot_params, dict):
            return
        snap_date = extra_snapshot_params.get("snapshot_date")
        snap_time = extra_snapshot_params.get("snapshot_time")
        if snap_date and snap_time:
            self._last_option_chain_snapshot_slot = (str(snap_date), str(snap_time))
        target = extra_snapshot_params.get("snapshot_target")
        if target:
            self._last_option_chain_snapshot_target = str(target).strip().lower()

    def _resolve_option_chain_data(self, candle, ctx) -> Optional[dict]:
        """
        Option chain for the current bar: in-memory cache from main strike selection,
        else the LEAPS (or other) snapshot CSV for the same slot — no extra API call.
        """
        cached = getattr(self, "_last_option_chain", None)
        df = self._option_chain_df(cached, option_type="")
        if df is not None and not df.empty:
            return cached

        slot = getattr(self, "_last_option_chain_snapshot_slot", None)
        if not slot:
            slot = self._snapshot_slot_from_candle(candle)
        snap_date, snap_time = slot
        target = (
            getattr(self, "_last_option_chain_snapshot_target", None) or "leaps_rsi"
        )
        loaded = load_option_chain_snapshot(
            snapshot_date=snap_date,
            snapshot_time=snap_time,
            snapshot_target=str(target),
            ctx_symbol=str(getattr(ctx, "symbol", "") or ""),
            ctx_exchange=str(getattr(ctx, "exchange", "") or ""),
        )
        if loaded is not None:
            self._last_option_chain = loaded
        return loaded

    def _strike_row_from_chain(
        self, chain: Any, strike: Union[int, float], option_type: str
    ) -> Optional[pd.Series]:
        df = self._option_chain_df(chain, option_type=option_type)
        if df is None or df.empty:
            return None
        strike_col = self._option_chain_strike_column(df)
        if strike_col is None:
            return None
        try:
            strike_f = float(strike)
        except (TypeError, ValueError):
            return None
        sp = pd.to_numeric(df[strike_col], errors="coerce")
        rows = df[sp == strike_f]
        if rows.empty:
            return None
        return rows.iloc[0]

    def _execution_price_from_chain_row(
        self,
        row: Any,
        option_type: str,
        side: str,
    ) -> Optional[float]:
        """BUY → ask (then LTP); SELL → bid (then LTP) from a chain snapshot row."""
        if row is None:
            return None
        opt_u = str(option_type or "").upper()
        is_put = opt_u in ("PE", "PUT")
        buy = str(side or "").upper() == "BUY"
        if is_put:
            primary, secondary = "PE Ask", "PE LTP"
            if not buy:
                primary, secondary = "PE Bid", "PE LTP"
        else:
            primary, secondary = "CE Ask", "CE LTP"
            if not buy:
                primary, secondary = "CE Bid", "CE LTP"

        for col in (primary, secondary):
            try:
                if isinstance(row, pd.Series):
                    if col not in row.index:
                        continue
                    val = row[col]
                elif isinstance(row, dict):
                    if col not in row:
                        continue
                    val = row[col]
                else:
                    continue
                if val is None or (isinstance(val, float) and pd.isna(val)):
                    continue
                px = float(val.iloc[0] if isinstance(val, pd.Series) else val)
                if px > 0:
                    return px
            except (KeyError, TypeError, ValueError):
                continue
        return self._ltp_from_strike_row_backtest(row, opt_u) or None

    def _option_price_from_resolved_chain(
        self,
        candle,
        ctx,
        strike,
        option_type,
        *,
        side: Optional[str] = None,
    ) -> Optional[float]:
        chain = self._resolve_option_chain_data(candle, ctx)
        if chain is None:
            return None
        row = self._strike_row_from_chain(chain, strike, option_type)
        if row is None:
            return None
        px = self._execution_price_from_chain_row(row, option_type, side or "BUY")
        if px is not None and px > 0:
            return px
        return None

    def _find_strike_snapshot_params(self, candle, ctx, option_type):
        """Override in strategy to set params['snapshot']=True for chain CSV logging."""
        return {}

    def get_option_chain_snapshot(self, candle, ctx, option_type):
        otm_strikes = self.fetch_option_chain(candle, ctx, option_type)
        if not otm_strikes:
            if str(getattr(self, "name", "") or "") == "OptionBuildup":
                logger.warning(
                    "OptionBuildup snapshot: empty otm_strikes (sym=%s opt=%s)",
                    getattr(ctx, "symbol", "?"),
                    option_type,
                )
            return None
        params = {
            "exchange": ctx.exchange,
            "interval": self.timeframe,
            "expiry_code": ctx.selected_expiry,
            "instrument": "OPTIDX",
            "expiry_flag": self._dhan_expiry_flag(),
            "strikes": 60,
        }
        if self.api != "DHAN":
            strike_param = otm_strikes
            if strike_param and isinstance(strike_param[0], (int, float)):
                strike_param = [str(int(s)) for s in otm_strikes]
            params.update(
                {
                    "strike": strike_param,
                    "option_type": option_type,
                    "exchangeSegment": "NSE_FNO",
                    "securityId": self._dhan_option_security_id(),
                }
            )
        extra_snapshot_params = self._find_strike_snapshot_params(
            candle=candle, ctx=ctx, option_type=option_type
        )
        self._remember_option_chain_snapshot_slot(extra_snapshot_params)
        if isinstance(extra_snapshot_params, dict) and extra_snapshot_params:
            params.update(extra_snapshot_params)
        chain = ctx.option_chain_service.get_chain(api=self.api, ctx=ctx, params=params)
        self._last_option_chain = chain
        if bool(params.get("snapshot", False)):
            try:
                log_option_chain_snapshot(
                    chain,
                    ctx=ctx,
                    strategy_name=getattr(self, "name", "") or "",
                    api=self.api,
                    params=params,
                )
            except Exception as exc:
                logger.warning(
                    "log_option_chain_snapshot raised: %s", exc, exc_info=True
                )
        return chain

    def find_strike_in_premium_range(
        self,
        candle,
        ctx,
        option_type,
        min_prem=200,
        max_prem=400,
        delta_min=None,
        delta_max=None,
        expiry_pref=None,
    ):
        otm_strikes = self.fetch_option_chain(
            candle, ctx, option_type, expiry_pref=expiry_pref
        )

        if not otm_strikes:
            return None

        d_min = (
            delta_min
            if delta_min is not None
            else getattr(self, "delta_abs_min", None)
        )
        d_max = (
            delta_max
            if delta_max is not None
            else getattr(self, "delta_abs_max", None)
        )
        use_delta = d_min is not None and d_max is not None

        # When delta bounds are set and the chain has a delta column, strike selection uses
        # |delta| only — no min_prem/max_prem filtering or final premium check.

        extra_snapshot_params = self._find_strike_snapshot_params(
            candle=candle, ctx=ctx, option_type=option_type
        )
        self._remember_option_chain_snapshot_slot(extra_snapshot_params)
        snapshot_mode = isinstance(extra_snapshot_params, dict) and bool(
            extra_snapshot_params.get("snapshot")
        )

        strike_param = otm_strikes
        if strike_param and isinstance(strike_param[0], (int, float)):
            strike_param = [str(int(s)) for s in otm_strikes]

        if snapshot_mode and str(self.api or "").upper() == "DHAN":
            # Log ±60 strikes around ATM from Dhan (not the 4-strike OTM ladder).
            params = {
                "exchange": ctx.exchange,
                "interval": self.timeframe,
                "expiry_code": ctx.selected_expiry,
                "instrument": "OPTIDX",
                "expiry_flag": self._dhan_expiry_flag(),
                "strikes": 60,
            }
            params.update(extra_snapshot_params)
        else:
            params = {
                "exchange": ctx.exchange,
                "interval": self.timeframe,
                "expiry_code": ctx.selected_expiry,
                "strike": strike_param,
                "option_type": option_type,
                "instrument": "OPTIDX",
                "exchangeSegment": "NSE_FNO",
                "expiry_flag": self._dhan_expiry_flag(),
                "securityId": self._dhan_option_security_id(),
            }
            if isinstance(extra_snapshot_params, dict) and extra_snapshot_params:
                params.update(extra_snapshot_params)

        reuse_cached_chain = (
            not snapshot_mode
            and str(self.api or "").upper() == "DHAN"
            and self._can_reuse_cached_option_chain(ctx, expiry_pref)
        )

        if reuse_cached_chain:
            chain = getattr(self, "_last_option_chain", None)
        else:
            chain = ctx.option_chain_service.get_chain(
                api=self.api, ctx=ctx, params=params
            )
        if chain is None:
            chain = self._resolve_option_chain_data(candle, ctx)
        if bool(params.get("snapshot", False)):
            try:
                log_option_chain_snapshot(
                    chain,
                    ctx=ctx,
                    strategy_name=getattr(self, "name", "") or "",
                    api=self.api,
                    params=params,
                )
            except Exception as exc:
                logger.warning(
                    "log_option_chain_snapshot raised: %s", exc, exc_info=True
                )

        skip_premium_check = False
        if RUN_MODE == RunMode.LIVE or RUN_MODE == RunMode.PAPER:
            self._last_option_chain = chain
            if chain is None:
                print(">>no option chain data", ctx, params)
                return None
            if isinstance(chain, pd.DataFrame):
                if chain.empty:
                    print(">>no option chain data", ctx, params)
                    return None
            elif isinstance(chain, dict):
                if not chain:
                    print(">>no option chain data", ctx, params)
                    return None
            else:
                print(">>no option chain data", ctx, params)
                return None
            # DHAN live: get_chain returns {"symbol", "exchange", "chain": DataFrame, "atm_strike", "expiry"}.
            # Snapshot has CE/PE LTP + Strike Price (+ greeks); no datetime / close / strike columns.
            live_df = chain.get("chain") if isinstance(chain, dict) else chain
            if not isinstance(live_df, pd.DataFrame) or live_df.empty:
                return None

            option_type_upper = option_type.upper()
            premium_col = self._option_chain_premium_column(live_df, option_type_upper)
            strike_col = self._option_chain_strike_column(live_df)
            if premium_col is None or strike_col is None:
                return None

            live_df = self._filter_option_chain_strike_grid(live_df, strike_col)
            if live_df.empty:
                return None

            dcol_live = (
                self._option_chain_delta_column(live_df, option_type)
                if use_delta
                else None
            )
            delta_in_chain_live = (
                dcol_live is not None and dcol_live in live_df.columns
            )

            row = live_df
            if use_delta and delta_in_chain_live and dcol_live in row.columns:
                mask = row.apply(
                    lambda r: self._abs_delta_in_band(r, dcol_live, d_min, d_max),
                    axis=1,
                )
                filt = row[mask]
                if filt.empty:
                    return None
                if len(filt) > 1:
                    target_mid = (float(d_min) + float(d_max)) / 2.0
                    ad_series = filt.apply(
                        lambda r: abs(float(r[dcol_live]))
                        if pd.notna(r.get(dcol_live))
                        else float("nan"),
                        axis=1,
                    )
                    filt = (
                        filt.assign(_dd=(ad_series - target_mid).abs())
                        .sort_values("_dd")
                        .drop(columns=["_dd"])
                    )
                row = filt
                skip_premium_check = True
            else:
                prem_num = pd.to_numeric(live_df[premium_col], errors="coerce")
                # Bid/ask fallback: when selected premium_col is bid-like, use side midpoint.
                pu = str(premium_col).upper()
                if "BID" in pu and ("QTY" not in pu):
                    side_prefix = "CE" if option_type_upper in ("CE", "CALL") else "PE"
                    ask_col = None
                    for c in live_df.columns:
                        cu = str(c).upper()
                        if side_prefix in cu and "ASK" in cu and ("QTY" not in cu):
                            ask_col = c
                            break
                    if ask_col:
                        ask_num = pd.to_numeric(live_df[ask_col], errors="coerce")
                        prem_num = (prem_num + ask_num) / 2.0
                prem_num = prem_num.fillna(0)
                in_band = live_df[
                    prem_num.between(float(min_prem), float(max_prem), inclusive="both")
                ]
                row = in_band
                if row.empty:
                    row = live_df[prem_num > 0]
                    if not row.empty:
                        skip_premium_check = True
                if row.empty:
                    row = live_df
                    if not row.empty:
                        skip_premium_check = True

            if row.empty:
                return None

            row = self._sort_rows_by_ideal_premium(row, premium_col)
            r0 = row.iloc[0]
            if not use_delta or not delta_in_chain_live:
                try:
                    premium = float(prem_num.loc[r0.name])
                except (KeyError, TypeError, ValueError):
                    premium = float(
                        pd.to_numeric(r0[premium_col], errors="coerce") or 0.0
                    )
            else:
                premium = float(pd.to_numeric(r0[premium_col], errors="coerce") or 0.0)
            selected_strike = r0[strike_col]
        else:
            chain = self._coerce_backtest_option_chain_df(chain, option_type)
            self._last_option_chain = chain
            if chain is None:
                print(">>no option chain data", ctx, params)
                return None

            # Rolling option history (e.g. DHAN): multiple bars — keep the current candle row only.
            if "datetime" in chain.columns and len(chain) > 0:
                wall = self._chain_datetime_wall_clock_keys(chain)
                wall_c = self._candle_wall_clock_key(candle)
                filt = chain[wall == wall_c]
                if not filt.empty:
                    chain = filt
                elif len(chain) > 1:
                    return None

            # BS delta columns (DELTA_CE/DELTA_PE, abs_delta) when iv+strike present and no broker delta.
            chain = self._append_computed_delta_to_chain_df(chain, option_type, candle, ctx)

            option_type_upper = option_type.upper()
            premium_col = self._option_chain_premium_column(chain, option_type_upper)

            if premium_col is None:
                return None

            strike_col_bt = self._option_chain_strike_column(chain)
            if strike_col_bt:
                chain = self._filter_option_chain_strike_grid(chain, strike_col_bt)
                if chain.empty:
                    return None

            dcol_bt = self._option_chain_delta_column(chain, option_type)
            delta_in_chain = dcol_bt is not None and dcol_bt in chain.columns

            if use_delta and delta_in_chain:
                row = chain[
                    pd.to_numeric(chain[premium_col], errors="coerce").fillna(0) > 0
                ]
                if row.empty:
                    row = chain
                delta_ok = row[
                    row.apply(
                        lambda r: self._abs_delta_in_band(r, dcol_bt, d_min, d_max),
                        axis=1,
                    )
                ]
                if delta_ok.empty:
                    return None

                if len(delta_ok) > 1:
                    target_mid = (float(d_min) + float(d_max)) / 2.0
                    ad_series = delta_ok.apply(
                        lambda r: abs(float(r[dcol_bt])) if pd.notna(r.get(dcol_bt)) else float("nan"),
                        axis=1,
                    )
                    delta_ok = (
                        delta_ok.assign(_dd=(ad_series - target_mid).abs())
                        .sort_values("_dd")
                        .drop(columns=["_dd"])
                    )
                row = delta_ok
                skip_premium_check = True
            else:
                row = chain[chain[premium_col].between(min_prem, max_prem)]
                if row.empty:
                    row = chain[
                        pd.to_numeric(chain[premium_col], errors="coerce").fillna(0) > 0
                    ]
                if row.empty:
                    row = chain

                if use_delta and dcol_bt and dcol_bt in row.columns:
                    delta_ok = row[
                        row.apply(
                            lambda r: self._abs_delta_in_band(r, dcol_bt, d_min, d_max),
                            axis=1,
                        )
                    ]
                    if not delta_ok.empty:
                        row = delta_ok

            if row.empty:
                return None

            strike_col = self._option_chain_strike_column(row)
            if strike_col is None:
                return None
            row = self._sort_rows_by_ideal_premium(row, premium_col)
            r0 = row.iloc[0]
            selected_strike = r0[strike_col]
            premium = float(r0[premium_col])

        if skip_premium_check or (min_prem <= premium <= max_prem):
            if isinstance(row, pd.DataFrame) and not row.empty:
                out_row = row.iloc[0]
            else:
                out_row = row

            return selected_strike, premium, out_row

        return None

    def _ltp_from_strike_row_backtest(self, strike_row, option_type: str) -> float:
        """
        Premium for backtest fills. NSE wide tables use ``CE LTP`` / ``PE LTP``; DHAN rolling
        rows are often a Series with ``open``/``high``/``low``/``close`` (premium) only.
        """
        option_type_label = "PUT" if option_type == "PE" else "CALL"
        opt_u = str(option_type).upper()
        keys = (
            f"{option_type_label} LTP",
            f"{opt_u} LTP",
            "PE LTP",
            "CE LTP",
            "PUT LTP",
            "CALL LTP",
        )
        for k in keys:
            try:
                if isinstance(strike_row, pd.Series):
                    if k not in strike_row.index:
                        continue
                    lv = strike_row[k]
                elif isinstance(strike_row, dict):
                    if k not in strike_row:
                        continue
                    lv = strike_row[k]
                else:
                    continue
                if lv is None or (isinstance(lv, float) and pd.isna(lv)):
                    continue
                v = float(lv.iloc[0] if isinstance(lv, pd.Series) else lv)
                if v > 0:
                    return v
            except (KeyError, TypeError, ValueError):
                continue
        if isinstance(strike_row, pd.DataFrame):
            df = strike_row.iloc[[0]] if len(strike_row) else strike_row
        elif isinstance(strike_row, pd.Series):
            df = strike_row.to_frame().T
        else:
            df = pd.DataFrame([strike_row])
        if df is None or df.empty:
            return 0.0
        pc = self._option_chain_premium_column(df, opt_u)
        if pc and pc in df.columns:
            try:
                return float(df.iloc[0][pc])
            except (TypeError, ValueError):
                pass
        return 0.0

    def map_instrument_to_intent(
        self,
        inst,
        strike_row,
        strategy,
        side,
        structure_id,
        candle_ts,
        symbol,
        action,
        order_type="LIMIT",
        tag=None,
        parent_intent_id=None,
        metadata_extras=None,
        trigger_price=None,
    ):
        option_type = inst.option_type

        if RUN_MODE in (RunMode.LIVE, RunMode.PAPER):
            ltp = self._execution_price_from_chain_row(
                strike_row, option_type, side
            )
            if ltp is None or ltp <= 0:
                ltp = ltp_from_strike_row_live(
                    strike_row, option_type=option_type, side=side
                )
        else:
            ltp = self._ltp_from_strike_row_backtest(strike_row, option_type)
        if ltp is not None and float(ltp) <= 0:
            ltp = None

        assert inst.trading_symbol
        assert inst.custom_symbol

        return OrderIntent(
            intent_id=uuid.uuid4().hex,
            instrument=inst,
            side=side,
            qty=self._entry_order_qty(inst),
            price=ltp,
            order_type=order_type,
            strategy=strategy,
            structure_id=structure_id,
            trade_type="MARGIN",
            tag=tag,
            candle_ts=candle_ts,
            parent_intent_id=parent_intent_id,
            symbol=symbol,
            action=action,
            metadata_extras=metadata_extras,
            trigger_price=trigger_price,
        )

    def map_futures_instrument_to_intent(
        self,
        inst,
        strike_row,
        strategy,
        side,
        structure_id,
        candle_ts,
        symbol,
        action,
        tag=None,
        parent_intent_id=None,
    ):
        # Execution price: for Delta use best_bid (BUY) / best_ask (SELL) when available; else close
        api = getattr(self, "api", "NSE")
        if api == "DELTA":
            if side == "BUY" and strike_row.get("best_bid") is not None:
                ltp = float(strike_row["best_bid"])
            elif side == "SELL" and strike_row.get("best_ask") is not None:
                ltp = float(strike_row["best_ask"])
            else:
                ltp = float(strike_row["close"])
        else:
            ltp = float(strike_row["close"])

        return OrderIntent(
            intent_id=uuid.uuid4().hex,
            instrument=inst,
            side=side,
            qty=self._entry_order_qty(inst),
            price=ltp,
            order_type="LIMIT",
            strategy=strategy,
            structure_id=structure_id,
            trade_type="MARGIN",
            tag=tag,
            candle_ts=candle_ts,
            parent_intent_id=parent_intent_id,
            symbol=symbol,
            action=action,
            metadata_extras=None,
            trigger_price=None,
        )

    # ==================================================
    # HEDGE ENTRY / EXIT
    # ==================================================
    def resolve_hedge_expiry(self, trade_date, parent_expiry=None):
        """Hedge expiry: same calendar expiry as the main leg when known, else monthly rule."""
        if parent_expiry is not None:
            return pd.Timestamp(parent_expiry).date()
        return (
            ExpiryResolver.current_month_expiry(trade_date)
            if trade_date.day < 15
            else ExpiryResolver.next_month_expiry(trade_date)
        )

    def calculate_hedge_strike(self, sold_strike, option_type):
        step = 500
        sold = int(sold_strike)
        opt = str(option_type or "").upper()
        if opt in ("CE", "CALL"):
            target = sold * 1.02
        elif opt in ("PE", "PUT"):
            target = sold * 0.98
        else:
            target = sold * 1.02
        return int(round(target / step) * step)

    def resolve_hedge_entry_price(
        self,
        candle,
        ctx,
        hedge_strike,
        option_type,
        hedge_expiry,
    ) -> Optional[float]:
        """
        Hedge leg limit price. Override when hedge expiry differs from the main
        option chain (e.g. LEAPS sell + monthly hedge).
        """
        px = self._option_price_from_resolved_chain(
            candle,
            ctx,
            hedge_strike,
            option_type,
            side="BUY",
        )
        if px is not None and px > 0:
            return px
        if RUN_MODE == RunMode.BACKTEST:
            return self.get_option_price_at_candle(
                candle,
                ctx,
                hedge_strike,
                option_type,
                hedge_expiry,
            )
        return None

    def create_hedge_intent(self, parent_sell_intent, candle, ctx):
        trade_date = pd.to_datetime(candle["timestamp"]).date()
        parent_expiry = getattr(
            getattr(parent_sell_intent, "instrument", None), "expiry", None
        )
        hedge_expiry = self.resolve_hedge_expiry(trade_date, parent_expiry=parent_expiry)

        hedge_strike = self.calculate_hedge_strike(
            parent_sell_intent.instrument.strike,
            parent_sell_intent.instrument.option_type,
        )

        hedge_symbol = ExpiryResolver.build_option_symbol(
            candle["symbol"],
            hedge_expiry,
            hedge_strike,
            parent_sell_intent.instrument.option_type,
            include_year=True,
        )

        inst = ctx.instrument_store.intent_creation_details(
            hedge_symbol,
            ctx.exchange,
            hedge_expiry,
            parent_sell_intent.instrument.option_type,
            hedge_strike,
            prefer_monthly=bool(getattr(self, "hedge_prefer_monthly", True)),
        )
        if inst is None:
            return None

        resolved_exp = pd.to_datetime(inst.expiry, errors="coerce")
        if pd.isna(resolved_exp):
            logger.warning(
                "Hedge instrument has no expiry: %s (wanted %s)",
                getattr(inst, "trading_symbol", inst),
                hedge_expiry,
            )
            return None
        resolved_date = resolved_exp.date()
        if (
            resolved_date.year != hedge_expiry.year
            or resolved_date.month != hedge_expiry.month
        ):
            logger.warning(
                "Hedge expiry mismatch: resolved %s (%s) wanted %s",
                resolved_date,
                inst.trading_symbol,
                hedge_expiry,
            )
            return None

        hedge_price = self.resolve_hedge_entry_price(
            candle,
            ctx,
            hedge_strike,
            parent_sell_intent.instrument.option_type,
            hedge_expiry,
        )
        if hedge_price is None or hedge_price <= 0:
            hedge_price = 0

        return self.create_order_intent(
            inst=inst,
            side="BUY",
            qty=self._entry_order_qty(inst),
            price=hedge_price,
            order_type="LIMIT",
            strategy=self.name,
            candle_ts=candle["timestamp"],
            structure_id=parent_sell_intent.structure_id,
            tag="HEDGE",
            parent_intent_id=parent_sell_intent.intent_id,
            symbol=candle["symbol"],
            action="ENTRY",
        )

    def create_hedge_exit_intent(self, position, candle, ctx):
        hedge = ctx.position_store.get_hedge_for(position)
        if not hedge or hedge.net_qty == 0:
            return None

        price = (
            self.get_option_price_at_candle(
                candle,
                ctx,
                hedge.instrument.strike,
                hedge.instrument.option_type,
                hedge.instrument.expiry,
            )
            if RUN_MODE == RunMode.BACKTEST
            else None
        )

        if price is None:
            if RUN_MODE == RunMode.BACKTEST:
                print(
                    f"⚠️ No exit price for hedge {hedge.instrument.symbol} at {candle['timestamp']}"
                )
                return None
            # Live: engine resolves executable price from depth at enqueue time.
            price = 0

        qty_lots = self._order_qty_in_lots(hedge.instrument, abs(int(hedge.net_qty or 0)))
        return self.create_order_intent(
            inst=hedge.instrument,
            side="BUY" if hedge.net_qty < 0 else "SELL",
            qty=qty_lots,
            price=price,
            order_type="LIMIT",
            strategy=self.name,
            candle_ts=candle["timestamp"],
            structure_id=hedge.structure_id,
            tag="HEDGE_EXIT",
            symbol=candle["symbol"],
            action="EXIT",
        )

    # ==================================================
    # ROLLOVER
    # ==================================================
    def is_rollover_window(self, ts):
        return 15 <= ts.day <= 18

    def should_roll_hedge(self, hedge, ts):
        expiry = pd.to_datetime(hedge.instrument.expiry).date()
        current = pd.to_datetime(ts).date()
        if expiry <= current:
            return False

        from core.utils.session.session_manager import SessionManager

        exchange = (
            getattr(self, "session_exchange", None)
            or getattr(self, "market_exchange", None)
            or "INDEX"
        )
        target = SessionManager.hedge_rollover_target_date(
            current.year,
            current.month,
            rollover_day=18,
            exchange=str(exchange),
        )
        return current >= target

    def on_candle_rollover(self, open_positions, candle, ctx):
        ts = pd.to_datetime(candle["timestamp"])
        if not self.is_rollover_window(ts):
            return []

        intents = []

        for hedge in [p for p in open_positions if p.tag == "HEDGE" and p.net_qty != 0]:
            if not self.should_roll_hedge(hedge, ts):
                continue

            parent = next(
                (
                    p
                    for p in open_positions
                    if p.structure_id == hedge.structure_id and p.tag == "MAIN"
                ),
                None,
            )
            if not parent:
                continue

            roll_key = (hedge.structure_id, ts.date())

            if roll_key in self.rolled_hedges:
                continue

            hedge_exit = self.create_hedge_exit_intent(parent, candle, ctx)
            if hedge_exit:
                intents.append(hedge_exit)

            new_hedge = self.create_hedge_intent(parent, candle, ctx)
            if new_hedge:
                intents.append(new_hedge)

            self.rolled_hedges.add(roll_key)

        return intents

    def _hedge_roll_key(self, hedge):
        inst = hedge.instrument
        return (
            hedge.strategy,
            hedge.structure_id,
            inst.expiry,
            inst.strike,
            inst.option_type,
        )

    def on_structure_exit(self, structure_id, **kwargs):
        """Called when a structure is fully exited. Clears rollover state for that structure."""
        self.rolled_hedges = {k for k in self.rolled_hedges if k[0] != structure_id}

    # Anchor VWAP
    def _update_anchor_vwap(self, candle: Any):
        symbol = candle["symbol"]
        high = candle.get("high")
        low = candle.get("low")
        close = candle.get("close")
        volume = candle.get("volume")

        if None in (high, low, close, volume):
            return None

        typical_price = (high + low + close) / 3.0

        state = self._anchor_state.get(symbol)

        if state is None:
            # First listing candle initialization
            self._anchor_state[symbol] = {
                "cum_pv": typical_price * volume,
                "cum_vol": volume,
                "anchor_vwap": typical_price,
            }
        else:
            state["cum_pv"] += typical_price * volume
            state["cum_vol"] += volume
            state["anchor_vwap"] = state["cum_pv"] / state["cum_vol"]

        return self._anchor_state[symbol]["anchor_vwap"]

    # super trend (atr_period / mult come from strategy attributes if not passed)
    def _supertrend(
        self,
        candles: List[Any],
        atr_period: Optional[int] = None,
        mult: Optional[float] = None,
    ) -> Optional[Tuple[float, bool]]:
        """
        Returns (supertrend_line_value, is_green) for the last candle.
        is_green True = bullish → long only; False = bearish → short only.
        Strategies should set supertrend_atr_period and supertrend_multiplier.
        """
        atr_period = (
            atr_period
            if atr_period is not None
            else getattr(self, "supertrend_atr_period", 10)
        )
        mult = mult if mult is not None else getattr(self, "supertrend_multiplier", 3.0)
        if len(candles) < atr_period + 1:
            return None
        atr_list = self._atr(candles, atr_period)
        if atr_list is None:
            return None
        high = [c["high"] for c in candles]
        low = [c["low"] for c in candles]
        close = [c["close"] for c in candles]
        hl2 = [(high[i] + low[i]) / 2.0 for i in range(len(candles))]
        upper = [
            hl2[i] + mult * atr_list[i] if atr_list[i] is not None else None
            for i in range(len(candles))
        ]
        lower = [
            hl2[i] - mult * atr_list[i] if atr_list[i] is not None else None
            for i in range(len(candles))
        ]
        # Final bands (trailing); supertrend direction
        final_upper = [None] * len(candles)
        final_lower = [None] * len(candles)
        supertrend_green = [None] * len(candles)  # True = green (bullish)
        final_upper[atr_period - 1] = upper[atr_period - 1]
        final_lower[atr_period - 1] = lower[atr_period - 1]
        supertrend_green[atr_period - 1] = (
            close[atr_period - 1] > final_lower[atr_period - 1]
        )
        for i in range(atr_period, len(candles)):
            prev_upper = final_upper[i - 1]
            prev_lower = final_lower[i - 1]
            if prev_upper is not None and close[i] > prev_upper:
                supertrend_green[i] = True
                final_lower[i] = lower[i]
                final_upper[i] = None
            elif prev_lower is not None and close[i] < prev_lower:
                supertrend_green[i] = False
                final_upper[i] = upper[i]
                final_lower[i] = None
            else:
                supertrend_green[i] = supertrend_green[i - 1]
                if supertrend_green[i]:
                    # Trail lower band (take higher of new vs prev when bullish)
                    final_lower[i] = (
                        max(lower[i], final_lower[i - 1])
                        if final_lower[i - 1] is not None
                        else lower[i]
                    )
                    final_upper[i] = None
                else:
                    # Trail upper band (take lower of new vs prev when bearish)
                    final_upper[i] = (
                        min(upper[i], final_upper[i - 1])
                        if final_upper[i - 1] is not None
                        else upper[i]
                    )
                    final_lower[i] = None
        idx = len(candles) - 1
        line_value = final_lower[idx] if supertrend_green[idx] else final_upper[idx]
        if line_value is None:
            return None
        return (line_value, supertrend_green[idx])

    def _atr(self, candles: List[Any], period: int) -> Optional[List[float]]:
        """True Range then EMA-smoothed ATR. Returns ATR value per candle from index period onward."""
        if len(candles) < period + 1:
            return None
        tr_list = []
        for i, c in enumerate(candles):
            high, low, close = c["high"], c["low"], c["close"]
            if i == 0:
                tr = high - low
            else:
                prev_close = candles[i - 1]["close"]
                tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_list.append(tr)
        # EMA of TR for ATR; alpha = 1/period
        alpha = 1.0 / period
        atr_list = [None] * len(candles)
        atr_list[period - 1] = sum(tr_list[:period]) / period
        for i in range(period, len(candles)):
            atr_list[i] = alpha * tr_list[i] + (1 - alpha) * atr_list[i - 1]
        return atr_list
