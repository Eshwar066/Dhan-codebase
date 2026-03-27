"""
Magical Lines: time-anchored option selling strategy for Dhan (NSE index options).

Runs at 3:20 PM. Direction from intraday candle (9:15–15:20): green → short PE, red → short CE.
Magical line: MLG = spot * 0.9975 (green), MLR = spot * 1.0025 (red).
Main leg: strike in multiples of 100, premium in 180–320 range.
Hedge: within 500 points of main leg, net credit 90–120.
Expiry: monthly; after 13th of month new trades use next month. Rollover one week before expiry (Wednesday).
Reversal: if at 3:20 price crosses and closes opposite to magical line → exit and short in reverse direction.
Optional: second/third level when market moves 2% from first magical line (max positions capped).
"""

import pandas as pd
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from run.config import RUN_MODE, RunMode
from core.strategies.base import BaseStrategy
from core.strategies.IndiaMktMixins import IndiaMktMixins
from core.utils.expiry_resolver import ExpiryResolver


VALID_TIME_1520 = {"15:20"}

# Premium and hedge constraints (with buffer per spec)
TARGET_PREMIUM_MIN = 200
TARGET_PREMIUM_MAX = 400
STRIKE_STEP = 100
HEDGE_MAX_POINTS = 500
NET_CREDIT_MIN = 90
NET_CREDIT_MAX = 120
MAGICAL_LINE_PCT = 0.0025  # 0.25%
MAX_MAGICAL_LEVELS = 3
MOVE_PCT_FOR_NEXT_LEVEL = 0.02  # 2%


