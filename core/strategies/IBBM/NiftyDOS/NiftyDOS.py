"""
NIFTY-DOS (Supertrend + MA9 + ADX Directional Option Selling)

- Timeframe: 30m, closed-bar evaluation
- On day of expiry: new trade triggered, shift to next expiry
- Supertrend(16, 2) + SMA9 + ADX(14)
- Supertrend Green (bullish) + MA9 bullish + ADX > 25 → SELL OTM PUT (premium 80-105)
- Supertrend Red (bearish) + MA9 bearish + ADX > 25 → SELL OTM CALL (premium 80-105)
- Hedge: 500 points OTM from MAIN on same weekly expiry
- Rollover: 1 trading day before weekly expiry
- No new entries on NSE holidays, event_no_trade_dates, or weekly expiry day


Exit Rules (5min timeframe check) - based on STRUCTURE CAPITAL (margin for hedged position):
- Structure = MAIN (short option) + HEDGE (long option) with same structure_id
- Capital deployed = margin_per_lot * qty (broker margin for hedged structure, e.g., ₹50,000/lot)
- Combined P&L = MAIN P&L + HEDGE P&L (net structure P&L)
- CALL: SL 3.5% of capital, TP 3.7% of capital
- PUT: SL 3.5% of capital, TP 3.7% of capital

Reentry on SL: Nifty price >= MA9 for bullish ST and nifty price <= MA9 for bearish ST with ADX > 25 and check candle (if in favor of trend then only enter)
Reentry on TP: Nifty price >= MA9 for bullish ST and nifty price <= MA9 for bearish ST

After 3pm: if |profit or loss| >= 3% of capital deployed exit the trade, re-entry if ADX > 25 else reentry on next day 9:45
No Entry at 3:15PM for both CE and PE when ADX < 25
Check at 9:15: if price is opposite to signal, exit trade and enter in 30min candle close
"""

from __future__ import annotations

import logging
from datetime import date, time, timedelta
from pathlib import Path
from typing import Any, List, Optional, Set

import numpy as np
import pandas as pd

from run.config import RUN_MODE, RunMode
from core.strategies.base import BaseStrategy
from core.strategies.IndiaMktMixins import IST, IndiaMktMixins
from core.strategies.indicator_helpers import (
    add_adx,
    add_sma,
    add_supertrend,
    default_persisted_keys_for_sma,
)
from core.utils.expiry_resolver import ExpiryResolver
from core.utils.option_chain_snapshot_log import log_option_chain_snapshot
from core.utils.session.session_manager import SessionManager

logger = logging.getLogger(__name__)


