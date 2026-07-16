import logging
from datetime import date
from pathlib import Path
from typing import Any, List, Optional, Tuple

import pandas as pd
import talib

from run.config import RUN_MODE, RunMode
from core.strategies.base import BaseStrategy
from core.strategies.IndiaMktMixins import IST, IndiaMktMixins
from core.strategies.indicator_helpers import (
    add_ema_high_low,
    default_persisted_keys_for_ema_high_low,
    default_persisted_keys_for_rsi,
)
from core.utils.expiry_resolver import ExpiryResolver
from core.utils.indicator_history import nse_60m_bar_close_eval_window
from core.utils.option_chain_snapshot_log import log_option_chain_snapshot

logger = logging.getLogger(__name__)

# (class flag attr, MAIN expiry_pref, structure_id suffix)
LEG_SPECS: Tuple[Tuple[str, str, str], ...] = (
    ("mini_leaps_enabled", "LEAPS_ROLL", ""),
    ("quarterly_leaps_enabled", "QUARTERLY", ":QTR"),
)


class LeapsQuarterly(IndiaMktMixins, BaseStrategy):
    """
    LEAPS RSI option selling with optional dual MAIN legs:
    - mini LEAPS (LEAPS_ROLL monthly rollover expiry)
    - quarterly LEAPS (Mar/Jun/Sep/Dec last Tuesday)
    Each MAIN leg has its own monthly hedge (unchanged hedge rules).
    """

    name = "LEAPS_RSI"
    underlying_symbols = ["NIFTY"]
    timeframe = "60"
    required_context = ["option_chain"]
    api = "DHAN"
    expiryType = "LEAPS_ROLL"
    option_chain_strike_step = 500
    option_chain_ideal_premium = 350
    hedge_monthly_rollover_after_calendar_day = 15
    hedge_monthly_expiry_weekday = 1
    ema_period = 8

    # Toggle which MAIN+HEDGE bundles to place on entry (overridable via strategy.yaml legs:).
    mini_leaps_enabled = True
    quarterly_leaps_enabled = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._leaps_snapshot_logged_slots: set[str] = set()
        self._leaps_hedge_snapshot_logged_slots: set[str] = set()
        self._entry_signaled_keys: set[str] = set()
        self._evaluated_signal_keys: set[str] = set()
        self._snapshot_expiry_pref: Optional[str] = None
        self._load_legs_config_from_yaml()

    def _load_legs_config_from_yaml(self) -> None:
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
            logger.warning("LEAPS_RSI: could not read strategy.yaml legs: %s", exc)
            return
        legs = raw.get("legs") or {}
        mini = legs.get("mini_leaps") or {}
        qtr = legs.get("quarterly_leaps") or {}
        if "enabled" in mini:
            self.mini_leaps_enabled = bool(mini.get("enabled"))
        if "enabled" in qtr:
            self.quarterly_leaps_enabled = bool(qtr.get("enabled"))

    def get_warmup_period(self):
        return 0

    def prepare_indicators(self, df):
        df["rsi"] = talib.RSI(df["close"], 14)
        df["prev_rsi"] = df["rsi"].shift(1)
        df = add_ema_high_low(df, period=int(getattr(self, "ema_period", 8) or 8))
        return df

    def requires_live_rsi_patch(self) -> bool:
        return True

    def persisted_indicator_keys(self):
        return (
            default_persisted_keys_for_rsi()
            + default_persisted_keys_for_ema_high_low()
        )

    def resolve_hedge_expiry(self, trade_date: date, parent_expiry=None):
        """Monthly hedge; ignores parent MAIN expiry (mini vs quarterly)."""
        _ = parent_expiry
        cutoff = int(getattr(self, "hedge_monthly_rollover_after_calendar_day", 15) or 15)
        exp_wd = int(getattr(self, "hedge_monthly_expiry_weekday", 1) or 1) % 7
        if trade_date.day < cutoff:
            return ExpiryResolver.current_month_expiry(trade_date, weekday=exp_wd)
        return ExpiryResolver.next_month_expiry(trade_date, weekday=exp_wd)

    def calculate_hedge_strike(self, sold_strike, option_type):
        step = int(getattr(self, "option_chain_strike_step", 500) or 500)
        sold = int(sold_strike)
        opt = str(option_type or "").upper()
        if opt in ("CE", "CALL"):
            target = sold * 1.02
        elif opt in ("PE", "PUT"):
            target = sold * 0.98
        else:
            logger.warning(
                "LEAPS calculate_hedge_strike: unknown option_type=%s; defaulting +2%%",
                option_type,
            )
            target = sold * 1.02
        return int(round(target / step) * step)

    def _candle_close_ts_ist(self, candle: dict) -> pd.Timestamp:
        ts = pd.Timestamp(candle["timestamp"])
        if ts.tzinfo is None:
            ts = ts.tz_localize(IST)
        else:
            ts = ts.tz_convert(IST)
        bar_minutes = int(self.timeframe) if str(self.timeframe).isdigit() else 60
        return ts + pd.Timedelta(minutes=bar_minutes)

    def _find_strike_snapshot_params(self, candle, ctx, option_type):
        ts_ist = self._candle_close_ts_ist(candle)
        snapshot_date = ts_ist.strftime("%Y-%m-%d")
        snapshot_time = ts_ist.strftime("%H-%M")
        expiry_tag = str(getattr(self, "_snapshot_expiry_pref", "") or "")
        slot_key = "|".join(
            [
                str(getattr(ctx, "symbol", "") or ""),
                str(option_type or ""),
                expiry_tag,
                snapshot_date,
                snapshot_time,
            ]
        )
        if slot_key in self._leaps_snapshot_logged_slots:
            return {}
        self._leaps_snapshot_logged_slots.add(slot_key)
        target = "leaps_rsi"
        if expiry_tag == "QUARTERLY":
            target = "leaps_rsi_quarterly"
        return {
            "snapshot": True,
            "snapshot_date": snapshot_date,
            "snapshot_time": snapshot_time,
            "snapshot_target": target,
        }

    def _hedge_snapshot_params(
        self, candle: dict, ctx, option_type: str, hedge_expiry: date
    ) -> dict:
        ts_ist = self._candle_close_ts_ist(candle)
        snapshot_date = ts_ist.strftime("%Y-%m-%d")
        snapshot_time = ts_ist.strftime("%H-%M")
        slot_key = "|".join(
            [
                str(getattr(ctx, "symbol", "") or ""),
                str(option_type or ""),
                hedge_expiry.isoformat(),
                snapshot_date,
                snapshot_time,
            ]
        )
        if slot_key in self._leaps_hedge_snapshot_logged_slots:
            return {}
        self._leaps_hedge_snapshot_logged_slots.add(slot_key)
        return {
            "snapshot": True,
            "snapshot_date": snapshot_date,
            "snapshot_time": snapshot_time,
            "snapshot_target": "leaps_rsi_hedge",
        }

    def fetch_hedge_option_chain(
        self,
        candle: dict,
        ctx,
        hedge_expiry: date,
        option_type: str,
    ) -> Optional[Any]:
        extra_snapshot_params = self._hedge_snapshot_params(
            candle, ctx, option_type, hedge_expiry
        )
        params = {
            "exchange": ctx.exchange,
            "interval": self.timeframe,
            "expiry_code": hedge_expiry,
            "instrument": "OPTIDX",
            "expiry_flag": "MONTH",
            "strikes": 60,
            "expiry_match_same_month": True,
        }
        if extra_snapshot_params:
            params.update(extra_snapshot_params)

        saved_expiry = getattr(ctx, "selected_expiry", None)
        try:
            ctx.selected_expiry = hedge_expiry
            chain = ctx.option_chain_service.get_chain(
                api=self.api, ctx=ctx, params=params
            )
        finally:
            ctx.selected_expiry = saved_expiry

        if bool(params.get("snapshot", False)) and chain is not None:
            try:
                log_option_chain_snapshot(
                    chain,
                    ctx=ctx,
                    strategy_name=self.name,
                    api=self.api,
                    params=params,
                )
            except Exception as exc:
                logger.warning(
                    "log_option_chain_snapshot (hedge) raised: %s", exc, exc_info=True
                )
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
            px = self.get_option_price_at_candle(
                candle,
                ctx,
                hedge_strike,
                option_type,
                hedge_expiry,
            )
            if px is not None and px > 0:
                return px

        chain = self.fetch_hedge_option_chain(
            candle, ctx, hedge_expiry, option_type
        )
        if chain is None:
            logger.warning(
                "LEAPS hedge chain missing sym=%s expiry=%s strike=%s opt=%s",
                getattr(ctx, "symbol", "?"),
                hedge_expiry,
                hedge_strike,
                option_type,
            )
            return None

        row = self._strike_row_from_chain(chain, hedge_strike, option_type)
        px = self._execution_price_from_chain_row(row, option_type, "BUY")
        if px is not None and px > 0:
            return px
        logger.warning(
            "LEAPS hedge price missing sym=%s expiry=%s strike=%s opt=%s",
            getattr(ctx, "symbol", "?"),
            hedge_expiry,
            hedge_strike,
            option_type,
        )
        return None

    def _hourly_bar_open_key(self, candle: dict) -> str:
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

    def _entry_signal_guard_key(self, candle: dict, structure_id: str) -> str:
        return f"{structure_id}|{self._hourly_bar_open_key(candle)}"

    def _in_nse_hourly_close_eval_window(self, candle: dict, grace_minutes: int = 8) -> bool:
        return nse_60m_bar_close_eval_window(candle, grace_minutes=grace_minutes)

    def _resolve_main_expiry(
        self, candle: dict, ctx, expiry_pref: str
    ) -> Optional[date]:
        chain_exp = self._expiry_from_option_chain()
        if chain_exp is not None:
            return chain_exp
        trade_date = pd.to_datetime(candle["timestamp"]).date()
        try:
            resolved = ExpiryResolver.resolve(
                expiry_list=ctx.get_expiry_list() if ctx is not None else [],
                trade_date=trade_date,
                api=self.api,
                expiry_pref=str(expiry_pref or self.expiryType),
            )
        except (TypeError, ValueError):
            return None
        if resolved is None:
            return None
        if ExpiryResolver.is_calendar_expiry(resolved):
            return ExpiryResolver.as_calendar_date(resolved)
        return None

    def _build_entry_intents(
        self,
        candle: dict,
        ctx,
        option_type: str,
        *,
        structure_id: str,
        expiry_pref: str,
        leg_label: str,
    ) -> Optional[List[Any]]:
        signal_key = self._entry_signal_guard_key(candle, structure_id)
        if signal_key in self._entry_signaled_keys:
            return None

        # Exact structure_id OR same leg family (mini vs :QTR). Also blocks when
        # broker reconcile restored a short MAIN without structure_id after restart.
        has_open_main = getattr(ctx.position_store, "has_open_main_leg", None)
        if callable(has_open_main):
            blocked = has_open_main(
                self.name,
                underlying=str(candle.get("symbol") or ""),
                structure_id=structure_id,
            )
        else:
            blocked = ctx.position_store.has_open_structure(
                strategy=self.name, structure_id=structure_id, tag="MAIN"
            )
        if blocked:
            logger.info(
                "LEAPS %s entry skipped: open MAIN already present "
                "structure=%s sym=%s",
                leg_label,
                structure_id,
                candle.get("symbol"),
            )
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

        opt_u = option_type.upper()
        min_prem, max_prem = 200, 400

        self._snapshot_expiry_pref = str(expiry_pref or "")
        try:
            result = self.find_strike_in_premium_range(
                candle,
                ctx,
                option_type,
                min_prem=min_prem,
                max_prem=max_prem,
                expiry_pref=expiry_pref,
            )
        finally:
            self._snapshot_expiry_pref = None

        if result is None:
            logger.warning(
                "LEAPS %s entry skipped: no valid strike sym=%s opt=%s ts=%s "
                "expiry_pref=%s premium_band=%s-%s",
                leg_label,
                candle.get("symbol"),
                option_type,
                candle.get("timestamp"),
                expiry_pref,
                min_prem,
                max_prem,
            )
            return None

        strike, premium, row = result
        if not strike:
            return None

        expiry_for_symbol = self._resolve_main_expiry(candle, ctx, expiry_pref)
        if expiry_for_symbol is None:
            logger.warning(
                "LEAPS %s entry skipped: no expiry sym=%s ts=%s expiry_pref=%s",
                leg_label,
                candle.get("symbol"),
                candle.get("timestamp"),
                expiry_pref,
            )
            return None

        trading_symbol = ExpiryResolver.build_option_symbol(
            candle["symbol"],
            expiry_for_symbol,
            strike,
            option_type,
            include_year=True,
        )

        inst = ctx.instrument_store.intent_creation_details(
            trading_symbol,
            ctx.exchange,
            expiry_for_symbol,
            option_type,
            strike,
        )

        if inst is None:
            logger.warning(
                "LEAPS %s entry skipped: instrument not found sym=%s trading_symbol=%s "
                "expiry=%s strike=%s opt=%s",
                leg_label,
                candle.get("symbol"),
                trading_symbol,
                expiry_for_symbol,
                strike,
                option_type,
            )
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
            parent_sell_intent=sell_intent,
            candle=candle,
            ctx=ctx,
        )

        self._entry_signaled_keys.add(signal_key)
        logger.info(
            "LEAPS %s entry intents structure=%s main=%s expiry=%s strike=%s",
            leg_label,
            structure_id,
            trading_symbol,
            expiry_for_symbol,
            strike,
        )
        return [hedge_intent, sell_intent] if hedge_intent else [sell_intent]

    def should_evaluate(self, candle):
        if not self._in_nse_hourly_close_eval_window(candle):
            return False
        rsi = candle.get("rsi")
        prev = candle.get("prev_rsi")
        if pd.isna(rsi) or pd.isna(prev):
            return False
        cross_lt_32 = prev >= 32 and rsi < 32
        cross_gt_52 = prev <= 52 and rsi > 52
        if not cross_lt_32 and not cross_gt_52:
            return False
        eval_key = self._hourly_bar_open_key(candle)
        if eval_key in self._evaluated_signal_keys:
            return False
        self._evaluated_signal_keys.add(eval_key)
        return True

    def eval_signal_log_message(self, candle) -> Optional[str]:
        rsi = candle.get("rsi")
        prev = candle.get("prev_rsi")
        if pd.isna(rsi) or pd.isna(prev):
            return None
        return (
            "Signal condition met"
            f" rsi={rsi} prev_rsi={prev}"
            f" timeframe={getattr(self, 'timeframe', '')}"
        )

    def on_candle(self, candle, ctx):
        rsi = candle["rsi"]
        if rsi < 32:
            option_type = "CALL"
            regime = "RSI_LT_32"
        elif rsi > 52:
            option_type = "PUT"
            regime = "RSI_GT_52"
        else:
            return None

        if not self.mini_leaps_enabled and not self.quarterly_leaps_enabled:
            logger.warning("LEAPS entry skipped: both mini_leaps and quarterly_leaps disabled")
            return None

        base_structure_id = self.build_structure_id(candle, regime)
        all_intents: List[Any] = []

        for flag_attr, expiry_pref, suffix in LEG_SPECS:
            if not getattr(self, flag_attr, False):
                continue
            structure_id = f"{base_structure_id}{suffix}"
            leg_label = "quarterly" if suffix else "mini"
            legs = self._build_entry_intents(
                candle,
                ctx,
                option_type,
                structure_id=structure_id,
                expiry_pref=expiry_pref,
                leg_label=leg_label,
            )
            if legs:
                all_intents.extend(legs)

        return all_intents or None

    def should_exit(self, position, candle, ctx=None):
        if position.tag != "MAIN":
            return False
        rsi = candle.get("rsi")
        if pd.isna(rsi):
            return False
        if position.instrument.option_type in ("CE", "CALL") and rsi > 52:
            return True
        if position.instrument.option_type in ("PE", "PUT") and rsi < 32:
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
        qty_lots = self._order_qty_in_lots(
            position.instrument, abs(int(position.net_qty or 0))
        )
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

        return intents