class MagicalLines(IndiaMktMixins, BaseStrategy):
    """
    Magical Lines: 3:20 PM option selling with magical line, premium target, and hedged leg.
    Dhan broker, NSE index options (e.g. NIFTY).
    """

    name = "MagicalLines"
    timeframe = "60"
    required_context = ["option_chain"]
    api = "NSE"
    expiryType = "MONTHLY"
    valid_times = VALID_TIME_1520

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._day_open: Dict[str, float] = {}
        self._magical_levels: Dict[str, List[Dict]] = {}  # symbol -> [{level, ml, direction, ...}]

    def get_warmup_period(self):
        return 0

    # ==================================================
    # EXPIRY: after 13th → next month; else current month
    # ==================================================
    def get_expiry_for_magical(self, ctx) -> Optional[Any]:
        trade_date = pd.to_datetime(ctx.timestamp).date()
        if trade_date.day > 13:
            return ExpiryResolver.next_month_expiry(trade_date)
        return ExpiryResolver.current_month_expiry(trade_date)

    def fetch_option_chain(self, candle, ctx, option_type):
        ocs = ctx.option_chain_service
        if self.api == "NSE":
            ctx.expiry_list = ocs.get_expiries(api=self.api, ctx=ctx, instrument="FUTIDX")

        expiry_date = self.get_expiry_for_magical(ctx)
        if expiry_date is None or not ctx.expiry_list:
            return None

        expiry_dates = [pd.to_datetime(e).date() for e in ctx.expiry_list]
        matches = [e for e in expiry_dates if e == expiry_date]
        if not matches:
            matches = sorted(expiry_dates)
            for e in matches:
                if e >= expiry_date:
                    expiry_date = e
                    break
            else:
                expiry_date = matches[-1] if matches else expiry_date

        idx = next((i for i, e in enumerate(expiry_dates) if pd.to_datetime(e).date() == expiry_date), 0)
        ctx.selected_expiry = ctx.expiry_list[idx] if idx < len(ctx.expiry_list) else ctx.expiry_list[0]

        spot = float(candle["close"])
        step = STRIKE_STEP
        atm = round(spot / step) * step
        if option_type.upper() in ("PUT", "PE"):
            strikes = [atm + (i * step) for i in range(-15, 16)]
        else:
            strikes = [atm + (i * step) for i in range(-15, 16)]
        ctx.otm_strikes = [int(s) for s in strikes]
        return ctx.otm_strikes

    # ==================================================
    # DIRECTION: green day (close > open) → short PE; red → short CE
    # ==================================================
    def _update_day_open(self, symbol: str, candle: dict):
        ts = pd.to_datetime(candle["timestamp"])
        key = f"{symbol}_{ts.date()}"
        if key not in self._day_open:
            self._day_open[key] = float(candle.get("open", candle.get("close", 0)))
        return self._day_open[key]

    def _direction_at_1520(self, candle, ctx) -> Optional[str]:
        symbol = candle["symbol"]
        day_open = self._update_day_open(symbol, candle)
        close = float(candle["close"])
        if close > day_open:
            return "SHORT_PE"
        return "SHORT_CE"

    # ==================================================
    # MAGICAL LINE
    # ==================================================
    def _magical_line(self, spot: float, direction: str) -> float:
        if direction == "SHORT_PE":
            return spot * (1 - MAGICAL_LINE_PCT)
        return spot * (1 + MAGICAL_LINE_PCT)

    # ==================================================
    # STRIKE SELECTION: multiples of 100, premium 180–320
    # ==================================================
    def find_strike_magical(
        self, candle, ctx, option_type: str
    ) -> Optional[Tuple[Any, float, Any]]:
        result = self.find_strike_in_premium_range(
            candle, ctx, option_type,
            min_prem=TARGET_PREMIUM_MIN,
            max_prem=TARGET_PREMIUM_MAX,
        )
        if result is None:
            return None
        strike, premium, row = result
        strike = int(float(strike))
        if strike % STRIKE_STEP != 0:
            return None
        return strike, premium, row

    # ==================================================
    # HEDGE: within 500 points, net credit 90–120
    # ==================================================
    def find_hedge_magical(
        self, candle, ctx, main_strike: int, main_premium: float, option_type: str
    ) -> Optional[Tuple[Any, float]]:
        ocs = ctx.option_chain_service
        chain = ocs.get_chain(
            api=self.api,
            ctx=ctx,
            params={
                "exchange": ctx.exchange,
                "interval": self.timeframe,
                "expiry_code": ctx.selected_expiry,
                "strike": [
                    main_strike + (i * STRIKE_STEP)
                    for i in range(-HEDGE_MAX_POINTS // STRIKE_STEP, HEDGE_MAX_POINTS // STRIKE_STEP + 1)
                ],
                "option_type": option_type,
                "instrument": "OPTIDX",
                "exchangeSegment": "NSE_FNO",
                "expiry_flag": "MONTH",
                "securityId": "13",
            },
        )
        if not chain or "chain" not in chain:
            return None
        df = chain["chain"]
        opt_upper = option_type.upper()
        prem_col = None
        for c in df.columns:
            if opt_upper in c.upper() and "LTP" in c.upper():
                prem_col = c
                break
        if prem_col is None:
            return None
        strike_col = "Strike Price" if "Strike Price" in df.columns else df.columns[0]
        for _, r in df.iterrows():
            try:
                hedge_strike = int(float(r[strike_col]))
            except (TypeError, ValueError, KeyError):
                continue
            if abs(hedge_strike - main_strike) > HEDGE_MAX_POINTS:
                continue
            hedge_prem = float(r.get(prem_col, 0) or 0)
            net = main_premium - hedge_prem
            if NET_CREDIT_MIN <= net <= NET_CREDIT_MAX:
                return hedge_strike, hedge_prem
        return None

    # ==================================================
    # SHOULD EVALUATE: only at 15:20
    # ==================================================
    def should_evaluate(self, candle):
        ts = pd.to_datetime(candle["timestamp"])
        return self._is_valid_time(ts, VALID_TIME_1520)

    # ==================================================
    # ENTRY
    # ==================================================
    def on_candle(self, candle, ctx):
        if not self.should_evaluate(candle):
            return None

        symbol = candle["symbol"]
        direction = self._direction_at_1520(candle, ctx)
        spot = float(candle["close"])
        ml = self._magical_line(spot, direction)

        option_type = "PE" if direction == "SHORT_PE" else "CE"
        structure_id = f"{self.name}:{symbol}:ML1"

        if ctx.position_store.has_open_structure(
            strategy=self.name, structure_id=structure_id, tag="MAIN"
        ):
            return None

        result = self.find_strike_magical(candle, ctx, option_type)
        if result is None:
            return None
        strike, premium, row = result

        expiry = ctx.selected_expiry
        trading_symbol = ExpiryResolver.build_option_symbol(
            self, candle["symbol"], expiry, strike, option_type
        )
        inst = ctx.instrument_store.intent_creation_details(
            trading_symbol, ctx.exchange, expiry, option_type, strike
        )
        if inst is None:
            return None

        sell_intent = self.map_instrument_to_intent(
            inst=inst,
            strike_row=row,
            strategy=self.name,
            side="SELL",
            structure_id=structure_id,
            candle_ts=candle["timestamp"],
            tag="MAIN",
            symbol=symbol,
            action="ENTRY",
        )

        hedge = self.find_hedge_magical(candle, ctx, strike, premium, option_type)
        if hedge is None:
            return [sell_intent]
        hedge_strike, hedge_prem = hedge
        hedge_expiry = self.get_expiry_for_magical(ctx)
        hedge_symbol = ExpiryResolver.build_option_symbol(
            self, candle["symbol"], hedge_expiry, hedge_strike, option_type
        )
        hedge_inst = ctx.instrument_store.intent_creation_details(
            hedge_symbol, ctx.exchange, hedge_expiry, option_type, hedge_strike
        )
        if hedge_inst is None:
            return [sell_intent]
        hedge_intent = self.create_order_intent(
            inst=hedge_inst,
            side="BUY",
            qty=1,
            price=hedge_prem,
            order_type="LIMIT",
            strategy=self.name,
            candle_ts=candle["timestamp"],
            structure_id=structure_id,
            tag="HEDGE",
            parent_intent_id=sell_intent.intent_id,
            symbol=symbol,
            action="ENTRY",
        )
        return [sell_intent, hedge_intent]

    # ==================================================
    # EXIT: reversal when close opposite to magical line at 3:20
    # ==================================================
    def should_exit(self, position, candle, ctx=None):
        if position.tag != "MAIN":
            return False
        if not self.should_evaluate(candle):
            return False
        symbol = candle["symbol"]
        close = float(candle["close"])
        direction = self._direction_at_1520(candle, ctx)
        ml = self._magical_line(close, direction)
        is_pe = position.instrument.option_type in ("PE", "PUT")
        if is_pe and close < ml:
            return True
        if not is_pe and close > ml:
            return True
        return False

    def on_position_exit(self, position, candle, ctx):
        intents = []
        price = (
            self.get_option_price_at_candle(
                candle, ctx,
                position.instrument.strike,
                position.instrument.option_type,
                position.instrument.expiry,
            )
            if RUN_MODE == RunMode.BACKTEST
            else None
        )
        intents.append(
            self.create_order_intent(
                inst=position.instrument,
                side="BUY" if position.net_qty < 0 else "SELL",
                qty=abs(position.net_qty),
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

    # ==================================================
    # ROLLOVER: one week before expiry, Wednesday
    # ==================================================
    def is_rollover_window(self, ts):
        trade_date = pd.to_datetime(ts).date()
        expiry = ExpiryResolver.current_month_expiry(trade_date)
        if trade_date.month != expiry.month:
            expiry = ExpiryResolver.next_month_expiry(trade_date)
        one_week_before = expiry - timedelta(days=7)
        return one_week_before <= trade_date < expiry and trade_date.weekday() == 2