class NiftyDOS(IndiaMktMixins, BaseStrategy):
    """NIFTY Supertrend + MA9 + ADX directional option selling with TP/SL management."""

    name = "NiftyDOS"
    underlying_symbols = ["NIFTY"]
    timeframe = "30"
    required_context = ["option_chain"]
    api = "DHAN"
    expiryType = "WEEKLY"
    dhan_expiry_flag = "WEEK"
    weekly_expiry_weekday = 1  # Nifty weekly = Tuesday
    option_chain_strike_step = 50
    otm_strike_step = 50
    otm_strike_count = 8
    option_chain_ideal_premium = 92
    option_chain_interval = "5"  # TP/SL check on 5min
    supertrend_atr_period = 16
    supertrend_multiplier = 2.0
    ma_period = 9
    adx_period = 14
    premium_min = 80
    premium_max = 105
    hedge_distance_points = 500
    hedge_rollover_days_before_expiry = 1
    hedge_prefer_monthly = False

    # TP/SL parameters (percentage of capital deployed for the hedged structure)
    call_sl_pct = 3.5
    call_tp_pct = 3.7
    put_sl_pct = 3.5
    put_tp_pct = 3.7

    # Capital per lot for the hedged structure (approximate SPAN margin for MAIN + HEDGE)
    # This should be configured based on broker's margin requirement for the hedged position
    # Example: If broker requires ₹50,000 margin per lot for the hedged structure, set to 50000
    margin_per_lot = 50000  # Approximate margin required per lot for hedged position

    # Reentry parameters
    reentry_adx_threshold = 25
    eod_exit_pct = 3.0  # 3% after 3pm
    eod_exit_time = time(15, 15)  # 3:15 PM
    no_entry_time = time(15, 15)  # 3:15 PM
    morning_check_time = time(9, 15)  # 9:15 AM

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._snapshot_logged_slots: set[str] = set()
        self._hedge_snapshot_logged_slots: set[str] = set()
        self._entry_signaled_keys: set[str] = set()
        self._evaluated_signal_keys: set[str] = set()
        self._event_no_trade_dates: Set[date] = set()
        self._snapshot_expiry_pref: Optional[str] = None
        self._force_hedge_expiry: Optional[date] = None
        self.rolled_hedges: Set[tuple] = set()
        # Structure tracking: store both MAIN and HEDGE entry prices
        self._structure_main_entry_price: dict[str, float] = {}  # structure_id -> main entry premium
        self._structure_hedge_entry_price: dict[str, float] = {}  # structure_id -> hedge entry premium
        self._structure_type: dict[str, str] = {}  # structure_id -> "CALL" or "PUT"
        # Track SL/TP hit for reentry timing
        self._sl_hit_structure: dict[str, str] = {}  # structure_id -> option_type (for next candle reentry)
        self._tp_hit_pending: dict[str, str] = {}  # structure_id -> option_type (for immediate reentry)
        self._prev_st_signal: Optional[str] = None  # track previous supertrend for flip detection
        self._load_config_from_yaml()

    def _load_config_from_yaml(self) -> None:
        yaml_path = Path(__file__).resolve().parent / "strategy.yaml"
        try:
            import yaml
        except ImportError:
            return
        if not yaml_path.is_file():
            return
        try:
            raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            logger.warning("NiftyDOS: could not read strategy.yaml: %s", exc)
            return

        params = raw.get("params") or {}
        if "supertrend_atr_period" in params:
            self.supertrend_atr_period = int(params["supertrend_atr_period"])
        if "supertrend_multiplier" in params:
            self.supertrend_multiplier = float(params["supertrend_multiplier"])
        if "ma_period" in params:
            self.ma_period = int(params["ma_period"])
        if "adx_period" in params:
            self.adx_period = int(params["adx_period"])
        if "premium_min" in params:
            self.premium_min = float(params["premium_min"])
        if "premium_max" in params:
            self.premium_max = float(params["premium_max"])
        if "hedge_distance_points" in params:
            self.hedge_distance_points = int(params["hedge_distance_points"])
        if "weekly_expiry_weekday" in params:
            self.weekly_expiry_weekday = int(params["weekly_expiry_weekday"]) % 7
        if "hedge_rollover_days_before_expiry" in params:
            self.hedge_rollover_days_before_expiry = int(params["hedge_rollover_days_before_expiry"])

        # TP/SL parameters
        if "call_sl_pct" in params:
            self.call_sl_pct = float(params["call_sl_pct"])
        if "call_tp_pct" in params:
            self.call_tp_pct = float(params["call_tp_pct"])
        if "put_sl_pct" in params:
            self.put_sl_pct = float(params["put_sl_pct"])
        if "put_tp_pct" in params:
            self.put_tp_pct = float(params["put_tp_pct"])

        # Capital per lot for hedged structure
        if "margin_per_lot" in params:
            self.margin_per_lot = float(params["margin_per_lot"])

        # Reentry parameters
        if "reentry_adx_threshold" in params:
            self.reentry_adx_threshold = int(params["reentry_adx_threshold"])
        if "eod_exit_pct" in params:
            self.eod_exit_pct = float(params["eod_exit_pct"])

        events = raw.get("event_no_trade_dates") or []
        parsed: Set[date] = set()
        for item in events:
            try:
                parsed.add(pd.Timestamp(item).date())
            except Exception:
                logger.warning("NiftyDOS: bad event_no_trade date=%s", item)
        self._event_no_trade_dates = parsed

    def get_warmup_period(self):
        return max(50, int(self.supertrend_atr_period) * 5, int(self.adx_period) * 3)

    def prepare_indicators(self, df):
        # Supertrend
        df = add_supertrend(
            df,
            atr_period=int(self.supertrend_atr_period),
            multiplier=float(self.supertrend_multiplier),
        )
        # SMA
        period = int(getattr(self, "ma_period", 9) or 9)
        ma_col = f"sma{period}"
        prev_ma_col = f"prev_sma{period}"
        df = add_sma(df, period=period, column=ma_col)
        if ma_col in df.columns:
            df[prev_ma_col] = df[ma_col].shift(1)
        # ADX
        df = add_adx(df, period=int(self.adx_period))
        if "close" in df.columns:
            df["prev_close"] = df["close"].shift(1)
        return df

    def persisted_indicator_keys(self):
        period = int(getattr(self, "ma_period", 9) or 9)
        st_keys = [
            f"supertrend_{int(self.supertrend_atr_period)}_{float(self.supertrend_multiplier)}",
            f"supertrend_dir_{int(self.supertrend_atr_period)}_{float(self.supertrend_multiplier)}",
        ]
        return (
            default_persisted_keys_for_sma(period, column=f"sma{period}")
            + [f"prev_sma{period}", "prev_close"]
            + st_keys
            + [f"adx_{int(self.adx_period)}", f"di_plus_{int(self.adx_period)}", f"di_minus_{int(self.adx_period)}"]
        )

    def shared_indicator_signature(self) -> str:
        return (
            f"dos_st{int(self.supertrend_atr_period)}_{float(self.supertrend_multiplier)}_"
            f"ma{int(self.ma_period)}_adx{int(self.adx_period)}"
        )

    # ---------- Expiry / hedge ----------

    def resolve_hedge_expiry(self, trade_date: date, parent_expiry=None):
        """Weekly hedge: same expiry as MAIN when known, else current weekly."""
        forced = getattr(self, "_force_hedge_expiry", None)
        if forced is not None:
            return pd.Timestamp(forced).date()
        if parent_expiry is not None:
            return pd.Timestamp(parent_expiry).date()
        wd = int(getattr(self, "weekly_expiry_weekday", 1) or 1) % 7
        return ExpiryResolver.current_weekly_expiry(trade_date, weekday=wd)

    def calculate_hedge_strike(self, sold_strike, option_type):
        """Hedge is fixed points OTM from MAIN (default 500)."""
        step = int(getattr(self, "option_chain_strike_step", 50) or 50)
        sold = int(sold_strike)
        gap = int(getattr(self, "hedge_distance_points", 500) or 500)
        opt = str(option_type or "").upper()
        if opt in ("CE", "CALL"):
            target = sold + gap
        elif opt in ("PE", "PUT"):
            target = sold - gap
        else:
            target = sold + gap
        return int(round(target / step) * step)

    def fetch_hedge_option_chain(
        self,
        candle: dict,
        ctx,
        hedge_expiry: date,
        option_type: str,
    ) -> Optional[Any]:
        ts_ist = self._candle_close_ts_ist(candle)
        slot_key = "|".join(
            [
                str(getattr(ctx, "symbol", "") or ""),
                str(option_type or ""),
                hedge_expiry.isoformat(),
                ts_ist.strftime("%Y-%m-%d"),
                ts_ist.strftime("%H-%M"),
            ]
        )
        extra: dict = {}
        if slot_key not in self._hedge_snapshot_logged_slots:
            self._hedge_snapshot_logged_slots.add(slot_key)
            extra = {
                "snapshot": True,
                "snapshot_date": ts_ist.strftime("%Y-%m-%d"),
                "snapshot_time": ts_ist.strftime("%H-%M"),
                "snapshot_target": "nifty_dos_hedge",
            }
        params = {
            "exchange": ctx.exchange,
            "interval": self._option_data_interval(),
            "expiry_code": hedge_expiry,
            "instrument": "OPTIDX",
            "expiry_flag": "WEEK",
            "strikes": 60,
            "expiry_match_same_month": True,
        }
        params.update(extra)

        saved_expiry = getattr(ctx, "selected_expiry", None)
        try:
            ctx.selected_expiry = hedge_expiry
            chain = ctx.option_chain_service.get_chain(api=self.api, ctx=ctx, params=params)
        finally:
            ctx.selected_expiry = saved_expiry

        if bool(params.get("snapshot", False)) and chain is not None:
            try:
                log_option_chain_snapshot(chain, ctx=ctx, strategy_name=self.name, api=self.api, params=params)
            except Exception as exc:
                logger.warning("log_option_chain_snapshot (hedge) raised: %s", exc, exc_info=True)
        return chain

    def resolve_hedge_entry_price(
        self,
        candle,
        ctx,
        hedge_strike,
        option_type,
        hedge_expiry,
    ) -> Optional[float]:
        if RUN_MODE == RunMode.BACKTEST:
            px = self.get_option_price_at_candle(candle, ctx, hedge_strike, option_type, hedge_expiry)
            if px is not None and px > 0:
                return px

        chain = self.fetch_hedge_option_chain(candle, ctx, hedge_expiry, option_type)
        if chain is None:
            return None
        row = self._strike_row_from_chain(chain, hedge_strike, option_type)
        px = self._execution_price_from_chain_row(row, option_type, "BUY")
        return px if px is not None and px > 0 else None

    # ---------- Time / event gates ----------

    def _candle_close_ts_ist(self, candle: dict) -> pd.Timestamp:
        ts = pd.Timestamp(candle["timestamp"])
        if ts.tzinfo is None:
            ts = ts.tz_localize(IST)
        else:
            ts = ts.tz_convert(IST)
        bar_minutes = int(self.timeframe) if str(self.timeframe).isdigit() else 30
        return ts + pd.Timedelta(minutes=bar_minutes)

    def _bar_open_key(self, candle: dict) -> str:
        bucket = candle.get("bucket_ts")
        if bucket is not None:
            try:
                ts = pd.to_datetime(int(float(bucket)), unit="s", utc=True).tz_convert(IST)
                return ts.strftime("%Y-%m-%d %H:%M")
            except (TypeError, ValueError):
                pass
        ts = pd.Timestamp(candle.get("timestamp"))
        if ts.tzinfo is None:
            ts = ts.tz_localize(IST)
        else:
            ts = ts.tz_convert(IST)
        return ts.strftime("%Y-%m-%d %H:%M")

    def _trade_date(self, candle: dict) -> date:
        ts = pd.Timestamp(candle.get("timestamp"))
        if ts.tzinfo is None:
            ts = ts.tz_localize(IST)
        else:
            ts = ts.tz_convert(IST)
        return ts.date()

    def _candle_time_ist(self, candle: dict) -> time:
        ts = pd.Timestamp(candle.get("timestamp"))
        if ts.tzinfo is None:
            ts = ts.tz_localize(IST)
        else:
            ts = ts.tz_convert(IST)
        return ts.time()

    def _is_event_no_trade_day(self, trade_date: date) -> bool:
        if trade_date in self._event_no_trade_dates:
            return True
        try:
            return bool(SessionManager.is_holiday(trade_date, "INDEX"))
        except Exception:
            return False

    def _is_weekly_expiry_day(self, trade_date: date) -> bool:
        wd = int(getattr(self, "weekly_expiry_weekday", 1) or 1) % 7
        expiry = ExpiryResolver.current_weekly_expiry(trade_date, weekday=wd)
        return trade_date == expiry

    def _prior_trading_day(self, day: date) -> date:
        d = day - timedelta(days=1)
        for _ in range(14):
            if SessionManager.is_trading_day(d, "INDEX"):
                return d
            d -= timedelta(days=1)
        return day - timedelta(days=1)

    def _in_30m_close_eval_window(self, candle: dict, grace_minutes: int = 5) -> bool:
        ts = pd.Timestamp(candle["timestamp"])
        if ts.tzinfo is None:
            ts = ts.tz_localize(IST)
        else:
            ts = ts.tz_convert(IST)
        close_ts = ts + pd.Timedelta(minutes=30)
        now_ist = pd.Timestamp.now(tz=IST)
        return (now_ist - close_ts).total_seconds() / 60 <= grace_minutes

    def _is_after_3pm(self, candle: dict) -> bool:
        return self._candle_time_ist(candle) >= self.eod_exit_time

    def _is_after_315pm(self, candle: dict) -> bool:
        return self._candle_time_ist(candle) >= self.no_entry_time

    def _is_915am(self, candle: dict) -> bool:
        t = self._candle_time_ist(candle)
        return t.hour == 9 and t.minute == 15

    def _is_expiry_day_new_trade(self, candle: dict) -> bool:
        """Check if it's expiry day and we need to shift to next expiry."""
        trade_date = self._trade_date(candle)
        return self._is_weekly_expiry_day(trade_date)

    # ---------- Entry ----------

    def _find_strike_snapshot_params(self, candle, ctx, option_type):
        ts_ist = self._candle_close_ts_ist(candle)
        expiry_tag = str(getattr(self, "_snapshot_expiry_pref", "") or "")
        slot_key = "|".join(
            [
                str(getattr(ctx, "symbol", "") or ""),
                str(option_type or ""),
                expiry_tag,
                ts_ist.strftime("%Y-%m-%d"),
                ts_ist.strftime("%H-%M"),
            ]
        )
        if slot_key in self._snapshot_logged_slots:
            return {}
        self._snapshot_logged_slots.add(slot_key)
        target = "nifty_dos"
        if expiry_tag == "NEXT_WEEKLY":
            target = "nifty_dos_next"
        return {
            "snapshot": True,
            "snapshot_date": ts_ist.strftime("%Y-%m-%d"),
            "snapshot_time": ts_ist.strftime("%H-%M"),
            "snapshot_target": target,
        }

    def _resolve_main_expiry(
        self, candle: dict, ctx, expiry_pref: str = "WEEKLY"
    ) -> Optional[date]:
        chain_exp = self._expiry_from_option_chain()
        if chain_exp is not None:
            return chain_exp
        trade_date = self._trade_date(candle)
        wd = int(getattr(self, "weekly_expiry_weekday", 1) or 1) % 7
        pref = str(expiry_pref or "WEEKLY").strip().upper()
        try:
            resolved = ExpiryResolver.resolve(
                expiry_list=ctx.get_expiry_list() if ctx is not None else [],
                trade_date=trade_date,
                api=self.api,
                expiry_pref=pref,
                weekly_expiry_weekday=wd,
            )
        except (TypeError, ValueError):
            resolved = None
        if resolved is None:
            if pref == "NEXT_WEEKLY":
                return ExpiryResolver.next_weekly_expiry(trade_date, weekday=wd)
            return ExpiryResolver.current_weekly_expiry(trade_date, weekday=wd)
        if ExpiryResolver.is_calendar_expiry(resolved):
            return ExpiryResolver.as_calendar_date(resolved)
        if pref == "NEXT_WEEKLY":
            return ExpiryResolver.next_weekly_expiry(trade_date, weekday=wd)
        return ExpiryResolver.current_weekly_expiry(trade_date, weekday=wd)

    def _strike_is_otm(self, strike: Any, option_type: str, spot: float) -> bool:
        try:
            k = float(strike)
            s = float(spot)
        except (TypeError, ValueError):
            return False
        opt = str(option_type or "").upper()
        if opt in ("CE", "CALL"):
            return k > s
        if opt in ("PE", "PUT"):
            return k < s
        return False

    def _accept_otm_premium_strike(
        self,
        result: Optional[Any],
        option_type: str,
        spot: float,
        min_prem: float,
        max_prem: float,
    ) -> Optional[Any]:
        """Require OTM strike with premium strictly inside min_prem–max_prem."""
        if result is None:
            return None
        strike, premium, row = result
        if not strike:
            return None
        try:
            prem = float(premium)
        except (TypeError, ValueError):
            return None
        if prem < float(min_prem) or prem > float(max_prem):
            return None
        if spot > 0 and not self._strike_is_otm(strike, option_type, spot):
            return None
        return result

    def _get_supertrend_signal(self, candle: dict) -> Optional[str]:
        """Get Supertrend direction: 'BULLISH' (green) or 'BEARISH' (red)."""
        st_key = f"supertrend_{int(self.supertrend_atr_period)}_{float(self.supertrend_multiplier)}"
        dir_key = f"supertrend_dir_{int(self.supertrend_atr_period)}_{float(self.supertrend_multiplier)}"
        st_val = candle.get(st_key)
        dir_val = candle.get(dir_key)
        if pd.isna(st_val) or pd.isna(dir_val):
            return None
        # dir_val: 1 = bullish (green), -1 = bearish (red)
        return "BULLISH" if dir_val == 1 else "BEARISH"

    def _get_ma_signal(self, candle: dict) -> Optional[str]:
        """Get MA9 direction relative to price."""
        period = int(getattr(self, "ma_period", 9) or 9)
        ma_key = f"sma{period}"
        close = candle.get("close")
        ma = candle.get(ma_key)
        if pd.isna(close) or pd.isna(ma):
            return None
        return "BULLISH" if close > ma else "BEARISH"

    def _get_adx_value(self, candle: dict) -> Optional[float]:
        adx_key = f"adx_{int(self.adx_period)}"
        val = candle.get(adx_key)
        if pd.isna(val):
            return None
        return float(val)

    def _candle_favors_trend(self, candle: dict, trend: str) -> bool:
        """Check if candle is in favor of the trend (green for bullish, red for bearish)."""
        open_price = candle.get("open")
        close_price = candle.get("close")
        if pd.isna(open_price) or pd.isna(close_price):
            return False
        if trend == "BULLISH":
            return close_price > open_price
        else:
            return close_price < open_price

    def _build_entry_intents(
        self,
        candle: dict,
        ctx,
        option_type: str,
        *,
        structure_id: str,
    ) -> Optional[List[Any]]:
        signal_key = f"{structure_id}|{self._bar_open_key(candle)}"
        if signal_key in self._entry_signaled_keys:
            return None

        if ctx.position_store.has_open_structure(
            strategy=self.name, structure_id=structure_id, tag="MAIN"
        ):
            return None

        intent_store = getattr(ctx, "intent_store", None)
        if intent_store is not None:
            if intent_store.has_pending_intent(
                strategy=self.name,
                structure_id=structure_id,
                actions=["ENTRY"],
            ):
                return None
            if intent_store.has_entry_for_structure(
                strategy=self.name,
                structure_id=structure_id,
            ):
                return None

        min_prem = float(getattr(self, "premium_min", 80) or 80)
        max_prem = float(getattr(self, "premium_max", 105) or 105)
        spot = float(candle.get("close") or 0)

        # Prefer current weekly; if no OTM in premium band, roll MAIN to next weekly.
        result = None
        expiry_pref = "WEEKLY"
        for pref in ("WEEKLY", "NEXT_WEEKLY"):
            self._snapshot_expiry_pref = pref
            try:
                candidate = self.find_strike_in_premium_range(
                    candle,
                    ctx,
                    option_type,
                    min_prem=min_prem,
                    max_prem=max_prem,
                    expiry_pref=pref,
                )
            finally:
                self._snapshot_expiry_pref = None
            accepted = self._accept_otm_premium_strike(candidate, option_type, spot, min_prem, max_prem)
            if accepted is not None:
                result = accepted
                expiry_pref = pref
                if pref == "NEXT_WEEKLY":
                    logger.info(
                        "NiftyDOS: no OTM prem=%s-%s on current weekly; using next weekly opt=%s ts=%s",
                        min_prem,
                        max_prem,
                        option_type,
                        candle.get("timestamp"),
                    )
                break
            logger.info(
                "NiftyDOS: no OTM strike in prem=%s-%s expiry_pref=%s opt=%s",
                min_prem,
                max_prem,
                pref,
                option_type,
            )

        if result is None:
            logger.warning(
                "NiftyDOS entry skipped: no OTM strike opt=%s prem=%s-%s on WEEKLY or NEXT_WEEKLY ts=%s",
                option_type,
                min_prem,
                max_prem,
                candle.get("timestamp"),
            )
            return None

        strike, premium, row = result

        expiry_for_symbol = self._resolve_main_expiry(candle, ctx, expiry_pref)
        if expiry_for_symbol is None:
            logger.warning("NiftyDOS entry skipped: no weekly expiry pref=%s", expiry_pref)
            return None

        # Do not open a new weekly on expiry day or past expiry.
        if self._trade_date(candle) >= expiry_for_symbol:
            logger.info("NiftyDOS entry skipped: trade_date>=expiry %s", expiry_for_symbol)
            return None

        trading_symbol = ExpiryResolver.build_option_symbol(
            candle["symbol"], expiry_for_symbol, strike, option_type, include_year=True
        )
        inst = ctx.instrument_store.intent_creation_details(
            trading_symbol, ctx.exchange, expiry_for_symbol, option_type, strike
        )
        if inst is None:
            logger.warning("NiftyDOS entry skipped: instrument missing %s", trading_symbol)
            return None

        sell_intent = self.map_instrument_to_intent(
            inst=inst,
            strike_row=row,
            strategy=self.name,
            side="SELL",
            structure_id=structure_id,
            candle_ts=candle["timestamp"],
            tag="MAIN",
            symbol=candle["symbol"],
            action="ENTRY",
        )
        hedge_intent = self.create_hedge_intent(
            parent_sell_intent=sell_intent, candle=candle, ctx=ctx
        )
        self._entry_signaled_keys.add(signal_key)

        # Store entry prices for both MAIN and HEDGE for TP/SL tracking
        self._structure_main_entry_price[structure_id] = float(premium)
        hedge_entry_price = float(getattr(hedge_intent, "price", 0) or 0)
        self._structure_hedge_entry_price[structure_id] = hedge_entry_price
        self._structure_type[structure_id] = "CALL" if option_type in ("CE", "CALL") else "PUT"

        logger.info(
            "NiftyDOS entry structure=%s main=%s premium=%s hedge_premium=%s expiry=%s expiry_pref=%s hedge=%s",
            structure_id,
            trading_symbol,
            premium,
            hedge_entry_price,
            expiry_for_symbol,
            expiry_pref,
            getattr(getattr(hedge_intent, "instrument", None), "trading_symbol", None),
        )
        return [hedge_intent, sell_intent] if hedge_intent else [sell_intent]

    def should_evaluate(self, candle):
        # Live: only eval shortly after 30m bar close. Backtest: every closed bar.
        if RUN_MODE != RunMode.BACKTEST and not self._in_30m_close_eval_window(candle):
            return False

        trade_date = self._trade_date(candle)
        if self._is_event_no_trade_day(trade_date):
            return False
        if self._is_weekly_expiry_day(trade_date):
            return False

        # Check Supertrend signal - ONLY supertrend for initial entry
        st_signal = self._get_supertrend_signal(candle)
        if st_signal is None:
            return False

        # Track Supertrend flip for signal change detection
        if self._prev_st_signal is not None and self._prev_st_signal != st_signal:
            # Supertrend flipped - this is a signal change
            pass
        self._prev_st_signal = st_signal

        eval_key = self._bar_open_key(candle)
        if eval_key in self._evaluated_signal_keys:
            return False
        self._evaluated_signal_keys.add(eval_key)
        return True

    def eval_signal_log_message(self, candle) -> Optional[str]:
        st_signal = self._get_supertrend_signal(candle)
        ma_signal = self._get_ma_signal(candle)
        adx = self._get_adx_value(candle)
        period = int(getattr(self, "ma_period", 9) or 9)
        return (
            f"DOS Signal: ST={st_signal} MA={ma_signal} ADX={adx} "
            f"close={candle.get('close')} sma{period}={candle.get(f'sma{period}')}"
            f" timeframe={getattr(self, 'timeframe', '')}"
        )

    def on_candle(self, candle, ctx):
        trade_date = self._trade_date(candle)
        if self._is_event_no_trade_day(trade_date) or self._is_weekly_expiry_day(trade_date):
            return None

        st_signal = self._get_supertrend_signal(candle)
        if st_signal is None:
            return None

        # Handle SL reentry from PREVIOUS candle (check on this candle - the "next" candle)
        if self._sl_hit_structure:
            # Process all pending SL reentries
            for struct_id, opt_type in list(self._sl_hit_structure.items()):
                logger.info(f"NiftyDOS: Checking SL reentry for {opt_type} on next candle")
                reentry_intents = self._attempt_sl_reentry(candle, ctx, opt_type, struct_id)
                if reentry_intents:
                    return reentry_intents
            # Clear processed SL reentries (only one per candle to avoid multiple)
            self._sl_hit_structure.clear()

        # Check 3:15 PM no-entry rule (only for initial entry, not reentry)
        adx = self._get_adx_value(candle)
        if self._is_after_315pm(candle) and (adx is None or adx < self.reentry_adx_threshold):
            # But allow reentry if we have pending TP reentry
            if not self._tp_hit_pending:
                return None

        # Check 9:15 AM rule - if price opposite to signal, exit and re-enter on 30min close
        if self._is_915am(candle):
            close = candle.get("close")
            if close is not None:
                period = int(getattr(self, "ma_period", 9) or 9)
                ma_val = candle.get(f"sma{period}", 0)
                if st_signal == "BULLISH" and close < ma_val:
                    # Price opposite to signal - will be handled in position management
                    pass
                elif st_signal == "BEARISH" and close > ma_val:
                    pass

        # New entry on Supertrend signal (no MA/ADX filter)
        if st_signal == "BULLISH":
            option_type = "PUT"
            regime = "SUPER_BULLISH"
        elif st_signal == "BEARISH":
            option_type = "CALL"
            regime = "SUPER_BEARISH"
        else:
            return None

        structure_id = self.build_structure_id(candle, regime)
        return self._build_entry_intents(candle, ctx, option_type, structure_id=structure_id)

    # ---------- Exit / TP-SL Management ----------

    def _get_current_premium(self, position, candle, ctx) -> Optional[float]:
        """Get current premium for position."""
        if RUN_MODE == RunMode.BACKTEST:
            return self.get_option_price_at_candle(
                candle,
                ctx,
                position.instrument.strike,
                position.instrument.option_type,
                position.instrument.expiry,
            )
        # For live/paper, would need to fetch from option chain
        return None

    def _get_structure_positions(self, position, ctx):
        """Get both MAIN and HEDGE positions for a structure."""
        main_pos = position
        hedge_pos = None
        if ctx and ctx.position_store:
            hedge_pos = ctx.position_store.get_hedge_for(main_pos)
        return main_pos, hedge_pos

    def _get_structure_capital(self, structure_id: str, main_position, ctx=None) -> float:
        """Calculate total capital/margin deployed for the hedged structure.

        Uses broker's calculate_structure_margin to get the actual margin required
        for the hedged position (MAIN + HEDGE with hedge benefit).
        Falls back to configured margin_per_lot if broker calculation unavailable.
        """
        qty = abs(int(main_position.net_qty or 0))
        if qty <= 0:
            return 0.0

        # Try to get broker-calculated margin for the hedged structure
        if ctx and hasattr(ctx, "broker") and ctx.broker:
            broker = ctx.broker
            # Find the hedge position for this structure
            hedge_position = None
            if ctx.position_store:
                hedge_position = ctx.position_store.get_hedge_for(main_position)

            if hedge_position and hasattr(broker, "calculate_structure_margin"):
                try:
                    # Get entry prices for margin calculation
                    main_entry = self._structure_main_entry_price.get(structure_id, 0)
                    hedge_entry = self._structure_hedge_entry_price.get(structure_id, 0)

                    if main_entry > 0 and hedge_entry > 0:
                        margin_result = broker.calculate_structure_margin(
                            main_leg=main_position,
                            hedge_leg=hedge_position,
                            main_execution_price=main_entry,
                            hedge_execution_price=hedge_entry,
                            include_position=True,
                            include_orders=True,
                        )
                        if margin_result and margin_result.get("final_margin", 0) > 0:
                            # Return margin per lot * qty
                            final_margin = margin_result["final_margin"]
                            margin_per_lot = final_margin / qty if qty > 0 else final_margin
                            logger.debug(
                                "NiftyDOS: Using broker margin for structure %s: "
                                "final_margin=%.2f margin_per_lot=%.2f hedge_benefit=%.2f",
                                structure_id,
                                final_margin,
                                margin_per_lot,
                                margin_result.get("hedge_benefit", 0)
                            )
                            return final_margin
                except Exception as e:
                    logger.warning("NiftyDOS: Broker margin calculation failed, using fallback: %s", e)

        # Fallback to configured margin_per_lot
        return self.margin_per_lot * qty

    def _calculate_structure_pnl(self, main_position, hedge_position, candle, ctx) -> float:
        """Calculate combined P&L for the hedged structure (MAIN + HEDGE).

        MAIN: Short option - profit when premium decreases
        HEDGE: Long option - profit when premium increases
        """
        structure_id = main_position.structure_id

        # Get entry prices
        main_entry = self._structure_main_entry_price.get(structure_id, 0)
        hedge_entry = self._structure_hedge_entry_price.get(structure_id, 0)

        if main_entry <= 0:
            return 0.0

        # Get current prices
        main_current = self._get_current_premium(main_position, candle, ctx)
        if main_current is None:
            return 0.0

        # Calculate MAIN P&L (short: profit when premium drops)
        lot_size = getattr(main_position.instrument, "lot_size", 0) or 0
        qty = abs(int(main_position.net_qty or 0))
        main_pnl = (main_entry - main_current) * lot_size * qty

        # Calculate HEDGE P&L if hedge exists (long: profit when premium rises)
        hedge_pnl = 0.0
        if hedge_position and hedge_position.net_qty != 0:
            hedge_current = self._get_current_premium(hedge_position, candle, ctx)
            if hedge_current is not None and hedge_entry > 0:
                hedge_qty = abs(int(hedge_position.net_qty or 0))
                hedge_pnl = (hedge_current - hedge_entry) * lot_size * hedge_qty

        return main_pnl + hedge_pnl

    def _check_tp_sl(self, position, candle, ctx) -> Optional[str]:
        """Check if TP or SL hit based on structure capital (margin deployed).

        Uses combined P&L (MAIN + HEDGE) vs margin_per_lot * qty.
        """
        structure_id = position.structure_id
        pos_type = self._structure_type.get(structure_id, "")
        if pos_type == "CALL":
            sl_pct = self.call_sl_pct
            tp_pct = self.call_tp_pct
        else:
            sl_pct = self.put_sl_pct
            tp_pct = self.put_tp_pct

        # Get both positions
        main_pos, hedge_pos = self._get_structure_positions(position, ctx)

        # Calculate capital deployed (margin required for hedged structure)
        capital_used = self._get_structure_capital(structure_id, main_pos, ctx)
        if capital_used <= 0:
            return None

        # Calculate combined structure P&L
        structure_pnl = self._calculate_structure_pnl(main_pos, hedge_pos, candle, ctx)

        # Calculate SL and TP amounts based on capital deployed
        sl_amount = capital_used * sl_pct / 100.0
        tp_amount = capital_used * tp_pct / 100.0

        # SL hit when loss exceeds SL amount
        if structure_pnl <= -sl_amount:
            logger.info(f"NiftyDOS: SL hit for structure {structure_id}, P&L={structure_pnl:.2f}, SL={sl_amount:.2f}, Capital={capital_used:.2f}")
            return "SL"
        # TP hit when profit exceeds TP amount
        if structure_pnl >= tp_amount:
            logger.info(f"NiftyDOS: TP hit for structure {structure_id}, P&L={structure_pnl:.2f}, TP={tp_amount:.2f}, Capital={capital_used:.2f}")
            return "TP"
        return None

    def _check_eod_exit(self, position, candle, ctx) -> bool:
        """Check if after 3pm and |P&L| >= eod_exit_pct of capital deployed."""
        if not self._is_after_3pm(candle):
            return False

        structure_id = position.structure_id
        main_pos, hedge_pos = self._get_structure_positions(position, ctx)

        capital_used = self._get_structure_capital(structure_id, main_pos, ctx)
        if capital_used <= 0:
            return False

        structure_pnl = self._calculate_structure_pnl(main_pos, hedge_pos, candle, ctx)

        eod_exit_amount = capital_used * self.eod_exit_pct / 100.0
        if abs(structure_pnl) >= eod_exit_amount:
            logger.info(f"NiftyDOS: EOD exit for structure {structure_id}, P&L={structure_pnl:.2f}, threshold={eod_exit_amount:.2f}")
            return True
        return False

    def should_exit(self, position, candle, ctx=None):
        if position.tag != "MAIN":
            return False

        # Check TP/SL on 5min timeframe
        tp_sl = self._check_tp_sl(position, candle, ctx)
        if tp_sl:
            # Track for reentry logic
            opt_type = self._structure_type.get(position.structure_id, "")
            if tp_sl == "SL":
                # SL hit - schedule reentry on NEXT candle with MA/ADX/candle check
                self._sl_hit_structure[position.structure_id] = opt_type
                logger.info(f"NiftyDOS: SL hit for structure {position.structure_id}, reentry on next candle")
            elif tp_sl == "TP":
                # TP hit - immediate reentry on SAME candle, same direction
                self._tp_hit_pending[position.structure_id] = opt_type
                logger.info(f"NiftyDOS: TP hit for structure {position.structure_id}, immediate reentry")
            return True

        # Check EOD exit after 3pm
        if self._check_eod_exit(position, candle, ctx):
            logger.info(f"NiftyDOS: EOD exit for structure {position.structure_id}")
            return True

        # Check Supertrend reversal
        st_signal = self._get_supertrend_signal(candle)
        if st_signal is None:
            return False

        opt = str(getattr(position.instrument, "option_type", "") or "").upper()
        # Short PUT (bullish) exits on bearish ST; Short CALL (bearish) exits on bullish ST
        if opt in ("PE", "PUT") and st_signal == "BEARISH":
            return True
        if opt in ("CE", "CALL") and st_signal == "BULLISH":
            return True

        return False

    def on_position_exit(self, position, candle, ctx):
        intents = []
        price = (
            self.get_option_price_at_candle(
                candle,
                ctx,
                position.instrument.strike,
                position.instrument.option_type,
                position.instrument.expiry,
            )
            if RUN_MODE == RunMode.BACKTEST
            else None
        )
        qty_lots = self._order_qty_in_lots(position.instrument, abs(int(position.net_qty or 0)))
        intents.append(
            self.create_order_intent(
                inst=position.instrument,
                side="BUY" if position.net_qty < 0 else "SELL",
                qty=qty_lots,
                price=price,
                order_type="LIMIT",
                strategy=self.name,
                candle_ts=candle["timestamp"],
                structure_id=position.structure_id,
                tag="MAIN_EXIT",
                symbol=candle["symbol"],
                action="EXIT",
            )
        )
        hedge_exit = self.create_hedge_exit_intent(position, candle, ctx)
        if hedge_exit:
            intents.append(hedge_exit)

        # Get option type before cleaning up
        opt_type = self._structure_type.get(position.structure_id, "")

        # Clean up tracking
        self._structure_main_entry_price.pop(position.structure_id, None)
        self._structure_hedge_entry_price.pop(position.structure_id, None)
        self._structure_type.pop(position.structure_id, None)

        # Handle reentry after exit
        # Check for immediate TP reentry (same candle)
        if position.structure_id in self._tp_hit_pending:
            reentry_type = self._tp_hit_pending.pop(position.structure_id)
            if reentry_type:
                logger.info(f"NiftyDOS: Immediate TP reentry for {reentry_type} on same candle")
                reentry_intents = self._attempt_immediate_reentry(candle, ctx, reentry_type, position.structure_id)
                if reentry_intents:
                    intents.extend(reentry_intents)

        # Check for SL reentry (next candle) - will be handled on next on_candle call
        # The _sl_hit_structure is checked in on_candle

        return intents

    # ---------- Reentry Logic ----------

    def _should_reenter_on_sl(self, candle, ctx, option_type: str) -> bool:
        """Check reentry conditions after SL hit."""
        adx = self._get_adx_value(candle)
        if adx is None or adx <= self.reentry_adx_threshold:
            return False

        ma_signal = self._get_ma_signal(candle)
        if ma_signal is None:
            return False

        # Check MA alignment with trend
        if option_type == "PUT" and ma_signal != "BULLISH":
            return False
        if option_type == "CALL" and ma_signal != "BEARISH":
            return False

        # Check candle favors trend
        st_signal = self._get_supertrend_signal(candle)
        if st_signal is None:
            return False
        if not self._candle_favors_trend(candle, st_signal):
            return False

        return True

    def _should_reenter_on_tp(self, candle, ctx, option_type: str) -> bool:
        """Check reentry conditions after TP hit."""
        ma_signal = self._get_ma_signal(candle)
        if ma_signal is None:
            return False

        if option_type == "PUT" and ma_signal != "BULLISH":
            return False
        if option_type == "CALL" and ma_signal != "BEARISH":
            return False

        return True

    def _attempt_sl_reentry(self, candle, ctx, option_type: str, structure_id: str) -> Optional[List[Any]]:
        """Attempt reentry on NEXT candle after SL hit - check MA, ADX, and candle direction."""
        trade_date = self._trade_date(candle)
        if self._is_event_no_trade_day(trade_date) or self._is_weekly_expiry_day(trade_date):
            return None

        # Check 3:15 PM no-entry rule for reentry
        adx = self._get_adx_value(candle)
        if self._is_after_315pm(candle) and (adx is None or adx < self.reentry_adx_threshold):
            return None

        # SL Reentry conditions:
        # 1. ADX > 25
        if adx is None or adx <= self.reentry_adx_threshold:
            logger.info(f"NiftyDOS: SL reentry skipped - ADX {adx} <= {self.reentry_adx_threshold}")
            return None

        # 2. MA alignment with trend
        ma_signal = self._get_ma_signal(candle)
        if ma_signal is None:
            return None
        if option_type == "PUT" and ma_signal != "BULLISH":
            logger.info(f"NiftyDOS: SL reentry skipped - MA not bullish for PUT")
            return None
        if option_type == "CALL" and ma_signal != "BEARISH":
            logger.info(f"NiftyDOS: SL reentry skipped - MA not bearish for CALL")
            return None

        # 3. Candle favors trend (green for bullish, red for bearish)
        st_signal = self._get_supertrend_signal(candle)
        if st_signal is None:
            return None
        if not self._candle_favors_trend(candle, st_signal):
            logger.info(f"NiftyDOS: SL reentry skipped - candle not in favor of {st_signal}")
            return None

        # All conditions met - reenter
        logger.info(f"NiftyDOS: SL reentry conditions met for {option_type}")
        new_structure_id = self.build_structure_id(candle, "REENTRY_SL")
        return self._build_entry_intents(candle, ctx, option_type, structure_id=new_structure_id)

    def _attempt_immediate_reentry(self, candle, ctx, option_type: str, structure_id: str) -> Optional[List[Any]]:
        """Attempt IMMEDIATE reentry on TP hit - same candle, same direction, find strike 80-105."""
        trade_date = self._trade_date(candle)
        if self._is_event_no_trade_day(trade_date) or self._is_weekly_expiry_day(trade_date):
            return None

        # For TP reentry: NO MA/ADX/candle check - just find strike in 80-105 range and enter
        # Check 3:15 PM no-entry rule (but TP reentry is allowed if ADX >= 25 per rules)
        adx = self._get_adx_value(candle)
        if self._is_after_315pm(candle) and (adx is None or adx < self.reentry_adx_threshold):
            return None

        logger.info(f"NiftyDOS: Immediate TP reentry for {option_type} - finding strike 80-105")
        new_structure_id = self.build_structure_id(candle, "REENTRY_TP")
        return self._build_entry_intents(candle, ctx, option_type, structure_id=new_structure_id)

    def _attempt_reentry(self, candle, ctx, option_type: str, structure_id: str, reason: str) -> Optional[List[Any]]:
        """Legacy reentry method - kept for compatibility."""
        if reason == "SL":
            return self._attempt_sl_reentry(candle, ctx, option_type, structure_id)
        elif reason == "TP":
            return self._attempt_immediate_reentry(candle, ctx, option_type, structure_id)
        return None

    # ---------- Weekly hedge rollover ----------

    def is_rollover_window(self, ts):
        current = pd.to_datetime(ts).date()
        return current.weekday() < 5

    def should_roll_hedge(self, hedge, ts):
        expiry = pd.to_datetime(hedge.instrument.expiry).date()
        current = pd.to_datetime(ts).date()
        if expiry <= current:
            return False
        days_before = int(getattr(self, "hedge_rollover_days_before_expiry", 1) or 1)
        roll_day = expiry
        for _ in range(max(1, days_before)):
            roll_day = self._prior_trading_day(roll_day)
        return current >= roll_day

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

            wd = int(getattr(self, "weekly_expiry_weekday", 1) or 1) % 7
            next_exp = ExpiryResolver.next_weekly_expiry(ts.date(), weekday=wd)
            self._force_hedge_expiry = next_exp
            try:
                new_hedge = self.create_hedge_intent(parent, candle, ctx)
                if not new_hedge:
                    logger.warning(
                        "NiftyDOS hedge rollover skipped (no new hedge) structure=%s",
                        hedge.structure_id,
                    )
                    continue
                intents.append(new_hedge)
                hedge_exit = self.create_hedge_exit_intent(parent, candle, ctx)
                if hedge_exit:
                    intents.append(hedge_exit)
            finally:
                self._force_hedge_expiry = None

            self.rolled_hedges.add(roll_key)
            logger.info(
                "NiftyDOS hedge rollover structure=%s next_expiry=%s",
                hedge.structure_id,
                next_exp,
            )

        return intents