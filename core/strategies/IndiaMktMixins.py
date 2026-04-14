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
import pandas as pd
from datetime import date, timedelta, datetime, timezone
from typing import Any, List, Optional, Tuple, Union

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
        lot = int(getattr(inst, "lot_size", 0) or 0)
        lots = int(getattr(self, "order_qty_lots", ORDER_QTY_LOTS) or 1)
        return max(1, lot * max(1, lots))

    def _normalize_order_qty(self, inst, qty) -> int:
        if qty is None:
            return self._entry_order_qty(inst)
        try:
            q = int(qty)
        except (TypeError, ValueError):
            return self._entry_order_qty(inst)
        return q if q > 0 else self._entry_order_qty(inst)

    # ==================================================
    # DHAN EXPIRED OPTION CSV (BACKTEST) — same layout as dhan expired option chain download scripts
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
                exp_code = self._delta_expiry_ddmmyy(expiry)
                sym = delta_option_trading_symbol(
                    None,
                    float(strike) if strike is not None else 0.0,
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

        params = {
            "exchange": ctx.exchange,
            "interval": self.timeframe,
            "expiry_code": expiry,
            "strike": [str(int(float(strike)))],
            "option_type": option_type,
            "instrument": "OPTIDX",
            "exchangeSegment": "NSE_FNO",
            "expiry_flag": "MONTH",
            "securityId": "13",
        }

        chain = ctx.option_chain_service.get_chain(api=self.api, ctx=ctx, params=params)

        df: Optional[pd.DataFrame] = None
        if chain is None:
            return None
        if isinstance(chain, dict):
            df = chain.get("chain")
        elif isinstance(chain, pd.DataFrame):
            df = chain
        else:
            return None
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return None

        # DHAN rolling option bars: multiple timestamps — keep the current candle row only.
        if "datetime" in df.columns and len(df) > 0:
            candle_time = candle["timestamp"].replace(tzinfo=None)
            ts = pd.to_datetime(df["datetime"])
            wall = ts.dt.strftime("%Y-%m-%d %H:%M")
            wall_c = pd.Timestamp(candle_time).strftime("%Y-%m-%d %H:%M")
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
        for col in chain.columns:
            if option_type_upper in col.upper() and "LTP" in col.upper():
                return col
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

    def fetch_option_chain(self, candle, ctx, option_type):
        ocs = ctx.option_chain_service

        if self.api == "NSE":
            ctx.expiry_list = ocs.get_expiries(
                api=self.api, ctx=ctx, instrument="FUTIDX"
            )

        expiry_code = ExpiryResolver.resolve(
            expiry_list=ctx.get_expiry_list(),
            trade_date=ctx.timestamp,
            api=self.api,
            expiry_pref=self.expiryType,
        )
        spot = candle["close"]
        step = 500
        otm_strikes = ExpiryResolver.get_otm_strikes(
            self, spot=spot, option_type=option_type, step=step, count=4
        )
        ctx.selected_expiry = expiry_code
        ctx.otm_strikes = otm_strikes

        return otm_strikes

    def find_strike_in_premium_range(
        self,
        candle,
        ctx,
        option_type,
        min_prem=200,
        max_prem=400,
        delta_min=None,
        delta_max=None,
    ):
        otm_strikes = self.fetch_option_chain(candle, ctx, option_type)

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

        candle_time = candle["timestamp"].replace(tzinfo=None)

        # When delta bounds are set and the chain has a delta column, strike selection uses
        # |delta| only — no min_prem/max_prem filtering or final premium check.

        strike_param = otm_strikes
        if strike_param and isinstance(strike_param[0], (int, float)):
            strike_param = [str(int(s)) for s in otm_strikes]

        params = {
            "exchange": ctx.exchange,
            "interval": self.timeframe,
            "expiry_code": ctx.selected_expiry,
            "strike": strike_param,
            "option_type": option_type,
            "instrument": "OPTIDX",
            "exchangeSegment": "NSE_FNO",
            "expiry_flag": "MONTH",
            "securityId": "13",
        }

        chain = ctx.option_chain_service.get_chain(api=self.api, ctx=ctx, params=params)
       
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

        skip_premium_check = False

        if RUN_MODE == RunMode.LIVE or RUN_MODE == RunMode.PAPER:
            if not isinstance(chain, pd.DataFrame) or chain.empty:
                return None

            dcol_live = (
                self._option_chain_delta_column(chain, option_type)
                if use_delta and isinstance(chain, pd.DataFrame)
                else None
            )
            delta_in_chain_live = (
                dcol_live is not None and dcol_live in chain.columns
            )

            row = chain[chain["datetime"] == candle_time]
            if row.empty:
                return None

            if use_delta and delta_in_chain_live and dcol_live in row.columns:
                mask = row.apply(
                    lambda r: self._abs_delta_in_band(r, dcol_live, d_min, d_max),
                    axis=1,
                )
                filt = row[mask]
                if filt.empty:
                    return None
                row = filt
                skip_premium_check = True

            premium = float(row.iloc[0]["close"])
            selected_strike = row.iloc[0]["strike"]
        else:
            # NSE backtest often returns {"chain": df}; DHAN / Tradehull may return a bare DataFrame.
            if isinstance(chain, dict):
                chain = chain.get("chain")
            if chain is None:
                return None
            if isinstance(chain, pd.DataFrame):
                if chain.empty:
                    return None
            else:
                return None

            # Rolling option history (e.g. DHAN): multiple bars — keep the current candle row only.
            if "datetime" in chain.columns and len(chain) > 0:
                ts = pd.to_datetime(chain["datetime"])
                wall = ts.dt.strftime("%Y-%m-%d %H:%M")
                wall_c = pd.Timestamp(candle_time).strftime("%Y-%m-%d %H:%M")
                filt = chain[wall == wall_c]
                if not filt.empty:
                    chain = filt
                elif len(chain) > 1:
                    return None

            option_type_upper = option_type.upper()
            premium_col = self._option_chain_premium_column(chain, option_type_upper)

            if premium_col is None:
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
            ltp = ltp_from_strike_row_live(strike_row)
        else:
            ltp = self._ltp_from_strike_row_backtest(strike_row, option_type)

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
    def resolve_hedge_expiry(self, trade_date):
        return (
            ExpiryResolver.current_month_expiry(trade_date)
            if trade_date.day < 15
            else ExpiryResolver.next_month_expiry(trade_date)
        )

    def calculate_hedge_strike(self, sold_strike, option_type):
        if option_type == "CALL":
            return int(round((sold_strike * 1.02) / 500) * 500)
        return int(round((sold_strike * 0.98) / 500) * 500)

    def create_hedge_intent(self, parent_sell_intent, candle, ctx):
        trade_date = pd.to_datetime(candle["timestamp"]).date()
        hedge_expiry = self.resolve_hedge_expiry(trade_date)

        hedge_strike = self.calculate_hedge_strike(
            parent_sell_intent.instrument.strike,
            parent_sell_intent.instrument.option_type,
        )

        hedge_symbol = ExpiryResolver.build_option_symbol(
            self,
            candle["symbol"],
            hedge_expiry,
            hedge_strike,
            parent_sell_intent.instrument.option_type,
        )

        inst = ctx.instrument_store.intent_creation_details(
            hedge_symbol,
            ctx.exchange,
            hedge_expiry,
            parent_sell_intent.instrument.option_type,
            hedge_strike,
        )
        if inst is None:
            return None

        hedge_price = (
            self.get_option_price_at_candle(
                candle,
                ctx,
                hedge_strike,
                parent_sell_intent.instrument.option_type,
                hedge_expiry,
            )
            if RUN_MODE == RunMode.BACKTEST
            else 0
        )

        return self.create_order_intent(
            inst=inst,
            side="BUY",
            qty=1,
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
            print(
                f"⚠️ No exit price for hedge {hedge.instrument.symbol} at {candle['timestamp']}"
            )
            return None

        return self.create_order_intent(
            inst=hedge.instrument,
            side="BUY" if hedge.net_qty < 0 else "SELL",
            qty=abs(hedge.net_qty),
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

        target = date(current.year, current.month, 18)
        if target.weekday() == 5:
            target -= timedelta(days=1)
        elif target.weekday() == 6:
            target -= timedelta(days=2)

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
