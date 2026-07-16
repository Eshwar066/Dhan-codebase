"""
NIFTY SMA(9) weekly option selling on 2h bars.

- Close crosses above SMA9 → SELL PUT (OTM, premium 80–100) + weekly hedge
- Close crosses below SMA9 → SELL CALL (OTM, premium 80–100) + weekly hedge
- If current weekly has no OTM strike in 80–100, use next weekly expiry
- Hedge 500 points OTM from MAIN on the same weekly expiry
  (CALL short K → long K+500; PUT short K → long K−500)
- Roll hedge 1 trading day before weekly expiry
- No new entries on NSE holidays / configured event dates / weekly expiry day
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any, List, Optional, Set

import pandas as pd

from run.config import RUN_MODE, RunMode
from core.strategies.base import BaseStrategy
from core.strategies.IndiaMktMixins import IST, IndiaMktMixins
from core.strategies.indicator_helpers import (
    add_sma,
    default_persisted_keys_for_sma,
)
from core.utils.expiry_resolver import ExpiryResolver
from core.utils.indicator_history import nse_120m_bar_close_eval_window
from core.utils.option_chain_snapshot_log import log_option_chain_snapshot
from core.utils.session.session_manager import SessionManager

logger = logging.getLogger(__name__)


class NiftySMA9Weekly(IndiaMktMixins, BaseStrategy):
    """SMA9 NIFTY weekly option sell with weekly hedge protection."""

    name = "NiftySMA9Weekly"
    underlying_symbols = ["NIFTY"]
    timeframe = "120"
    required_context = ["option_chain"]
    api = "DHAN"
    expiryType = "WEEKLY"
    dhan_expiry_flag = "WEEK"
    weekly_expiry_weekday = 1  # Nifty weekly = Tuesday
    option_chain_strike_step = 50
    otm_strike_step = 50
    otm_strike_count = 8
    option_chain_ideal_premium = 90
    # Dhan option OHLC APIs have no 120m; price exits/hedges on 60m bars.
    option_chain_interval = "60"
    sma_period = 9
    premium_min = 80
    premium_max = 100
    hedge_distance_points = 500  # fixed OTM gap from MAIN strike
    hedge_rollover_days_before_expiry = 1
    hedge_prefer_monthly = False  # weekly hedge series

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._snapshot_logged_slots: set[str] = set()
        self._hedge_snapshot_logged_slots: set[str] = set()
        self._entry_signaled_keys: set[str] = set()
        self._evaluated_signal_keys: set[str] = set()
        self._event_no_trade_dates: Set[date] = set()
        self._snapshot_expiry_pref: Optional[str] = None
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
            logger.warning("NiftySMA9Weekly: could not read strategy.yaml: %s", exc)
            return

        params = raw.get("params") or {}
        if "sma_period" in params:
            self.sma_period = int(params["sma_period"])
        if "premium_min" in params:
            self.premium_min = float(params["premium_min"])
        if "premium_max" in params:
            self.premium_max = float(params["premium_max"])
        if "hedge_distance_points" in params:
            self.hedge_distance_points = int(params["hedge_distance_points"])
        elif "hedge_distance_pct" in params:
            # Legacy yaml key ignored; fixed-point hedge is required.
            logger.info(
                "NiftySMA9Weekly: hedge_distance_pct is deprecated; "
                "use hedge_distance_points (default %s)",
                getattr(self, "hedge_distance_points", 500),
            )
        if "weekly_expiry_weekday" in params:
            self.weekly_expiry_weekday = int(params["weekly_expiry_weekday"]) % 7
        if "hedge_rollover_days_before_expiry" in params:
            self.hedge_rollover_days_before_expiry = int(
                params["hedge_rollover_days_before_expiry"]
            )

        events = raw.get("event_no_trade_dates") or []
        parsed: Set[date] = set()
        for item in events:
            try:
                parsed.add(pd.Timestamp(item).date())
            except Exception:
                logger.warning("NiftySMA9Weekly: bad event_no_trade date=%s", item)
        self._event_no_trade_dates = parsed

    def get_warmup_period(self):
        return max(30, int(self.sma_period) * 3)

    def prepare_indicators(self, df):
        period = int(getattr(self, "sma_period", 9) or 9)
        col = f"sma{period}"
        prev_col = f"prev_sma{period}"
        df = add_sma(df, period=period, column=col)
        if col in df.columns:
            df[prev_col] = df[col].shift(1)
        if "close" in df.columns:
            df["prev_close"] = df["close"].shift(1)
        return df

    def persisted_indicator_keys(self):
        period = int(getattr(self, "sma_period", 9) or 9)
        return default_persisted_keys_for_sma(period, column=f"sma{period}") + [
            f"prev_sma{period}",
            "prev_close",
        ]

    def shared_indicator_signature(self) -> str:
        return f"sma9_weekly_{int(getattr(self, 'sma_period', 9) or 9)}"

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
            target = sold + gap  # e.g. short 24500 CE → long 25000 CE
        elif opt in ("PE", "PUT"):
            target = sold - gap  # e.g. short 24000 PE → long 23500 PE
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
                "snapshot_target": "nifty_sma9_weekly_hedge",
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
        bar_minutes = int(self.timeframe) if str(self.timeframe).isdigit() else 120
        return ts + pd.Timedelta(minutes=bar_minutes)

    def _bar_open_key(self, candle: dict) -> str:
        bucket = candle.get("bucket_ts")
        if bucket is not None:
            try:
                ts = pd.to_datetime(int(float(bucket)), unit="s", utc=True).tz_convert(
                    IST
                )
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

    def _in_2h_close_eval_window(self, candle: dict, grace_minutes: int = 10) -> bool:
        return nse_120m_bar_close_eval_window(
            candle,
            grace_minutes=grace_minutes,
        )

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
        target = "nifty_sma9_weekly"
        if expiry_tag == "NEXT_WEEKLY":
            target = "nifty_sma9_weekly_next"
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
        """Require OTM strike with premium strictly inside ``min_prem``–``max_prem``."""
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
        max_prem = float(getattr(self, "premium_max", 100) or 100)
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
            accepted = self._accept_otm_premium_strike(
                candidate, option_type, spot, min_prem, max_prem
            )
            if accepted is not None:
                result = accepted
                expiry_pref = pref
                if pref == "NEXT_WEEKLY":
                    logger.info(
                        "NiftySMA9Weekly: no OTM prem=%s-%s on current weekly; "
                        "using next weekly opt=%s ts=%s",
                        min_prem,
                        max_prem,
                        option_type,
                        candle.get("timestamp"),
                    )
                break
            logger.info(
                "NiftySMA9Weekly: no OTM strike in prem=%s-%s expiry_pref=%s opt=%s",
                min_prem,
                max_prem,
                pref,
                option_type,
            )

        if result is None:
            logger.warning(
                "NiftySMA9Weekly entry skipped: no OTM strike opt=%s prem=%s-%s "
                "on WEEKLY or NEXT_WEEKLY ts=%s",
                option_type,
                min_prem,
                max_prem,
                candle.get("timestamp"),
            )
            return None

        strike, premium, row = result

        expiry_for_symbol = self._resolve_main_expiry(candle, ctx, expiry_pref)
        if expiry_for_symbol is None:
            logger.warning(
                "NiftySMA9Weekly entry skipped: no weekly expiry pref=%s",
                expiry_pref,
            )
            return None

        # Do not open a new weekly on expiry day (handled earlier) or past expiry.
        if self._trade_date(candle) >= expiry_for_symbol:
            logger.info(
                "NiftySMA9Weekly entry skipped: trade_date>=expiry %s",
                expiry_for_symbol,
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
                "NiftySMA9Weekly entry skipped: instrument missing %s",
                trading_symbol,
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
            "NiftySMA9Weekly entry structure=%s main=%s premium=%s expiry=%s "
            "expiry_pref=%s hedge=%s",
            structure_id,
            trading_symbol,
            premium,
            expiry_for_symbol,
            expiry_pref,
            getattr(getattr(hedge_intent, "instrument", None), "trading_symbol", None),
        )
        return [hedge_intent, sell_intent] if hedge_intent else [sell_intent]

    def should_evaluate(self, candle):
        # Live: only eval shortly after 2h bar close. Backtest: every closed bar.
        if RUN_MODE != RunMode.BACKTEST and not self._in_2h_close_eval_window(candle):
            return False

        trade_date = self._trade_date(candle)
        if self._is_event_no_trade_day(trade_date):
            return False
        if self._is_weekly_expiry_day(trade_date):
            return False

        period = int(getattr(self, "sma_period", 9) or 9)
        sma_key = f"sma{period}"
        prev_sma_key = f"prev_sma{period}"
        close = candle.get("close")
        prev_close = candle.get("prev_close")
        sma = candle.get(sma_key)
        prev_sma = candle.get(prev_sma_key)
        if any(pd.isna(x) for x in (close, prev_close, sma, prev_sma)):
            return False

        cross_up = prev_close <= prev_sma and close > sma
        cross_down = prev_close >= prev_sma and close < sma
        if not cross_up and not cross_down:
            return False

        eval_key = self._bar_open_key(candle)
        if eval_key in self._evaluated_signal_keys:
            return False
        self._evaluated_signal_keys.add(eval_key)
        return True

    def eval_signal_log_message(self, candle) -> Optional[str]:
        period = int(getattr(self, "sma_period", 9) or 9)
        sma_key = f"sma{period}"
        prev_sma_key = f"prev_sma{period}"
        return (
            "SMA9 cross"
            f" close={candle.get('close')} {sma_key}={candle.get(sma_key)}"
            f" prev_close={candle.get('prev_close')} {prev_sma_key}={candle.get(prev_sma_key)}"
            f" timeframe={getattr(self, 'timeframe', '')}"
        )

    def on_candle(self, candle, ctx):
        trade_date = self._trade_date(candle)
        if self._is_event_no_trade_day(trade_date) or self._is_weekly_expiry_day(
            trade_date
        ):
            return None

        period = int(getattr(self, "sma_period", 9) or 9)
        sma_key = f"sma{period}"
        prev_sma_key = f"prev_sma{period}"
        close = candle.get("close")
        prev_close = candle.get("prev_close")
        sma = candle.get(sma_key)
        prev_sma = candle.get(prev_sma_key)
        if any(pd.isna(x) for x in (close, prev_close, sma, prev_sma)):
            return None

        if prev_close <= prev_sma and close > sma:
            option_type = "PUT"
            regime = "SMA_CROSS_UP"
        elif prev_close >= prev_sma and close < sma:
            option_type = "CALL"
            regime = "SMA_CROSS_DOWN"
        else:
            return None

        structure_id = self.build_structure_id(candle, regime)
        return self._build_entry_intents(
            candle, ctx, option_type, structure_id=structure_id
        )

    # ---------- Exit ----------

    def should_exit(self, position, candle, ctx=None):
        if position.tag != "MAIN":
            return False
        period = int(getattr(self, "sma_period", 9) or 9)
        sma_key = f"sma{period}"
        close = candle.get("close")
        sma = candle.get(sma_key)
        if pd.isna(close) or pd.isna(sma):
            return False
        opt = str(getattr(position.instrument, "option_type", "") or "").upper()
        # Opposite side of entry regime: short PUT exits on bearish break; short CALL on bullish.
        if opt in ("PE", "PUT") and close < sma:
            return True
        if opt in ("CE", "CALL") and close > sma:
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

    # ---------- Weekly hedge rollover (1 day before expiry) ----------

    def is_rollover_window(self, ts):
        current = pd.to_datetime(ts).date()
        # Broad window: allow checking any weekday near weekly expiry.
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

            # Force next weekly expiry for the replacement hedge.
            wd = int(getattr(self, "weekly_expiry_weekday", 1) or 1) % 7
            next_exp = ExpiryResolver.next_weekly_expiry(ts.date(), weekday=wd)
            self._force_hedge_expiry = next_exp
            try:
                hedge_exit = self.create_hedge_exit_intent(parent, candle, ctx)
                if hedge_exit:
                    intents.append(hedge_exit)
                new_hedge = self.create_hedge_intent(parent, candle, ctx)
                if new_hedge:
                    intents.append(new_hedge)
            finally:
                self._force_hedge_expiry = None

            self.rolled_hedges.add(roll_key)
            logger.info(
                "NiftySMA9Weekly hedge rollover structure=%s next_expiry=%s",
                hedge.structure_id,
                next_exp,
            )

        return intents
