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
from dataclasses import replace
from datetime import date, time, timedelta
from pathlib import Path
from typing import Any, List, Optional, Set
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
    entry_945_buffer_minutes = 3  # allow delayed first-bar delivery until 9:48 IST

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
        self._pending_eval_reason: Optional[str] = None
        self._st_flip_reentry_pending: dict[str, str] = {}  # structure_id -> new_option_type (for immediate reentry on ST flip)
        # Track reentry pending after position closes at broker
        # structure_id -> {"type": "CALL"/"PUT", "reason": "TP"/"ST_FLIP", ...}
        self._reentry_after_close: dict[str, dict] = {}
        # Exit intents sent but broker may still show open qty — keep TP/SL tracking until flat.
        self._pending_exit_structure_ids: set[str] = set()
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
            filtered2 = instrument_df[combined_mask2]

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
        return 0
        # return max(50, int(self.supertrend_atr_period) * 5, int(self.adx_period) * 3)

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

    def on_candle_rollover(self, open_positions, candle, ctx):
        """No hedge rollover — MAIN and HEDGE always share the same weekly expiry."""
        return []

    # ---------- Time / event gates ----------

    def _candle_bar_minutes(self, candle: dict) -> int:
        candle_tf = str(candle.get("timeframe", self.timeframe) or "").strip()
        if candle_tf.isdigit():
            return int(candle_tf)
        if str(self.timeframe).isdigit():
            return int(self.timeframe)
        return 30

    def _candle_open_ts_ist(self, candle: dict) -> pd.Timestamp:
        """Bar open in IST. Prefer ``bucket_ts``; else UTC-naive ``timestamp`` from engine."""
        bucket = candle.get("bucket_ts")
        if bucket is not None:
            try:
                return pd.to_datetime(int(float(bucket)), unit="s", utc=True).tz_convert(IST)
            except (TypeError, ValueError):
                pass
        ts = pd.Timestamp(candle.get("timestamp"))
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC").tz_convert(IST)
        else:
            ts = ts.tz_convert(IST)
        return ts

    def _candle_close_ts_ist(self, candle: dict) -> pd.Timestamp:
        """Bar close in IST = open + candle timeframe."""
        return self._candle_open_ts_ist(candle) + pd.Timedelta(
            minutes=self._candle_bar_minutes(candle)
        )

    def _candle_ts_ist(self, candle: dict):
        """Timezone-aware IST bar-open time for OMS intents and fill hooks."""
        return self._candle_open_ts_ist(candle).to_pydatetime()

    def _candle_ts_ist_iso(self, candle: dict) -> str:
        return self._candle_open_ts_ist(candle).isoformat()

    def _coerce_candle_ts_ist(self, candle_ts: Any):
        """Normalize intent/fill timestamps to timezone-aware IST."""
        ts = pd.Timestamp(candle_ts)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC").tz_convert(IST)
        else:
            ts = ts.tz_convert(IST)
        return ts.to_pydatetime()

    def _candle_for_mixin(self, candle: dict) -> dict:
        """Candle copy with IST-naive open time for mixin wall-clock helpers."""
        out = dict(candle)
        out["timestamp"] = (
            self._candle_open_ts_ist(candle).tz_localize(None).to_pydatetime()
        )
        return out

    def _candle_wall_clock_key(self, candle: dict) -> str:
        return self._candle_open_ts_ist(candle).strftime("%Y-%m-%d %H:%M")

    def _snapshot_slot_from_candle(self, candle: dict):
        close_ts = self._candle_close_ts_ist(candle)
        return close_ts.strftime("%Y-%m-%d"), close_ts.strftime("%H-%M")

    def create_order_intent(self, *args, **kwargs):
        candle_ts = kwargs.get("candle_ts")
        if candle_ts is not None:
            kwargs["candle_ts"] = self._coerce_candle_ts_ist(candle_ts)
        return super().create_order_intent(*args, **kwargs)

    def create_hedge_intent(self, parent_sell_intent, candle, ctx):
        intent = super().create_hedge_intent(
            parent_sell_intent, self._candle_for_mixin(candle), ctx
        )
        if intent is not None:
            intent = replace(intent, candle_ts=self._candle_ts_ist(candle))
        return intent

    def create_hedge_exit_intent(self, position, candle, ctx):
        intent = super().create_hedge_exit_intent(position, candle, ctx)
        if intent is not None:
            intent = replace(intent, candle_ts=self._candle_ts_ist(candle))
        return intent

    def _bar_open_key(self, candle: dict) -> str:
        return self._candle_open_ts_ist(candle).strftime("%Y-%m-%d %H:%M")

    def _trade_date(self, candle: dict) -> date:
        return self._candle_open_ts_ist(candle).date()

    def _candle_time_ist(self, candle: dict) -> time:
        return self._candle_open_ts_ist(candle).time()

    def _is_primary_timeframe_candle(self, candle: dict) -> bool:
        candle_tf = str(candle.get("timeframe", self.timeframe) or "").strip()
        return candle_tf == str(self.timeframe).strip()

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

    def _in_close_eval_window(self, candle: dict, grace_minutes: int = 5) -> bool:
        """Check if we're within grace period after candle close."""
        close_ts = self._candle_close_ts_ist(candle)
        now_ist = pd.Timestamp.now(tz=IST)
        diff_minutes = (now_ist - close_ts).total_seconds() / 60
        tf_min = self._candle_bar_minutes(candle)
        open_ts = self._candle_open_ts_ist(candle)
        logger.info(
            "NiftyDOS: _in_close_eval_window tf=%smin open_ts=%s close_ts=%s "
            "now_ist=%s diff=%.2fmin grace=%s",
            tf_min,
            open_ts,
            close_ts,
            now_ist,
            diff_minutes,
            grace_minutes,
        )
        return diff_minutes <= grace_minutes

    def _is_after_3pm(self, candle: dict) -> bool:
        """Check if candle CLOSE time is after 3:00 PM (for EOD exit)."""
        close_ts = self._candle_close_ts_ist(candle)
        return close_ts.time() >= self.eod_exit_time

    def _is_after_315pm(self, candle: dict) -> bool:
        """Check if candle CLOSE time is after 3:15 PM (for no-entry rule)."""
        close_ts = self._candle_close_ts_ist(candle)
        return close_ts.time() >= self.no_entry_time

    def _is_915am(self, candle: dict) -> bool:
        """First 30m bar of the session (opens 9:15 IST)."""
        if not self._is_primary_timeframe_candle(candle):
            return False
        open_ts = self._candle_open_ts_ist(candle)
        return open_ts.hour == 9 and open_ts.minute == 15

    def _is_in_945_close_window(self, close_ts: pd.Timestamp) -> bool:
        """True when bar close falls in 9:45–9:48 IST (3 min buffer for delayed feed)."""
        buf = int(getattr(self, "entry_945_buffer_minutes", 3) or 3)
        close_minutes = close_ts.hour * 60 + close_ts.minute
        start = 9 * 60 + 45
        end = start + buf
        return start <= close_minutes <= end

    def _is_in_945_open_window(self, open_ts: pd.Timestamp) -> bool:
        """First session 30m bar open: 9:15–9:18 IST (matches close buffer)."""
        buf = int(getattr(self, "entry_945_buffer_minutes", 3) or 3)
        open_minutes = open_ts.hour * 60 + open_ts.minute
        start = 9 * 60 + 15
        end = start + buf
        return start <= open_minutes <= end

    def _is_945am(self, candle: dict) -> bool:
        """First 30m bar entry window: open 9:15–9:18, close 9:45–9:48 IST."""
        if not self._is_primary_timeframe_candle(candle):
            return False
        bar_min = self._candle_bar_minutes(candle)
        bar_delta = pd.Timedelta(minutes=bar_min)

        if candle.get("bucket_ts") is not None:
            open_ts = self._candle_open_ts_ist(candle)
            if not self._is_in_945_open_window(open_ts):
                return False
            close_ts = self._candle_close_ts_ist(candle)
            return self._is_in_945_close_window(close_ts)

        ts = pd.Timestamp(candle.get("timestamp"))
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC").tz_convert(IST)
        else:
            ts = ts.tz_convert(IST)

        # Timestamp may be bar open or bar close when bucket_ts is missing.
        if self._is_in_945_open_window(ts):
            return self._is_in_945_close_window(ts + bar_delta)
        if self._is_in_945_close_window(ts):
            return self._is_in_945_open_window(ts - bar_delta)
        return False

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

    def _engine_logger(self, ctx):
        if ctx and hasattr(ctx, "order_router"):
            return getattr(ctx.order_router, "engine_logger", None)
        return None

    def _log_strategy_event(self, ctx, event_type: str, message: str, **fields) -> None:
        engine_logger = self._engine_logger(ctx)
        if engine_logger:
            engine_logger.log(event_type, message, strategy_id=self.name, **fields)
        logger.info("NiftyDOS: %s", message)

    def _log_entry_skipped(self, ctx, reason: str, **fields) -> None:
        req = getattr(self, "_last_chain_fetch_requested_expiry", None)
        chain_exp = getattr(self, "_last_chain_fetch_response_expiry", None)
        msg = (
            f"entry_skipped: {reason} requested_expiry={req} chain_expiry={chain_exp}"
        )
        self._log_strategy_event(
            ctx,
            "entry_skipped",
            msg,
            reason=reason,
            requested_expiry=str(req) if req is not None else None,
            chain_expiry=str(chain_exp) if chain_exp is not None else None,
            **fields,
        )

    def _build_entry_intents(
        self,
        candle: dict,
        ctx,
        option_type: str,
        *,
        structure_id: str,
        regime: str,
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
                self._log_entry_skipped(
                    ctx,
                    f"no OTM strike prem={min_prem}-{max_prem} NEXT_WEEKLY expiry_day opt={option_type}",
                    option_type=option_type,
                    expiry_pref="NEXT_WEEKLY",
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
            self._log_entry_skipped(
                ctx,
                f"no OTM strike prem={min_prem}-{max_prem} on WEEKLY or NEXT_WEEKLY opt={option_type}",
                option_type=option_type,
                premium_min=min_prem,
                premium_max=max_prem,
            )
            return None

        strike, premium, row = result

        expiry_for_symbol = self._resolve_main_expiry(candle, ctx, expiry_pref)
        if expiry_for_symbol is None:
            logger.warning("NiftyDOS entry skipped: no weekly expiry pref=%s", expiry_pref)
            self._log_entry_skipped(
                ctx, f"no weekly expiry resolved pref={expiry_pref}", expiry_pref=expiry_pref
            )
            return None

        # Do not open a new weekly on expiry day or past expiry.
        if self._trade_date(candle) >= expiry_for_symbol:
            logger.info("NiftyDOS entry skipped: trade_date>=expiry %s", expiry_for_symbol)
            self._log_entry_skipped(
                ctx,
                f"trade_date>=expiry {expiry_for_symbol}",
                expiry=str(expiry_for_symbol),
            )
            return None

        trading_symbol = ExpiryResolver.build_option_symbol(
            candle["symbol"], expiry_for_symbol, strike, option_type, include_year=True
        )
        inst = ctx.instrument_store.intent_creation_details(
            trading_symbol, ctx.exchange, expiry_for_symbol, option_type, strike
        )
        if inst is None:
            logger.warning("NiftyDOS entry skipped: instrument missing %s", trading_symbol)
            self._log_entry_skipped(
                ctx, f"instrument missing {trading_symbol}", trading_symbol=trading_symbol
            )
            return None

        # Create intents first
        sell_intent = self.map_instrument_to_intent(
            inst=inst,
            strike_row=row,
            strategy=self.name,
            side="SELL",
            structure_id=structure_id,
            candle_ts=self._candle_ts_ist(candle),
            tag="MAIN",
            symbol=candle["symbol"],
            action="ENTRY",
        )
        hedge_intent = self.create_hedge_intent(
            parent_sell_intent=sell_intent, candle=candle, ctx=ctx
        )
        if hedge_intent is None:
            logger.warning(
                "NiftyDOS entry skipped: hedge intent missing structure=%s opt=%s ts=%s",
                structure_id,
                option_type,
                candle.get("timestamp"),
            )
            self._log_entry_skipped(
                ctx,
                f"hedge intent missing structure={structure_id} opt={option_type}",
                structure_id=structure_id,
                option_type=option_type,
            )
            return None
        hedge_entry_price = float(getattr(hedge_intent, "price", 0) or 0)

        # Prepare strategy metadata for position tracking (written to open_positions.csv)
        strategy_meta = {
            "entry_main_premium": float(premium),
            "entry_hedge_premium": hedge_entry_price,
            "structure_type": "CALL" if option_type in ("CE", "CALL") else "PUT",
            "regime": regime,
            "tp_pct": self.call_tp_pct if option_type in ("CE", "CALL") else self.put_tp_pct,
            "sl_pct": self.call_sl_pct if option_type in ("CE", "CALL") else self.put_sl_pct,
            "margin_per_lot": self.margin_per_lot,
            "hedge_distance_points": self.hedge_distance_points,
            "signal_ts_ist": self._candle_open_ts_ist(candle).strftime("%Y-%m-%d %H:%M:%S"),
            "signal_tz": "Asia/Kolkata",
        }
        sell_intent = replace(sell_intent, metadata_extras=strategy_meta)
        hedge_intent = replace(hedge_intent, metadata_extras=strategy_meta)
        self._entry_signaled_keys.add(signal_key)

        # Store entry prices for both MAIN and HEDGE for TP/SL tracking
        self._structure_main_entry_price[structure_id] = float(premium)
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

    def _underlying_symbol(self, candle: dict) -> str:
        return str(candle.get("symbol") or "")

    def _strategy_open_positions(
        self,
        ctx,
        candle: Optional[dict] = None,
        *,
        underlying: Optional[str] = None,
        structure_id: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> list:
        """Open broker legs for this strategy only (ignore other strategies on same underlying)."""
        if not ctx or not ctx.position_store:
            return []
        und = underlying if underlying is not None else self._underlying_symbol(candle or {})
        positions = ctx.position_store.get_open_positions(
            underlying=und,
            strategy=self.name,
        ) or []
        tag_u = str(tag or "").upper() if tag else None
        out = []
        for pos in positions:
            if str(getattr(pos, "strategy", "") or "") != self.name:
                continue
            if structure_id and getattr(pos, "structure_id", None) != structure_id:
                continue
            pos_tag = str(getattr(pos, "tag", "") or "").upper()
            if tag_u and pos_tag != tag_u:
                continue
            if int(getattr(pos, "net_qty", 0) or 0) == 0:
                continue
            out.append(pos)
        return out

    def _has_open_main_for_strategy(self, candle: dict, ctx) -> bool:
        return bool(self._strategy_open_positions(ctx, candle, tag="MAIN"))

    def _structure_still_open_at_broker(self, structure_id: str, candle, ctx) -> bool:
        if not structure_id:
            return False
        still_open = self._strategy_open_positions(
            ctx, candle, structure_id=structure_id
        )
        if still_open:
            logger.debug(
                "NiftyDOS: structure %s still open for strategy=%s legs=%s",
                structure_id,
                self.name,
                [getattr(p, "tag", "?") for p in still_open],
            )
        return bool(still_open)

    def _is_structure_flat_at_broker(self, structure_id: str, candle, ctx) -> bool:
        return not self._structure_still_open_at_broker(structure_id, candle, ctx)

    def _st_flip_detected(self, candle: dict) -> bool:
        st = self._get_supertrend_signal(candle)
        if st is None or self._prev_st_signal is None:
            return False
        return self._prev_st_signal != st

    def _commit_st_signal_for_bar(self, candle: dict, st_signal: str) -> None:
        if not self._is_primary_timeframe_candle(candle):
            return
        self._prev_st_signal = st_signal

    def _eval_signal_reason(self, candle: dict) -> Optional[str]:
        """Return a short reason when this bar should emit signal_generated / run on_candle."""
        candle_tf = str(candle.get("timeframe", self.timeframe) or "").strip()

        if candle_tf == "5":
            if self._reentry_after_close:
                reasons = {
                    str(info.get("reason") or "")
                    for info in self._reentry_after_close.values()
                }
                if "TP" in reasons:
                    return "TP_REENTRY"
                if "ST_FLIP" in reasons:
                    return "ST_FLIP_REENTRY"
            # 5m runs for TP/SL monitoring; signal_generated only on reentry pending.
            return None

        if not self._is_primary_timeframe_candle(candle):
            return None

        if self._reentry_after_close:
            reasons = {
                str(info.get("reason") or "")
                for info in self._reentry_after_close.values()
            }
            if "TP" in reasons:
                return "TP_REENTRY"
            if "ST_FLIP" in reasons:
                return "ST_FLIP_REENTRY"

        if self._sl_hit_structure:
            return "SL_REENTRY"

        if self._is_945am(candle):
            return "9:45_ENTRY"

        if self._st_flip_detected(candle):
            return "ST_FLIP"

        return None

    def should_evaluate(self, candle):
        logger.info(
            "NiftyDOS: should_evaluate tf=%s ts_ist=%s raw_ts=%s",
            candle.get("timeframe"),
            self._candle_ts_ist_iso(candle),
            candle.get("timestamp"),
        )
        # Live: only eval shortly after bar close. Backtest: every closed bar.
        # For dummy feed testing, allow eval if candle is closed (has bucket_ts)
        if RUN_MODE != RunMode.BACKTEST:
            grace_minutes = 5
            if self._is_primary_timeframe_candle(candle):
                open_ts = self._candle_open_ts_ist(candle)
                if open_ts.hour == 9 and open_ts.minute == 15:
                    grace_minutes = max(
                        grace_minutes,
                        int(getattr(self, "entry_945_buffer_minutes", 3) or 3),
                    )
            if not self._in_close_eval_window(candle, grace_minutes=grace_minutes):
                # Allow dummy feed candles (simulated timestamps) to pass eval window
                if candle.get("bucket_ts") is not None and candle.get("session_close_partial") is not True:
                    logger.debug("NiftyDOS: allowing dummy feed candle past eval window")
                else:
                    logger.info(f"NiftyDOS: should_evaluate False - not in eval window")
                    return False

        trade_date = self._trade_date(candle)
        if self._is_event_no_trade_day(trade_date):
            logger.info(f"NiftyDOS: should_evaluate False - event no trade day")
            return False

        # On expiry day, allow evaluation - _build_entry_intents will handle NEXT_WEEKLY expiry
        # The original logic blocked all expiry day entries, but _build_entry_intents forces
        # NEXT_WEEKLY expiry on expiry day, so we should allow evaluation.

        # Detect if this is a 5-min candle (extra timeframe for TP/SL monitoring)
        candle_tf = str(candle.get("timeframe", self.timeframe) or "").strip()
        is_5min_tf = (candle_tf == "5")
        logger.info(f"NiftyDOS: 5min timeframe check is_5min_tf={is_5min_tf} candle_tf={candle_tf} candle:{candle}")
        # For 5-min timeframe: only evaluate if we have an open position (for TP/SL monitoring)
        # Skip Supertrend signal check - TP/SL doesn't need trend signal
        if is_5min_tf:
            monitor = bool(
                self._structure_main_entry_price
                or self._pending_exit_structure_ids
                or self._reentry_after_close
            )
            logger.info(
                "NiftyDOS: should_evaluate (5min) monitor=%s tracking=%s pending_exit=%s reentry=%s",
                monitor,
                list(self._structure_main_entry_price.keys()),
                list(self._pending_exit_structure_ids),
                list(self._reentry_after_close.keys()),
            )
            return monitor

        st_signal = self._get_supertrend_signal(candle)
        if st_signal is None:
            logger.info("NiftyDOS: should_evaluate False - no ST signal")
            return False

        eval_key = self._bar_open_key(candle)
        if eval_key in self._evaluated_signal_keys:
            logger.info(f"NiftyDOS: should_evaluate False - already evaluated key={eval_key}")
            return False

        reason = self._eval_signal_reason(candle)
        if not reason:
            self._commit_st_signal_for_bar(candle, st_signal)
            self._pending_eval_reason = None
            logger.info(
                "NiftyDOS: should_evaluate False (30m) - no actionable signal st=%s",
                st_signal,
            )
            return False

        self._evaluated_signal_keys.add(eval_key)
        self._pending_eval_reason = reason
        self._commit_st_signal_for_bar(candle, st_signal)
        logger.info(
            "NiftyDOS: should_evaluate True - key=%s reason=%s st_signal=%s",
            eval_key,
            reason,
            st_signal,
        )
        return True

    def eval_signal_log_message(self, candle) -> Optional[str]:
        reason = self._pending_eval_reason or self._eval_signal_reason(candle)
        if not reason:
            return None
        st_signal = self._get_supertrend_signal(candle)
        ma_signal = self._get_ma_signal(candle)
        adx = self._get_adx_value(candle)
        period = int(getattr(self, "sma_period", 9) or 9)
        return (
            f"DOS Signal ({reason}): ST={st_signal} MA={ma_signal} ADX={adx} "
            f"close={candle.get('close')} sma{period}={candle.get(f'sma{period}')} "
            f"timeframe={getattr(self, 'timeframe', '')}"
        )

    def on_candle(self, candle, ctx):
        logger.info(
            "NiftyDOS: on_candle tf=%s ts_ist=%s close=%s st=%s",
            candle.get("timeframe"),
            self._candle_ts_ist_iso(candle),
            candle.get("close"),
            self._get_supertrend_signal(candle),
        )
        trade_date = self._trade_date(candle)
        if self._is_event_no_trade_day(trade_date):
            return None

        # Determine candle timeframe
        candle_tf = str(candle.get("timeframe", self.timeframe) or "").strip()
        is_primary_tf = (candle_tf == str(self.timeframe).strip())
        is_5min_tf = (candle_tf == "5")

        # On expiry day, allow entry - _build_entry_intents will force NEXT_WEEKLY expiry
        # (No longer blocking expiry day entries here)

        # ===== CHECK PENDING REENTRIES AFTER BROKER CLOSE =====
        self._finalize_pending_exits(candle, ctx)
        reentry_intents = self._check_and_execute_pending_reentries(candle, ctx)
        if reentry_intents:
            return reentry_intents

        st_signal = self._get_supertrend_signal(candle)
        if st_signal is None:
            return None

        # ===== TP/SL CHECK ON 5-MIN CANDLES =====
        # Check TP/SL on EVERY 5-min candle (for intrabar exit)
        if is_5min_tf:
            exit_intents = self._check_tp_sl_on_5min(candle, ctx)
            if exit_intents:
                return exit_intents
            # 5-min candles are ONLY for TP/SL monitoring - skip signal generation
            return None

        # ===== REENTRY LOGIC =====
        # TP reentry: immediate on SAME 5-min candle (handled in _check_tp_sl_on_5min via on_position_exit)
        # ST flip reentry: immediate on SAME 5-min candle (handled in should_exit -> on_position_exit)
        # SL reentry: ONLY on 30-min (primary) timeframe, on NEXT candle after SL hit

        # Handle SL reentry from PREVIOUS candle - ONLY on primary timeframe (30-min)
        if is_primary_tf and self._sl_hit_structure:
            for struct_id, opt_type in list(self._sl_hit_structure.items()):
                if self._structure_still_open_at_broker(struct_id, candle, ctx):
                    logger.debug(
                        "NiftyDOS: SL reentry deferred for %s - position still open at broker",
                        struct_id,
                    )
                    continue
                logger.info(
                    "NiftyDOS: Checking SL reentry for %s on next 30-min candle",
                    opt_type,
                )
                if self._is_after_315pm(candle):
                    logger.info("NiftyDOS: SL reentry blocked after 15:15 PM")
                    self._sl_hit_structure.pop(struct_id, None)
                    continue
                reentry_intents = self._attempt_sl_reentry(candle, ctx, opt_type, struct_id)
                self._sl_hit_structure.pop(struct_id, None)
                if reentry_intents:
                    return reentry_intents

        # Check 3:15 PM no-entry rule for initial entry (allows TP reentry via on_position_exit)
        adx = self._get_adx_value(candle)
        if self._is_after_315pm(candle) and (adx is None or adx < self.reentry_adx_threshold):
            # But allow reentry if we have pending TP reentry (handled in on_position_exit)
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

        # Check 15:15 PM no-entry rule - block initial entry and 9:45 AM entry
        # TP reentry is handled in on_position_exit (immediate, same candle)
        # SL reentry is blocked above; ST flip reentry blocked in _attempt_st_flip_reentry
        if self._is_after_315pm(candle):
            return None

        # Check 9:45 AM rule - if no open position, create position on Supertrend direction
        if self._is_945am(candle):
            logger.info(f"NiftyDOS: 9:45 CHECK PASSED ts={candle.get('timestamp')} bucket_ts={candle.get('bucket_ts')} st_signal={st_signal}")
            if not self._has_open_main_for_strategy(candle, ctx):
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
                    return self._build_entry_intents(candle, ctx, option_type, structure_id=structure_id, regime=regime)

        # New entry on Supertrend signal (no MA/ADX filter) - ONLY on primary timeframe (30-min)
        if not is_primary_tf:
            return None

        if self._has_open_main_for_strategy(candle, ctx):
            logger.info(
                "NiftyDOS: Skipping new entry - MAIN position already open for strategy=%s",
                self.name,
            )
            return None

        if self._pending_eval_reason != "ST_FLIP":
            logger.info(
                "NiftyDOS: Skipping 30m entry - eval reason=%s (need ST_FLIP)",
                self._pending_eval_reason,
            )
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
        return self._build_entry_intents(candle, ctx, option_type, structure_id=structure_id, regime=regime)

    # ---------- Exit / TP-SL Management ----------

    def _clear_structure_tracking(self, structure_id: str, *, clear_sl_pending: bool = False) -> None:
        if not structure_id:
            return
        self._structure_main_entry_price.pop(structure_id, None)
        self._structure_hedge_entry_price.pop(structure_id, None)
        self._structure_type.pop(structure_id, None)
        self._pending_exit_structure_ids.discard(structure_id)
        if clear_sl_pending:
            self._sl_hit_structure.pop(structure_id, None)

    def _finalize_pending_exits(self, candle, ctx) -> None:
        """Drop TP/SL tracking once broker is flat; keep SL reentry flags for 30m eval."""
        if not self._pending_exit_structure_ids:
            return
        for structure_id in list(self._pending_exit_structure_ids):
            if self._structure_still_open_at_broker(structure_id, candle, ctx):
                continue
            self._pending_exit_structure_ids.discard(structure_id)
            self._structure_main_entry_price.pop(structure_id, None)
            self._structure_hedge_entry_price.pop(structure_id, None)
            self._structure_type.pop(structure_id, None)
            logger.info(
                "NiftyDOS: Broker flat after exit for structure %s strategy=%s (SL reentry=%s)",
                structure_id,
                self.name,
                structure_id in self._sl_hit_structure,
            )

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
        # For live/paper, fetch LTP via Dhan marketfeed (more efficient than full option chain)
        if ctx and hasattr(ctx, "order_router"):
            try:
                # Get security ID from instrument
                instrument = position.instrument
                security_id = getattr(instrument, "instrument_id", None)
                if not security_id:
                    # Fallback: try to get from trading symbol via instrument store
                    if ctx and ctx.instrument_store:
                        pass  # Could resolve here if needed

                if security_id:
                    # Access marketfeed via order_router -> broker -> source
                    order_router = ctx.order_router
                    broker = getattr(order_router, "broker", None)
                    if broker and hasattr(broker, "_source"):
                        source = broker._source
                        marketfeed = getattr(source, "_marketfeed", None)
                        if marketfeed:
                            # Fetch LTP for the option instrument
                            # NSE_FNO segment for Nifty options
                            instruments = {"NSE_FNO": [int(security_id)]}
                            response = marketfeed.ltp(instruments)
                            if response.get("status") == "success":
                                data = response.get("data", {})
                                nse_fno = data.get("NSE_FNO", {})
                                sec_data = nse_fno.get(str(security_id), {})
                                ltp = sec_data.get("last_price")
                                if ltp is not None:
                                    premium = float(ltp)
                                    logger.info(f"NiftyDOS: 5min premium fetch (marketfeed) struct={position.structure_id} strike={instrument.strike} opt={instrument.option_type} premium={premium:.2f}")
                                    return premium
            except Exception as e:
                logger.warning(f"NiftyDOS: Failed to fetch premium from marketfeed: {e}")

        # Fallback: try option chain service (for cases where marketfeed not available)
        if ctx and hasattr(ctx, "option_chain_service"):
            try:
                strike = position.instrument.strike
                option_type = position.instrument.option_type
                expiry = position.instrument.expiry

                # Try to get cached chain first (from previous fetch in this candle)
                cached_chain = getattr(self, "_last_option_chain", None)
                if cached_chain is not None:
                    row = self._strike_row_from_chain(cached_chain, strike, option_type)
                    if row is not None:
                        px = self._execution_price_from_chain_row(row, option_type, side="BUY")
                        if px is not None and px > 0:
                            return float(px)

                # Fetch fresh chain from service
                params = {
                    "exchange": ctx.exchange,
                    "interval": self._option_data_interval(),
                    "expiry_code": expiry,
                    "strike": [str(int(float(strike)))],
                    "option_type": option_type,
                    "instrument": "OPTIDX",
                    "exchangeSegment": "NSE_FNO",
                    "expiry_flag": self._dhan_expiry_flag(),
                    "securityId": self._dhan_option_security_id(),
                }
                chain = ctx.option_chain_service.get_chain(api=self.api, ctx=ctx, params=params)
                if chain is not None:
                    self._last_option_chain = chain
                    row = self._strike_row_from_chain(chain, strike, option_type)
                    if row is not None:
                        px = self._execution_price_from_chain_row(row, option_type, side="BUY")
                        if px is not None and px > 0:
                            premium = float(px)
                            logger.info(f"NiftyDOS: 5min premium fetch (option_chain) struct={position.structure_id} strike={strike} opt={option_type} premium={premium:.2f}")
                            return premium
            except Exception as e:
                logger.warning(f"NiftyDOS: Failed to fetch premium from option chain: {e}")
        return None

    def _get_structure_positions(self, position, ctx):
        """Get both MAIN and HEDGE positions for a structure."""
        main_pos = position
        hedge_pos = None
        if ctx and ctx.position_store:
            hedge_pos = ctx.position_store.get_hedge_for(main_pos)

        # Fallback: if metadata-based lookup fails (e.g. after broker reconcile
        # where hedge position lost its tag/structure_id), find hedge by matching
        # structure characteristics: same underlying, expiry, option_type, and
        # strike = main_strike +/- hedge_distance_points (same option type, long)
        if hedge_pos is None and ctx and ctx.position_store:
            hedge_pos = self._find_hedge_by_structure(main_pos, ctx)

        return main_pos, hedge_pos

    def _find_hedge_by_structure(self, main_pos, ctx):
        """Find hedge position by matching structure characteristics.

        Hedge is a LONG option with:
        - Same underlying, expiry, option_type as MAIN
        - Strike = main_strike + hedge_distance_points (CE) or - hedge_distance_points (PE)
        - Positive qty (long)
        """
        if not main_pos or main_pos.net_qty == 0:
            return None

        main_inst = getattr(main_pos, "instrument", None)
        if not main_inst:
            return None

        main_strike = getattr(main_inst, "strike", None)
        main_option_type = getattr(main_inst, "option_type", "")
        main_expiry = getattr(main_inst, "expiry", None)
        underlying = str(getattr(main_inst, "custom_symbol", "") or "").split()[0].upper()

        if main_strike is None or not main_option_type or main_expiry is None:
            return None

        try:
            main_strike_f = float(main_strike)
        except (TypeError, ValueError):
            return None

        gap = int(getattr(self, "hedge_distance_points", 500) or 500)
        if main_option_type.upper() in ("CE", "CALL"):
            hedge_strike = main_strike_f + gap
        else:
            hedge_strike = main_strike_f - gap

        # Look for matching hedge position (this strategy only)
        for pos in ctx.position_store.positions.values():
            if str(getattr(pos, "strategy", "") or "") != self.name:
                continue
            if str(getattr(pos, "tag", "") or "").upper() != "HEDGE":
                continue
            if pos.net_qty <= 0:
                continue
            inst = getattr(pos, "instrument", None)
            if not inst:
                continue
            if getattr(inst, "option_type", "").upper() != main_option_type.upper():
                continue
            if getattr(inst, "expiry", None) != main_expiry:
                continue
            # Check underlying match
            pos_underlying = str(getattr(inst, "custom_symbol", "") or "").split()[0].upper()
            if pos_underlying != underlying:
                continue
            # Check strike match
            pos_strike = getattr(inst, "strike", None)
            try:
                if pos_strike is not None and abs(float(pos_strike) - hedge_strike) < 1:
                    return pos
            except (TypeError, ValueError):
                continue

        return None

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
        # net_qty from broker is already total quantity (lots × lot_size), so don't multiply by lot_size again
        qty = abs(int(main_position.net_qty or 0))
        main_pnl = (main_entry - main_current) * qty

        # Calculate HEDGE P&L if hedge exists (long: profit when premium rises)
        hedge_pnl = 0.0
        if hedge_position and hedge_position.net_qty != 0:
            hedge_current = self._get_current_premium(hedge_position, candle, ctx)
            if hedge_current is not None and hedge_entry > 0:
                hedge_qty = abs(int(hedge_position.net_qty or 0))
                hedge_pnl = (hedge_current - hedge_entry) * hedge_qty

        structure_pnl = main_pnl + hedge_pnl
        logger.info(f"NiftyDOS: 5min structure P&L struct={structure_id} main_premium={main_current:.2f} main_entry={main_entry:.2f} main_pnl={main_pnl:.2f} hedge_pnl={hedge_pnl:.2f} total_pnl={structure_pnl:.2f}")
        return structure_pnl

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
        open_positions = self._strategy_open_positions(ctx, candle, tag="MAIN")

        exit_intents = []
        for position in open_positions:
            if position.tag != "MAIN":
                continue

            structure_id = position.structure_id

            if structure_id in self._pending_exit_structure_ids:
                logger.debug(
                    "NiftyDOS: 5min skipping TP/SL for %s - exit already pending",
                    structure_id,
                )
                continue

            # Skip if structure tracking missing (should not happen while position open)
            if structure_id not in self._structure_main_entry_price:
                logger.debug(f"NiftyDOS: 5min skipping TP/SL for {structure_id} - tracking already cleaned")
                continue

            # Check TP/SL
            tp_sl = self._check_tp_sl(position, candle, ctx)
            if tp_sl:
                opt_type = self._structure_type.get(structure_id, "")
                if tp_sl == "SL":
                    self._sl_hit_structure[structure_id] = opt_type
                    logger.info(f"NiftyDOS: 5min SL hit for structure {structure_id}, reentry on next candle")
                elif tp_sl == "TP":
                    self._tp_hit_pending[structure_id] = opt_type
                    logger.info(f"NiftyDOS: 5min TP hit for structure {structure_id}, immediate reentry")

                # Generate exit intents
                intents = self.on_position_exit(position, candle, ctx) or []
                exit_intents.extend(intents)
                continue  # Skip EOD check if TP/SL already hit

            # Check EOD exit after 3pm (also on 5-min candles)
            if self._check_eod_exit(position, candle, ctx):
                logger.info(f"NiftyDOS: 5min EOD exit for structure {structure_id}")
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
            structure_id = position.structure_id
            if structure_id in self._pending_exit_structure_ids:
                logger.debug(
                    "NiftyDOS: 30min skipping exit check for %s - exit already pending",
                    structure_id,
                )
                return False

            if structure_id not in self._structure_main_entry_price:
                logger.debug(f"NiftyDOS: 30min skipping exit check for {structure_id} - tracking already cleaned")
                return False

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
        """Generate exit intents for TP/SL/ST-flip hits. Reentry is deferred until position is actually closed at broker."""
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
                candle_ts=self._candle_ts_ist(candle),
                structure_id=position.structure_id,
                tag="MAIN_EXIT",
                symbol=candle["symbol"],
                action="EXIT",
            )
        )
        hedge_exit = self.create_hedge_exit_intent(position, candle, ctx)
        if hedge_exit:
            intents.append(hedge_exit)

        structure_id = position.structure_id
        self._pending_exit_structure_ids.add(structure_id)

        # Track reentry type pending after exit - do NOT execute yet (TP/ST only).
        # SL reentry stays in _sl_hit_structure and runs on the next 30-min bar after flat.
        exit_reentry_type = None
        if structure_id in self._tp_hit_pending:
            exit_reentry_type = self._tp_hit_pending.pop(structure_id)
            reentry_reason = "TP"
        elif structure_id in self._st_flip_reentry_pending:
            exit_reentry_type = self._st_flip_reentry_pending.pop(structure_id)
            reentry_reason = "ST_FLIP"
        elif structure_id in self._sl_hit_structure:
            logger.info(
                "NiftyDOS: Exit triggered (SL) for %s; SL reentry on next 30-min after broker flat",
                structure_id,
            )

        if exit_reentry_type:
            self._reentry_after_close[structure_id] = {
                "type": exit_reentry_type,
                "reason": reentry_reason,
                "original_strike": position.instrument.strike,
                "original_option_type": position.instrument.option_type,
            }
            logger.info(
                "NiftyDOS: Exit triggered (%s) for %s, reentry pending after broker close",
                reentry_reason,
                structure_id,
            )

        return intents

    def cleanup_manual_close(self, structure_id: str) -> None:
        """
        Clean up strategy tracking state when a position is manually closed at broker.

        Called by engine after detecting manual broker flat via reconciliation.
        Removes stale entry prices, reentry tracking, and structure type.
        """
        if not structure_id:
            return

        # Clean up tracking dicts
        self._structure_main_entry_price.pop(structure_id, None)
        self._structure_hedge_entry_price.pop(structure_id, None)
        self._structure_type.pop(structure_id, None)
        self._pending_exit_structure_ids.discard(structure_id)
        self._sl_hit_structure.pop(structure_id, None)
        self._tp_hit_pending.pop(structure_id, None)
        self._st_flip_reentry_pending.pop(structure_id, None)
        # Also clear any pending reentry after close
        self._reentry_after_close.pop(structure_id, None)

        logger.info(f"NiftyDOS: Cleaned up manual close for structure {structure_id}")

    def _check_and_execute_pending_reentries(self, candle, ctx) -> Optional[List[Any]]:
        """
        Check if positions with pending reentry have been closed at broker.
        If closed, execute the reentry.

        Called at the start of on_candle (every closed bar).
        """
        if not self._reentry_after_close:
            return None

        if not ctx or not ctx.position_store:
            return None

        executed_intents = []
        # Iterate over copy since we modify the dict
        for structure_id, reentry_info in list(self._reentry_after_close.items()):
            if self._structure_still_open_at_broker(structure_id, candle, ctx):
                logger.debug(
                    "NiftyDOS: Reentry for %s deferred - %s leg(s) still open at broker",
                    structure_id,
                    self.name,
                )
                continue

            logger.info(
                "NiftyDOS: %s structure %s flat at broker, executing reentry (%s)",
                self.name,
                structure_id,
                reentry_info["reason"],
            )
            reentry_type = reentry_info["type"]
            reason = reentry_info["reason"]

            # Clear the pending reentry
            self._reentry_after_close.pop(structure_id, None)

            # Execute appropriate reentry method based on reason
            reentry_intents = None
            if reason == "TP":
                reentry_intents = self._attempt_immediate_reentry(candle, ctx, reentry_type, structure_id)
            elif reason == "ST_FLIP":
                reentry_intents = self._attempt_st_flip_reentry(candle, ctx, reentry_type, structure_id)

            if reentry_intents:
                executed_intents.extend(reentry_intents)

        return executed_intents if executed_intents else None

    def restore_state_on_startup(self, position_manager, intent_store, ctx=None) -> None:
        """
        Restore strategy tracking state after engine restart/reconciliation.

        Called by engine's _restore_strategies_after_reconcile.
        Rebuilds internal tracking dicts from broker positions.
        """
        # Use engine_logger from ctx if available for JSON log file
        engine_logger = None
        if ctx and hasattr(ctx, "order_router"):
            engine_logger = getattr(ctx.order_router, "engine_logger", None)

        def _log(msg):
            if engine_logger:
                engine_logger.log("strategy_debug", msg, strategy_id=self.name)
            logger.info(f"NiftyDOS: {msg}")

        _log(f"restore_state_on_startup called, ctx={ctx is not None}")
        # Build a minimal context with position_store
        if ctx is None:
            from types import SimpleNamespace
            ctx = SimpleNamespace(
                position_store=position_manager,
                symbol=getattr(self, "underlying_symbols", ["NIFTY"])[0],
            )
        elif not hasattr(ctx, "position_store"):
            ctx.position_store = position_manager
            ctx.symbol = getattr(self, "underlying_symbols", ["NIFTY"])[0]

        _log(f"calling sync_tracking_from_broker with ctx.position_store={ctx.position_store is not None}")
        self.sync_tracking_from_broker(ctx)

    def sync_tracking_from_broker(self, ctx) -> int:
        """
        Restore strategy tracking dicts from broker positions after restart/reconciliation.

        Reads open positions from position_store and rebuilds:
        - _structure_main_entry_price
        - _structure_hedge_entry_price
        - _structure_type
        - _sl_hit_structure, _tp_hit_pending, _st_flip_reentry_pending (cleared)

        Returns number of structures restored.
        """
        engine_logger = None
        if ctx and hasattr(ctx, "order_router"):
            engine_logger = getattr(ctx.order_router, "engine_logger", None)

        def _log(msg):
            if engine_logger:
                engine_logger.log("strategy_debug", msg, strategy_id=self.name)
            logger.info(f"NiftyDOS: {msg}")

        _log(f"sync_tracking_from_broker called, ctx={ctx is not None}, position_store={ctx.position_store is not None if ctx else None}")
        if not ctx or not ctx.position_store:
            _log("sync_tracking_from_broker early return - ctx or position_store missing")
            return 0

        restored = 0
        try:
            open_positions = self._strategy_open_positions(
                ctx,
                underlying=str(getattr(ctx, "symbol", "") or ""),
                tag="MAIN",
            )
            _log(f"found {len(open_positions)} open MAIN positions for strategy={self.name}")

            for position in open_positions:
                _log(f"  checking position: symbol={getattr(position.instrument, 'trading_symbol', 'unknown')} tag={getattr(position, 'tag', 'none')} structure_id={getattr(position, 'structure_id', 'none')} net_qty={getattr(position, 'net_qty', 0)}")
                if position.tag != "MAIN":
                    _log(f"  skipping - tag is {position.tag}, not MAIN")
                    continue

                structure_id = getattr(position, "structure_id", None)
                if not structure_id:
                    _log(f"  skipping - no structure_id")
                    continue

                # Get MAIN entry price from position's avg_price (broker fill price)
                main_entry = getattr(position, "avg_price", None) or getattr(position, "entry_price", None)
                if main_entry is None:
                    _log(f"  skipping - no entry price (avg_price={getattr(position, 'avg_price', 'none')})")
                    continue

                # Find hedge position for same structure
                hedge_position = None
                if ctx.position_store:
                    hedge_position = ctx.position_store.get_hedge_for(position)

                hedge_entry = None
                if hedge_position and hedge_position.net_qty != 0:
                    hedge_entry = getattr(hedge_position, "avg_price", None) or getattr(hedge_position, "entry_price", None)

                # Determine option type
                opt_type = str(getattr(position.instrument, "option_type", "") or "").upper()
                if opt_type in ("CE", "CALL"):
                    structure_type = "CALL"
                elif opt_type in ("PE", "PUT"):
                    structure_type = "PUT"
                else:
                    structure_type = ""

                # Restore tracking
                self._structure_main_entry_price[structure_id] = float(main_entry)
                if hedge_entry is not None:
                    self._structure_hedge_entry_price[structure_id] = float(hedge_entry)
                if structure_type:
                    self._structure_type[structure_id] = structure_type

                # Clear any stale reentry flags (fresh start after restart)
                self._sl_hit_structure.pop(structure_id, None)
                self._tp_hit_pending.pop(structure_id, None)
                self._st_flip_reentry_pending.pop(structure_id, None)

                restored += 1
                hedge_log = f"{float(hedge_entry):.2f}" if hedge_entry is not None else "N/A"
                _log(
                    f"Restored tracking for structure {structure_id} "
                    f"main_entry={float(main_entry):.2f} hedge_entry={hedge_log} type={structure_type}"
                )

        except Exception as e:
            _log(f"Failed to sync tracking from broker: {e}")

        _log(f"sync_tracking_from_broker completed, restored={restored} structures")
        return restored

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

        if self._has_open_main_for_strategy(candle, ctx):
            logger.info(
                "NiftyDOS: SL reentry skipped - MAIN already open for strategy=%s",
                self.name,
            )
            return None

        # All conditions met - reenter
        logger.info(f"NiftyDOS: SL reentry conditions met for {option_type}")
        new_structure_id = self.build_structure_id(candle, "REENTRY_SL")
        return self._build_entry_intents(candle, ctx, option_type, structure_id=new_structure_id, regime="REENTRY_SL")

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

        if self._has_open_main_for_strategy(candle, ctx):
            logger.info(
                "NiftyDOS: TP reentry skipped - MAIN already open for strategy=%s",
                self.name,
            )
            return None

        logger.info(f"NiftyDOS: Immediate TP reentry for {option_type} - finding strike 80-105")
        new_structure_id = self.build_structure_id(candle, "REENTRY_TP")
        return self._build_entry_intents(candle, ctx, option_type, structure_id=new_structure_id, regime="REENTRY_TP")

    def _attempt_st_flip_reentry(self, candle, ctx, option_type: str, structure_id: str) -> Optional[List[Any]]:
        """Attempt IMMEDIATE reentry on Supertrend flip - same candle, NEW direction (opposite of old).

        For ST flip reentry: NO MA/ADX/candle check - just find strike in 80-105 range and enter in new direction.
        The Supertrend itself IS the signal, so we trust the flip and enter immediately.
        """
        trade_date = self._trade_date(candle)
        if self._is_event_no_trade_day(trade_date) or self._is_weekly_expiry_day(trade_date):
            return None

        # Block ST flip reentry after 15:15 PM (only TP reentry allowed)
        if self._is_after_315pm(candle):
            logger.info(f"NiftyDOS: ST flip reentry blocked after 15:15 PM")
            return None

        if self._has_open_main_for_strategy(candle, ctx):
            logger.info(
                "NiftyDOS: ST flip reentry skipped - MAIN already open for strategy=%s",
                self.name,
            )
            return None

        logger.info(f"NiftyDOS: Immediate ST flip reentry for {option_type} - finding strike 80-105")
        new_structure_id = self.build_structure_id(candle, "REENTRY_ST_FLIP")
        return self._build_entry_intents(candle, ctx, option_type, structure_id=new_structure_id, regime="REENTRY_ST_FLIP")

    def _attempt_reentry(self, candle, ctx, option_type: str, structure_id: str, reason: str) -> Optional[List[Any]]:
        """Legacy reentry method - kept for compatibility."""
        if reason == "SL":
            return self._attempt_sl_reentry(candle, ctx, option_type, structure_id)
        elif reason == "TP":
            return self._attempt_immediate_reentry(candle, ctx, option_type, structure_id)
        return None

    