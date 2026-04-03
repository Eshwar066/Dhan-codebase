"""
India market mixins: shared logic for India options/LEAPS strategies.

Use in any strategy that needs:
- Option chain fetch, strike selection, option pricing
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
from typing import Any, List, Optional, Tuple

# India Standard Time (UTC+5:30) for strategy time-of-day filters.
IST = timezone(timedelta(hours=5, minutes=30))

from run.config import RUN_MODE, RunMode
from core.utils.expiry_resolver import ExpiryResolver
from core.models.order_intent import OrderIntent
from core.strategies.deltaMktMixins import (
    _delta_source_from_ctx,
    delta_option_trading_symbol,
    ltp_from_strike_row_live,
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
        return OrderIntent(
            intent_id=uuid.uuid4().hex,
            instrument=inst,
            side=side,
            qty=int(inst.lot_size),
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

        if not chain or "chain" not in chain:
            return None

        df = chain["chain"]

        if option_type.upper() in ("PUT", "PE"):
            cols = ["PE LTP", "PUT LTP"]
        else:
            cols = ["CE LTP", "CALL LTP"]

        for col in cols:
            if col in df.columns:
                return float(df[col].iloc[0])

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
        self, candle, ctx, option_type, min_prem=200, max_prem=400
    ):
        otm_strikes = self.fetch_option_chain(candle, ctx, option_type)

        candle_time = candle["timestamp"].replace(tzinfo=None)

        params = {
            "exchange": ctx.exchange,
            "interval": self.timeframe,
            "expiry_code": ctx.selected_expiry,
            "strike": otm_strikes,
            "option_type": option_type,
            "instrument": "OPTIDX",
            "exchangeSegment": "NSE_FNO",
            "expiry_flag": "MONTH",
            "securityId": "13",
        }

        chain = ctx.option_chain_service.get_chain(api=self.api, ctx=ctx, params=params)
        if not chain:
            print(">>no option chain data", ctx, params)
            return None

        if RUN_MODE == RunMode.LIVE or RUN_MODE == RunMode.PAPER:
            if chain is None or len(chain) == 0:
                return None

            row = chain[chain["datetime"] == candle_time]
            if row.empty:
                return None

            premium = float(row.iloc[0]["close"])
            selected_strike = row.iloc[0]["strike"]
        else:
            chain = chain["chain"]
            if chain is None or len(chain) == 0:
                return None

            option_type_upper = option_type.upper()
            premium_col = None
            for col in chain.columns:
                if option_type_upper in col.upper() and "LTP" in col.upper():
                    premium_col = col
                    break

            if premium_col is None:
                return None

            row = chain[chain[premium_col].between(min_prem, max_prem)]
            if row.empty:
                return None

            selected_strike = row.iloc[0]["Strike Price"]
            premium = float(row.iloc[0][premium_col])

        if min_prem <= premium <= max_prem:
            return selected_strike, premium, row

        return None

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
            option_type_label = "PUT" if option_type == "PE" else "CALL"
            ltp_value = strike_row.get(f"{option_type_label} LTP", 0)
            ltp = (
                float(ltp_value.iloc[0])
                if isinstance(ltp_value, pd.Series)
                else float(ltp_value)
            )

        assert inst.trading_symbol
        assert inst.custom_symbol

        return OrderIntent(
            intent_id=uuid.uuid4().hex,
            instrument=inst,
            side=side,
            qty=int(inst.lot_size),
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
            qty=int(inst.lot_size),
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
