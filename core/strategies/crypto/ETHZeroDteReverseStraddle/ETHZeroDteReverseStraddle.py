"""ETH Daily Expiry Reverse Straddle (Strangle) — 12:00 PM IST entry, 5:00 PM IST exit on 15m candles."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, time
from typing import Any, Dict, List, Optional

import pandas as pd

from run.config import RUN_MODE, RunMode
from core.strategies.base import BaseStrategy
from core.strategies.deltaMktMixins import (
    DeltaMktMixins,
    _delta_source_from_ctx,
)
from core.strategies.IndiaMktMixins import IST, IndiaMktMixins

logger = logging.getLogger(__name__)

# Strategy constants
ENTRY_TIME = time(12, 0)      # 12:00 PM IST
EXIT_TIME = time(17, 0)       # 5:00 PM IST
STRIKE_OFFSET = 80.0          # 80 points away from ATM
LOTS = 1                      # 1 lot per leg
UNDERLYING = "ETHUSD"


@dataclass
class _PositionState:
    """Track open straddle position per expiry."""
    structure_id: str = ""
    call_strike: float = 0.0
    put_strike: float = 0.0
    expiry: str = ""
    entry_time: Optional[pd.Timestamp] = None
    call_trading_symbol: str = ""
    put_trading_symbol: str = ""


class ETHZeroDteReverseStraddle(DeltaMktMixins, IndiaMktMixins, BaseStrategy):
    """
    ETH Daily Expiry Reverse Straddle (short strangle) on 15m candles:

    - Entry: 12:00 PM IST (every weekday, skip Sat/Sun)
    - Buy ATM Call + Buy ATM Put
    - Sell Call 80 pts OTM + Sell Put 80 pts OTM
    - All legs: 1 lot each
    - Exit: 5:00 PM IST (same day)
    - Uses daily (0DTE) expiry
    """

    name = "ETHZeroDteReverseStraddle"
    underlying_symbols = [UNDERLYING]
    timeframe = "15"
    api = "DELTA"
    expiryType = "Daily"
    required_context = ["option_chain"]

    order_qty_lots = LOTS

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._active_symbol = UNDERLYING
        self._position_state: Optional[_PositionState] = None
        self._evaluated_bars: set[str] = set()
        self._entry_attempted_dates: set[date] = set()

    def _symbol_cfg(self) -> Dict[str, Any]:
        from core.strategies.crypto.DirectionalOptionSelling.constants import symbol_config
        return symbol_config(UNDERLYING)

    def get_warmup_period(self) -> int:
        return 50

    def _timestamp_ist(self, value: Any) -> pd.Timestamp:
        ts = pd.Timestamp(value)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts.tz_convert(IST)

    def _bar_key(self, candle: dict) -> str:
        symbol = str(candle.get("symbol") or "").strip().upper()
        tf = str(candle.get("timeframe") or self.timeframe)
        bt = candle.get("bucket_ts")
        if bt is not None:
            try:
                return f"{symbol}|{tf}|{int(float(bt))}"
            except (TypeError, ValueError):
                pass
        return f"{symbol}|{tf}|{self._timestamp_ist(candle['timestamp']).isoformat()}"

    def should_evaluate(self, candle: dict) -> bool:
        sym = str(candle.get("symbol") or "").strip().upper()
        if sym != UNDERLYING:
            return False

        # Skip weekends (Sat=5, Sun=6 in Python weekday)
        ts_ist = self._timestamp_ist(candle["timestamp"])
        if ts_ist.weekday() >= 5:
            return False

        # Deduplicate bars
        key = self._bar_key(candle)
        if key in self._evaluated_bars:
            return False
        self._evaluated_bars.add(key)
        if len(self._evaluated_bars) > 1000:
            self._evaluated_bars = set(sorted(self._evaluated_bars)[-500:])

        return True

    def _is_entry_bar(self, candle: dict) -> bool:
        """True if this 15m bar closes at 12:00 PM IST."""
        ts_ist = self._timestamp_ist(candle["timestamp"])
        # 15m bar closes at :00, :15, :30, :45 - check if close time is 12:00
        bar_close = (ts_ist + pd.Timedelta(minutes=15)).time().replace(second=0, microsecond=0)
        return bar_close == ENTRY_TIME

    def _is_exit_bar(self, candle: dict) -> bool:
        """True if this 15m bar closes at or after 5:00 PM IST."""
        ts_ist = self._timestamp_ist(candle["timestamp"])
        bar_close = (ts_ist + pd.Timedelta(minutes=15)).time().replace(second=0, microsecond=0)
        return bar_close >= EXIT_TIME

    def _0dte_expiry_code(self, candle: dict) -> str:
        """Today's daily expiry code (DDMMYY)."""
        return self._timestamp_ist(candle["timestamp"]).date().strftime("%d%m%y")

    def _select_atm_strike(self, candle: dict, ctx: Any) -> Optional[float]:
        """Find ATM strike from option chain."""
        source = _delta_source_from_ctx(ctx)
        if source is None:
            return None

        root = "ETH"
        spot = float(candle.get("close", 0))
        if spot <= 0:
            return None

        products = source.get_products(use_cache=True) or []
        prefix_c = f"C-{root}-"
        prefix_p = f"P-{root}-"

        matching = [
            p for p in products
            if str(p.get("symbol") or "").upper().startswith(prefix_c)
            or str(p.get("symbol") or "").upper().startswith(prefix_p)
        ]

        if not matching:
            return None

        target_expiry = self._0dte_expiry_code(candle)

        strikes = []
        for p in matching:
            if self._product_expiry(p) != target_expiry:
                continue
            strike = self._product_strike(p)
            if strike is not None:
                strikes.append(strike)

        if not strikes:
            return None

        atm_strike = min(strikes, key=lambda k: abs(k - spot))
        return atm_strike

    @staticmethod
    def _product_expiry(product: dict) -> str:
        symbol = str(product.get("symbol") or "").upper()
        parts = symbol.split("-")
        return str(parts[-1]).strip() if len(parts) >= 4 else ""

    @staticmethod
    def _product_strike(product: dict) -> Optional[float]:
        value = product.get("strike_price")
        if value is None:
            parts = str(product.get("symbol") or "").split("-")
            value = parts[2] if len(parts) >= 4 else None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _get_ticker(self, ctx: Any, symbol: str) -> Optional[dict]:
        source = _delta_source_from_ctx(ctx)
        if source is None:
            return None
        try:
            return source.get_ticker(symbol)
        except Exception:
            return None

    def _sell_premium(self, ticker: Any) -> Optional[float]:
        if not isinstance(ticker, dict):
            return None
        quotes = ticker.get("quotes") or {}
        try:
            bid = float(quotes.get("best_bid") or 0)
        except (TypeError, ValueError):
            bid = 0.0
        return bid if bid > 0 else None

    def _build_entry_intents(
        self,
        candle: dict,
        ctx: Any,
        atm_strike: float,
        expiry: str,
    ) -> List[Any]:
        """Build 4-leg entry intents: Buy ATM CE, Buy ATM PE, Sell OTM CE, Sell OTM PE."""
        spot = float(candle.get("close", 0))
        ts_ist = self._timestamp_ist(candle["timestamp"])
        structure_id = (
            f"{self.name}:{UNDERLYING}:straddle:"
            f"{ts_ist.date()}:{ts_ist.strftime('%H%M')}"
        )

        call_otm_strike = atm_strike + STRIKE_OFFSET
        put_otm_strike = atm_strike - STRIKE_OFFSET

        intents = []

        # 1. Buy ATM Call
        call_atm_symbol = f"C-ETH-{int(atm_strike)}-{expiry}"
        inst = ctx.instrument_store.intent_creation_details(
            call_atm_symbol, ctx.exchange, expiry, "CE", atm_strike
        )
        if inst:
            ticker = self._get_ticker(ctx, call_atm_symbol)
            premium = self._sell_premium(ticker) or 0
            intent = self.create_order_intent(
                inst=inst,
                side="BUY",
                qty=LOTS,
                price=premium,
                order_type="LIMIT",
                strategy=self.name,
                candle_ts=candle["timestamp"],
                structure_id=structure_id,
                tag="LONG_CE_ATM",
                symbol=UNDERLYING,
                action="ENTRY",
                metadata_extras={"leg": "LONG_CE_ATM", "atm_strike": atm_strike},
            )
            intents.append(intent)

        # 2. Buy ATM Put
        put_atm_symbol = f"P-ETH-{int(atm_strike)}-{expiry}"
        inst = ctx.instrument_store.intent_creation_details(
            put_atm_symbol, ctx.exchange, expiry, "PE", atm_strike
        )
        if inst:
            ticker = self._get_ticker(ctx, put_atm_symbol)
            premium = self._sell_premium(ticker) or 0
            intent = self.create_order_intent(
                inst=inst,
                side="BUY",
                qty=LOTS,
                price=premium,
                order_type="LIMIT",
                strategy=self.name,
                candle_ts=candle["timestamp"],
                structure_id=structure_id,
                tag="LONG_PE_ATM",
                symbol=UNDERLYING,
                action="ENTRY",
                metadata_extras={"leg": "LONG_PE_ATM", "atm_strike": atm_strike},
            )
            intents.append(intent)

        # 3. Sell OTM Call (80 pts away)
        call_otm_symbol = f"C-ETH-{int(call_otm_strike)}-{expiry}"
        inst = ctx.instrument_store.intent_creation_details(
            call_otm_symbol, ctx.exchange, expiry, "CE", call_otm_strike
        )
        if inst:
            ticker = self._get_ticker(ctx, call_otm_symbol)
            premium = self._sell_premium(ticker) or 0
            intent = self.create_order_intent(
                inst=inst,
                side="SELL",
                qty=LOTS,
                price=premium,
                order_type="LIMIT",
                strategy=self.name,
                candle_ts=candle["timestamp"],
                structure_id=structure_id,
                tag="SHORT_CE_OTM",
                symbol=UNDERLYING,
                action="ENTRY",
                metadata_extras={
                    "leg": "SHORT_CE_OTM",
                    "strike": call_otm_strike,
                    "entry_premium": premium,
                    "sl_premium_mult": 2.0,
                },
            )
            intents.append(intent)

        # 4. Sell OTM Put (80 pts away)
        put_otm_symbol = f"P-ETH-{int(put_otm_strike)}-{expiry}"
        inst = ctx.instrument_store.intent_creation_details(
            put_otm_symbol, ctx.exchange, expiry, "PE", put_otm_strike
        )
        if inst:
            ticker = self._get_ticker(ctx, put_otm_symbol)
            premium = self._sell_premium(ticker) or 0
            intent = self.create_order_intent(
                inst=inst,
                side="SELL",
                qty=LOTS,
                price=premium,
                order_type="LIMIT",
                strategy=self.name,
                candle_ts=candle["timestamp"],
                structure_id=structure_id,
                tag="SHORT_PE_OTM",
                symbol=UNDERLYING,
                action="ENTRY",
                metadata_extras={
                    "leg": "SHORT_PE_OTM",
                    "strike": put_otm_strike,
                    "entry_premium": premium,
                    "sl_premium_mult": 2.0,
                },
            )
            intents.append(intent)

        # Store position state
        self._position_state = _PositionState(
            structure_id=structure_id,
            call_strike=atm_strike,
            put_strike=atm_strike,
            expiry=expiry,
            entry_time=ts_ist,
            call_trading_symbol=call_otm_symbol,
            put_trading_symbol=put_otm_symbol,
        )

        logger.info(
            "%s ENTRY signaled structure_id=%s atm=%.0f call_otm=%.0f put_otm=%.0f expiry=%s spot=%.2f",
            self.name, structure_id, atm_strike, call_otm_strike, put_otm_strike, expiry, spot
        )

        return intents

    def _build_exit_intents(self, candle: dict, ctx: Any) -> List[Any]:
        """Build exit intents for all 4 legs."""
        if not self._position_state:
            return []

        state = self._position_state
        intents = []
        ts_ist = self._timestamp_ist(candle["timestamp"])

        legs = [
            ("LONG_CE_ATM", "SELL", state.call_strike, "CE"),
            ("LONG_PE_ATM", "SELL", state.put_strike, "PE"),
            ("SHORT_CE_OTM", "BUY", state.call_strike + STRIKE_OFFSET, "CE"),
            ("SHORT_PE_OTM", "BUY", state.put_strike - STRIKE_OFFSET, "PE"),
        ]

        for tag, side, strike, opt_type in legs:
            symbol = f"{'C' if opt_type == 'CE' else 'P'}-ETH-{int(strike)}-{state.expiry}"
            inst = ctx.instrument_store.intent_creation_details(
                symbol, ctx.exchange, state.expiry, opt_type, strike
            )
            if inst:
                intent = self.create_order_intent(
                    inst=inst,
                    side=side,
                    qty=LOTS,
                    price=None,
                    order_type="LIMIT",
                    strategy=self.name,
                    candle_ts=candle["timestamp"],
                    structure_id=state.structure_id,
                    tag=f"{tag}_EXIT",
                    symbol=UNDERLYING,
                    action="EXIT",
                    metadata_extras={"exit_reason": "time_exit", "leg": tag},
                )
                intents.append(intent)

        logger.info(
            "%s EXIT signaled structure_id=%s reason=time_exit",
            self.name, state.structure_id
        )

        self._position_state = None
        return intents

    def on_candle(self, candle: dict, ctx: Any) -> Any:
        if not self.should_evaluate(candle):
            return None

        if self._is_entry_bar(candle):
            trade_date = self._timestamp_ist(candle["timestamp"]).date()
            if trade_date in self._entry_attempted_dates:
                return None
            if self._position_state is not None:
                return None

            atm_strike = self._select_atm_strike(candle, ctx)
            if atm_strike is None:
                logger.warning("%s: could not find ATM strike for entry", self.name)
                return None

            expiry = self._0dte_expiry_code(candle)
            self._entry_attempted_dates.add(trade_date)
            return self._build_entry_intents(candle, ctx, atm_strike, expiry)

        elif self._is_exit_bar(candle):
            if self._position_state is None:
                return None
            return self._build_exit_intents(candle, ctx)

        return None

    def should_exit(
        self, position: Any, candle: Any, ctx: Any = None
    ) -> bool:
        """Force exit at 5 PM if position still open."""
        if self._position_state is None:
            return False
        ts_ist = self._timestamp_ist(candle["timestamp"])
        bar_close = (ts_ist + pd.Timedelta(minutes=15)).time().replace(second=0, microsecond=0)
        return bar_close >= EXIT_TIME

    def on_forced_exit(self, **kwargs: Any) -> None:
        """Clear position state on forced exit."""
        self._position_state = None