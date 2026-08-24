"""
NIFTY-DOS (Supertrend + MA9 + ADX Directional Option Selling)

- Timeframe: 30m, closed-bar evaluation
- On day of expiry: new trade triggered, shift to next expiry
- Supertrend(16, 2) + SMA9 + ADX(14)
- Supertrend Green (bullish) + MA9 bullish + ADX > 25 → SELL OTM PUT (premium 80-105)
- Supertrend Red (bearish) + MA9 bearish + ADX > 25 → SELL OTM CALL (premium 80-105)
- Hedge: 500 points OTM from MAIN on same weekly expiry
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
# Dhan API imports for live trading
from dhanhq import dhanhq
from core.library.dhan_tradehull import Tradehull

logger = logging.getLogger(__name__)


class NiftyDOS(IndiaMktMixins, BaseStrategy):
    """NIFTY Supertrend + MA9 + ADX directional option selling with TP/SL management."""

    name = "NiftyDOS"
    underlying_symbols = ["NIFTY"]
    timeframe = "30"
    extra_timeframes = ["5"]
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
    # Indicator parameters (for indicator_manager to compute and persist)
    supertrend_length = 16
    supertrend_factor = 2.0
    sma_period = 9
    adx_period = 14
    # Legacy aliases (used by strategy logic)
    supertrend_atr_period = 16
    supertrend_multiplier = 2.0
    ma_period = 9
    premium_min = 80
    premium_max = 105
    hedge_distance_points = 500
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
    eod_exit_time = time(15, 00)  # 3:00 PM
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
        # Structure tracking: store both MAIN and HEDGE entry prices
        self._structure_main_entry_price: dict[str, float] = {}  # structure_id -> main entry premium
        self._structure_hedge_entry_price: dict[str, float] = {}  # structure_id -> hedge entry premium
        self._structure_type: dict[str, str] = {}  # structure_id -> "CALL" or "PUT"
        # Track SL/TP hit for reentry timing
        self._sl_hit_structure: dict[str, str] = {}  # structure_id -> option_type (for next candle reentry)
        self._tp_hit_pending: dict[str, str] = {}  # structure_id -> option_type (for immediate reentry)
        # Track Supertrend flip for immediate reentry
        self._prev_st_signal: Optional[str] = None  # track previous supertrend for flip detection
        self._st_flip_reentry_pending: dict[str, str] = {}  # structure_id -> new_option_type (for immediate reentry on ST flip)
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
        if "supertrend_length" in params:
            self.supertrend_length = int(params["supertrend_length"])
            self.supertrend_atr_period = self.supertrend_length
        if "supertrend_factor" in params:
            self.supertrend_factor = float(params["supertrend_factor"])
            self.supertrend_multiplier = self.supertrend_factor
        if "supertrend_atr_period" in params:
            self.supertrend_atr_period = int(params["supertrend_atr_period"])
            self.supertrend_length = self.supertrend_atr_period
        if "supertrend_multiplier" in params:
            self.supertrend_multiplier = float(params["supertrend_multiplier"])
            self.supertrend_factor = self.supertrend_multiplier
        if "sma_period" in params:
            self.sma_period = int(params["sma_period"])
            self.ma_period = self.sma_period
        if "ma_period" in params:
            self.ma_period = int(params["ma_period"])
            self.sma_period = self.ma_period
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

    def get_trading_symbol_from_instrument_df(self, instrument_df, strike, option_type, expiry_date):
        """Get trading symbol from instrument dataframe."""
        try:
            expiry_str = pd.to_datetime(expiry_date).strftime('%d%b%y').upper()
            opt_type = 'CE' if option_type in ('CE', 'CALL') else 'PE'

            # Convert instrument expiry to same format (strip time), coercing errors to NaT
            instrument_expiry_str = pd.to_datetime(instrument_df['SEM_EXPIRY_DATE'], errors='coerce').dt.strftime('%d%b%y').str.upper()

            # Filter for matching symbol
            mask_custom = instrument_df['SEM_CUSTOM_SYMBOL'].str.startswith('NIFTY')
            mask_expiry = instrument_expiry_str == expiry_str
            mask_opt = instrument_df['SEM_OPTION_TYPE'] == opt_type
            # For options, strike price is stored as actual strike (not multiplied by 100)
            mask_strike = abs(instrument_df['SEM_STRIKE_PRICE'] - strike) < 0.01

            combined_mask = mask_custom & mask_expiry & mask_opt & mask_strike

            filtered = instrument_df[combined_mask]

            if not filtered.empty:
                return filtered.iloc[0]['SEM_TRADING_SYMBOL'], int(filtered.iloc[0]['SEM_SMST_SECURITY_ID']), int(filtered.iloc[0]['SEM_LOT_UNITS'])

            # Fallback: try matching by SEM_TRADING_SYMBOL
            mask_custom2 = instrument_df['SEM_TRADING_SYMBOL'].str.startswith('NIFTY')
            combined_mask2 = mask_custom2 & mask_expiry & mask_opt & mask_strike

            if not filtered2.empty:
                return filtered2.iloc[0]['SEM_TRADING_SYMBOL'], int(filtered2.iloc[0]['SEM_SMST_SECURITY_ID']), int(filtered2.iloc[0]['SEM_LOT_UNITS'])

            # Fallback: construct symbol
            symbol = f"NIFTY{expiry_str}{int(strike)}{opt_type}"
            return symbol, 0, 75
        except Exception as e:
            logger.warning(f"Could not find trading symbol: {e}")
            return None, 0, 75

    def calculate_margin_dhan(self, dhan, tradehull, main_symbol, hedge_symbol, main_expiry, hedge_expiry, main_strike, hedge_strike, option_type, main_qty=75, hedge_qty=75, main_price=0, hedge_price=0):
        """Calculate margin using Dhan's margin_calculator_multi API."""
        try:
            # Build scrip list for multi-leg margin
            scrip_list = [
                {
                    "tradingsymbol": main_symbol,
                    "exchange": "NFO",
                    "transaction_type": "SELL",
                    "quantity": main_qty,
                    "trade_type": "MARGIN",
                    "price": main_price,
                    "trigger_price": 0,
                },
                {
                    "tradingsymbol": hedge_symbol,
                    "exchange": "NFO",
                    "transaction_type": "BUY",
                    "quantity": hedge_qty,
                    "trade_type": "MARGIN",
                    "price": hedge_price,
                    "trigger_price": 0,
                }
            ]

            margin_result = tradehull.margin_calculator_multi(
                scrip_list=scrip_list,
                include_position=True,
                include_orders=True
            )

            if margin_result and isinstance(margin_result, dict):
                total_margin = margin_result.get('totalMargin') or margin_result.get('total_margin') or 0
                return {
                    'final_margin': total_margin,
                    'total_margin': total_margin,
                    'margin_result': margin_result
                }
        except Exception as e:
            logger.warning(f"Dhan margin calculation failed: {e}")

        return None

    def get_warmup_period(self):
        return max(50, int(self.supertrend_atr_period) * 5, int(self.adx_period) * 3)

    def prepare_indicators(self, df):
        # Supertrend - indicator_manager computes this with keys: supertrend, supertrend_direction,
        # supertrend_is_bullish, supertrend_upper, supertrend_lower, supertrend_atr
        # We still compute here for backtest, but live mode uses indicator_manager's computed values
        df = add_supertrend(
            df,
            atr_period=int(self.supertrend_length),
            multiplier=float(self.supertrend_factor),
        )
        # Rename columns to match indicator_manager's persisted keys
        if "supertrend" in df.columns:
            df.rename(columns={
                "supertrend": "supertrend",
                "supertrend_direction": "supertrend_direction",
                "supertrend_is_bullish": "supertrend_is_bullish",
                "supertrend_upper": "supertrend_upper",
                "supertrend_lower": "supertrend_lower",
                "supertrend_atr": "supertrend_atr",
            }, inplace=True)
        # SMA - indicator_manager uses sma{period} key
        period = int(getattr(self, "sma_period", 9) or 9)
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
        """Return indicator keys that match what indicator_manager writes to the shared JSONL.

        indicator_manager computes Supertrend with keys: supertrend, supertrend_direction,
        supertrend_is_bullish, supertrend_upper, supertrend_lower, supertrend_atr
        SMA with key: sma{period}
        ADX with keys: adx_{period}, adx_di_plus_{period}, adx_di_minus_{period}
        """
        period = int(getattr(self, "sma_period", 9) or 9)
        st_keys = [
            "supertrend",
            "supertrend_direction",
            "supertrend_is_bullish",
            "supertrend_upper",
            "supertrend_lower",
            "supertrend_atr",
        ]
        return (
            default_persisted_keys_for_sma(period, column=f"sma{period}")
            + [f"prev_sma{period}", "prev_close"]
            + st_keys
            + [f"adx_{int(self.adx_period)}", f"adx_di_plus_{int(self.adx_period)}", f"adx_di_minus_{int(self.adx_period)}"]
        )

    def shared_indicator_signature(self) -> str:
        return (
            f"dos_st{int(self.supertrend_length)}_{float(self.supertrend_factor)}_"
            f"ma{int(self.sma_period)}_adx{int(self.adx_period)}"
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

    def _is_945am(self, candle: dict) -> bool:
        t = self._candle_time_ist(candle)
        return t.hour == 9 and t.minute == 45

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
        """Get Supertrend direction: 'BULLISH' (green) or 'BEARISH' (red).

        indicator_manager writes: supertrend_direction (1.0/-1.0) and supertrend_is_bullish (bool)
        """
        # Prefer supertrend_is_bullish (bool), fallback to supertrend_direction (1.0/-1.0)
        is_bullish = candle.get("supertrend_is_bullish")
        if is_bullish is not None:
            return "BULLISH" if is_bullish else "BEARISH"
        dir_val = candle.get("supertrend_direction")
        if dir_val is not None and not pd.isna(dir_val):
            return "BULLISH" if dir_val == 1.0 or dir_val == 1 else "BEARISH"
        return None

    def _get_ma_signal(self, candle: dict) -> Optional[str]:
        """Get MA9 direction relative to price."""
        period = int(getattr(self, "sma_period", 9) or 9)
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

        # On expiry day, ALWAYS use next weekly expiry (per strategy rules)
        is_expiry_day = self._is_expiry_day_new_trade(candle)
        if is_expiry_day:
            # Force next weekly expiry on expiry day
            pref = "NEXT_WEEKLY"
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
                logger.info(
                    "NiftyDOS: Expiry day - using next weekly expiry opt=%s ts=%s",
                    option_type,
                    candle.get("timestamp"),
                )
            else:
                logger.warning(
                    "NiftyDOS entry skipped: no OTM strike in prem=%s-%s on NEXT_WEEKLY (expiry day) opt=%s ts=%s",
                    min_prem,
                    max_prem,
                    option_type,
                    candle.get("timestamp"),
                )
                return None
        else:
            # Normal logic: prefer current weekly; if no OTM in premium band, roll to next weekly
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

        # On expiry day, allow evaluation - _build_entry_intents will handle NEXT_WEEKLY expiry
        # The original logic blocked all expiry day entries, but _build_entry_intents forces
        # NEXT_WEEKLY expiry on expiry day, so we should allow evaluation.

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
        period = int(getattr(self, "sma_period", 9) or 9)
        return (
            f"DOS Signal: ST={st_signal} MA={ma_signal} ADX={adx} "
            f"close={candle.get('close')} sma{period}={candle.get(f'sma{period}')}"
            f" timeframe={getattr(self, 'timeframe', '')}"
        )

    def on_candle(self, candle, ctx):
        trade_date = self._trade_date(candle)
        if self._is_event_no_trade_day(trade_date):
            return None

        # Determine candle timeframe
        candle_tf = str(candle.get("timeframe", self.timeframe) or "").strip()
        is_primary_tf = (candle_tf == str(self.timeframe).strip())
        is_5min_tf = (candle_tf == "5")

        # On expiry day, allow entry - _build_entry_intents will force NEXT_WEEKLY expiry
        # (No longer blocking expiry day entries here)

        st_signal = self._get_supertrend_signal(candle)
        if st_signal is None:
            return None

        # ===== TP/SL CHECK ON 5-MIN CANDLES =====
        # Check TP/SL on EVERY 5-min candle (for intrabar exit)
        if is_5min_tf:
            exit_intents = self._check_tp_sl_on_5min(candle, ctx)
            if exit_intents:
                return exit_intents

        # ===== REENTRY LOGIC =====
        # TP reentry: immediate on SAME 5-min candle (handled in _check_tp_sl_on_5min via on_position_exit)
        # ST flip reentry: immediate on SAME 5-min candle (handled in should_exit -> on_position_exit)
        # SL reentry: ONLY on 30-min (primary) timeframe, on NEXT candle after SL hit

        # Handle SL reentry from PREVIOUS candle - ONLY on primary timeframe (30-min)
        if is_primary_tf and self._sl_hit_structure:
            # Process all pending SL reentries
            for struct_id, opt_type in list(self._sl_hit_structure.items()):
                logger.info(f"NiftyDOS: Checking SL reentry for {opt_type} on next 30-min candle")
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

        # Check 9:45 AM rule - if no open position, create position on Supertrend direction
        if self._is_945am(candle):
            # Check if there's already an open position for this strategy
            has_open_position = False
            if ctx and ctx.position_store:
                try:
                    open_positions = ctx.position_store.get_open_positions(
                        underlying=str(candle.get("symbol") or ""),
                        strategy=self.name,
                    ) or []
                    # Check for any MAIN position with non-zero qty
                    for pos in open_positions:
                        if getattr(pos, "tag", "") == "MAIN" and int(getattr(pos, "net_qty", 0) or 0) != 0:
                            has_open_position = True
                            break
                except Exception as e:
                    logger.warning(f"NiftyDOS: Error checking open positions at 9:45: {e}")

            if not has_open_position:
                logger.info(f"NiftyDOS: 9:45 AM - No open position, creating position on Supertrend direction: {st_signal}")
                # Determine option type based on Supertrend signal
                if st_signal == "BULLISH":
                    option_type = "PUT"
                    regime = "SUPER_BULLISH_945"
                elif st_signal == "BEARISH":
                    option_type = "CALL"
                    regime = "SUPER_BEARISH_945"
                else:
                    option_type = None

                if option_type:
                    structure_id = self.build_structure_id(candle, regime)
                    return self._build_entry_intents(candle, ctx, option_type, structure_id=structure_id)

        # New entry on Supertrend signal (no MA/ADX filter) - ONLY on primary timeframe (30-min)
        if not is_primary_tf:
            return None

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

        First tries direct Dhan API margin calculation (like emergency file),
        then falls back to broker's calculate_structure_margin,
        finally falls back to configured margin_per_lot.
        """
        qty = abs(int(main_position.net_qty or 0))
        if qty <= 0:
            return 0.0

        # Try direct Dhan API margin calculation first (like emergency file)
        try:
            # Load Dhan credentials from environment
            import os
            from dotenv import load_dotenv
            load_dotenv('/root/Dhan-codebase/.env')
            client_id = os.getenv("DHAN_CLIENT_CODE") or os.getenv("DHAN_CLIENT_ID")
            access_token = os.getenv("DHAN_ACCESS_TOKEN")

            if client_id and access_token:
                dhan = dhanhq(client_id, access_token)
                tradehull = Tradehull(client_id, access_token)

                # Get position details for margin calculation
                main_symbol = getattr(main_position.instrument, 'tradingsymbol', '')
                hedge_position = None
                if ctx and ctx.position_store:
                    hedge_position = ctx.position_store.get_hedge_for(main_position)
                hedge_symbol = getattr(hedge_position.instrument, 'tradingsymbol', '') if hedge_position else ''

                # Get entry prices
                main_entry = self._structure_main_entry_price.get(structure_id, 0.0)
                hedge_entry = self._structure_hedge_entry_price.get(structure_id, 0.0)

                # Get strike prices from positions
                main_strike = getattr(main_position.instrument, 'strike', 0.0)
                hedge_strike = getattr(hedge_position.instrument, 'strike', 0.0) if hedge_position else 0.0

                # Get option types
                main_option_type = getattr(main_position.instrument, 'option_type', '')
                # Hedge option type is same as main for this strategy
                hedge_option_type = main_option_type

                # Get quantities
                main_qty = abs(int(getattr(main_position, 'net_qty', 0) or 0))
                hedge_qty = abs(int(getattr(hedge_position, 'net_qty', 0) or 0)) if hedge_position else main_qty

                # Calculate margin using direct Dhan API
                margin_result = self.calculate_margin_dhan(
                    dhan=dhan,
                    tradehull=tradehull,
                    main_symbol=main_symbol,
                    hedge_symbol=hedge_symbol,
                    main_expiry=getattr(main_position.instrument, 'expiry', None),
                    hedge_expiry=getattr(hedge_position.instrument, 'expiry', None) if hedge_position else None,
                    main_strike=main_strike,
                    hedge_strike=hedge_strike,
                    option_type=main_option_type,
                    main_qty=main_qty,
                    hedge_qty=hedge_qty,
                    main_price=main_entry,
                    hedge_price=hedge_entry
                )

                if margin_result and margin_result.get('final_margin', 0) > 0:
                    final_margin = margin_result['final_margin']
                    logger.debug(
                        "NiftyDOS: Using direct Dhan API margin for structure %s: final_margin=%.2f",
                        structure_id,
                        final_margin
                    )
                    return final_margin
        except Exception as e:
            logger.warning("NiftyDOS: Direct Dhan API margin calculation failed, trying broker method: %s", e)

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

    def _check_tp_sl_on_5min(self, candle, ctx):
        """Check TP/SL and EOD exit on 5-min candle and return exit intents if hit."""
        if not ctx or not ctx.position_store:
            return None

        symbol = str(candle.get("symbol", "") or "")
        open_positions = ctx.position_store.get_open_positions(
            underlying=symbol, strategy=self.name
        ) or []

        exit_intents = []
        for position in open_positions:
            if position.tag != "MAIN":
                continue

            # Check TP/SL
            tp_sl = self._check_tp_sl(position, candle, ctx)
            if tp_sl:
                opt_type = self._structure_type.get(position.structure_id, "")
                if tp_sl == "SL":
                    self._sl_hit_structure[position.structure_id] = opt_type
                    logger.info(f"NiftyDOS: 5min SL hit for structure {position.structure_id}, reentry on next candle")
                elif tp_sl == "TP":
                    self._tp_hit_pending[position.structure_id] = opt_type
                    logger.info(f"NiftyDOS: 5min TP hit for structure {position.structure_id}, immediate reentry")

                # Generate exit intents
                intents = self.on_position_exit(position, candle, ctx) or []
                exit_intents.extend(intents)
                continue  # Skip EOD check if TP/SL already hit

            # Check EOD exit after 3pm (also on 5-min candles)
            if self._check_eod_exit(position, candle, ctx):
                logger.info(f"NiftyDOS: 5min EOD exit for structure {position.structure_id}")
                intents = self.on_position_exit(position, candle, ctx) or []
                exit_intents.extend(intents)

        return exit_intents if exit_intents else None

    def should_exit(self, position, candle, ctx=None):
        if position.tag != "MAIN":
            return False

        # Detect if this is a 5-min candle (extra timeframe)
        candle_tf = str(candle.get("timeframe", self.timeframe) or "").strip()
        is_5min_tf = (candle_tf == "5")

        # On 5-min candles: SKIP TP/SL/EOD/ST-FLIP checks (all handled on 30-min only)
        if not is_5min_tf:
            # Check TP/SL (only on primary timeframe - 30-min)
            tp_sl = self._check_tp_sl(position, candle, ctx)
            if tp_sl:
                # Track for reentry logic
                opt_type = self._structure_type.get(position.structure_id, "")
                if tp_sl == "SL":
                    # SL hit - schedule reentry on NEXT candle with MA/ADX/candle check
                    self._sl_hit_structure[position.structure_id] = opt_type
                    logger.info(f"NiftyDOS: SL hit for structure {position.structure_id}, reentry on next 30-min candle")
                elif tp_sl == "TP":
                    # TP hit - immediate reentry on SAME candle, same direction
                    self._tp_hit_pending[position.structure_id] = opt_type
                    logger.info(f"NiftyDOS: TP hit for structure {position.structure_id}, immediate reentry")
                return True

            # Check EOD exit after 3pm (only on primary timeframe)
            if self._check_eod_exit(position, candle, ctx):
                logger.info(f"NiftyDOS: EOD exit for structure {position.structure_id}")
                return True

            # Check Supertrend reversal (only on 30-min timeframe)
            st_signal = self._get_supertrend_signal(candle)
            if st_signal is None:
                return False

            opt = str(getattr(position.instrument, "option_type", "") or "").upper()
            # Short PUT (bullish) exits on bearish ST; Short CALL (bearish) exits on bullish ST
            st_flip = False
            new_option_type = None
            if opt in ("PE", "PUT") and st_signal == "BEARISH":
                st_flip = True
                new_option_type = "CALL"
            elif opt in ("CE", "CALL") and st_signal == "BULLISH":
                st_flip = True
                new_option_type = "PUT"

            if st_flip and new_option_type:
                # Supertrend flipped - schedule immediate reentry on same candle in new direction
                self._st_flip_reentry_pending[position.structure_id] = new_option_type
                logger.info(f"NiftyDOS: Supertrend flip detected for structure {position.structure_id}, "
                            f"old={opt} new={new_option_type}, immediate reentry on same 30-min candle")
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

        # Check for immediate ST flip reentry (same candle)
        if position.structure_id in self._st_flip_reentry_pending:
            reentry_type = self._st_flip_reentry_pending.pop(position.structure_id)
            if reentry_type:
                logger.info(f"NiftyDOS: Immediate ST flip reentry for {reentry_type} on same candle")
                reentry_intents = self._attempt_st_flip_reentry(candle, ctx, reentry_type, position.structure_id)
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

    def _attempt_st_flip_reentry(self, candle, ctx, option_type: str, structure_id: str) -> Optional[List[Any]]:
        """Attempt IMMEDIATE reentry on Supertrend flip - same candle, NEW direction (opposite of old).

        For ST flip reentry: NO MA/ADX/candle check - just find strike in 80-105 range and enter in new direction.
        The Supertrend itself IS the signal, so we trust the flip and enter immediately.
        """
        trade_date = self._trade_date(candle)
        if self._is_event_no_trade_day(trade_date) or self._is_weekly_expiry_day(trade_date):
            return None

        # Check 3:15 PM no-entry rule (but ST flip reentry is allowed if ADX >= 25 per rules)
        adx = self._get_adx_value(candle)
        if self._is_after_315pm(candle) and (adx is None or adx < self.reentry_adx_threshold):
            return None

        logger.info(f"NiftyDOS: Immediate ST flip reentry for {option_type} - finding strike 80-105")
        new_structure_id = self.build_structure_id(candle, "REENTRY_ST_FLIP")
        return self._build_entry_intents(candle, ctx, option_type, structure_id=new_structure_id)

    def _attempt_reentry(self, candle, ctx, option_type: str, structure_id: str, reason: str) -> Optional[List[Any]]:
        """Legacy reentry method - kept for compatibility."""
        if reason == "SL":
            return self._attempt_sl_reentry(candle, ctx, option_type, structure_id)
        elif reason == "TP":
            return self._attempt_immediate_reentry(candle, ctx, option_type, structure_id)
        return None

    