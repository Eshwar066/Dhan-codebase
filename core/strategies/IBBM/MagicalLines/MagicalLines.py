"""
Magical Lines: quarterly NIFTY option selling (Dhan).

Daily decision on the NSE 30-minute bar that opens 15:15 IST (covers 15:20).
Candle colour uses the 09:15 session open vs that bar's close:
green → short PE, red → short CE.

Magical line at entry:
- PUT:  spot - spot * 0.25%
- CALL: spot + spot * 0.25%

Main strike is the listed strike nearest that line. Hedge is 500 points
further OTM on the same quarterly expiry.

A new line is allowed only when no open magical line sits inside ±3% of spot.
Further lines follow the first line's direction after spot has moved 3% from it,
and only when the 15:15 candle colour still matches that direction.

Exits:
- One week before the position's quarterly expiry.
- Next session's 15:15 bar: spot has crossed that position's magical line by more
  than the 0.2% buffer → exit and sell the opposite side (new line from spot).
  A close inside the 0.2% buffer is held for the next day.
- Every 30-minute bar: spot is 0.5% or more through the magical line → exit
  immediately, no reverse.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, replace
from datetime import date, time, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from run.config import RUN_MODE, RunMode
from core.strategies.base import BaseStrategy
from core.strategies.IndiaMktMixins import IST, IndiaMktMixins
from core.strategies.meta import pack_strategy_meta
from core.utils.expiry_resolver import ExpiryResolver

logger = logging.getLogger(__name__)

# NSE 30m bars open on :15 / :45 from 09:15. The 15:15 bar is the 15:20 decision.
DECISION_TIMES = {time(15, 15), time(15, 20)}
SESSION_OPEN_TIME = time(9, 15)

MAGICAL_LINE_PCT = 0.0025  # 0.25%
LEVEL_GAP_PCT = 0.03  # 3% between open magical lines
BUFFER_PCT = 0.002  # 0.2% — hold if the daily close is this close to the line
ADVERSE_EXIT_PCT = 0.005  # 0.5% through the line (covers the 0.5–1% band and beyond)
HEDGE_POINTS = 500
STRIKE_STEP = 50
EXPIRY_EXIT_DAYS = 7


@dataclass(frozen=True)
class _MlMeta:
    symbol: str
    entry_date: date
    magical_line: float
    direction: str
    level: int
    option_type: str


@dataclass
class _PendingReversal:
    intents: List[Any]
    candle: dict


class MagicalLines(IndiaMktMixins, BaseStrategy):
    """Quarterly magical-line short options with a 500-point same-expiry hedge."""

    name = "MagicalLines"
    underlying_symbols = ["NIFTY"]
    timeframe = "30"
    required_context = ["option_chain"]
    api = "DHAN"
    expiryType = "QUARTERLY"
    otm_strike_step = STRIKE_STEP
    otm_strike_count = 16
    option_chain_strike_step = STRIKE_STEP

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._meta_by_structure_id: Dict[str, _MlMeta] = {}
        self._session_open: Dict[Tuple[str, date], float] = {}
        self._exit_reason_by_structure_id: Dict[str, str] = {}
        self._pending_exit_structure_ids: set[str] = set()
        self._pending_reversal_by_exit_structure_id: Dict[str, _PendingReversal] = {}
        self._entry_signaled_keys: set[str] = set()

    def get_warmup_period(self):
        return 0

    def on_candle_rollover(self, open_positions, candle, ctx):
        """Hedge shares the quarterly expiry; the book is closed a week before it."""
        return []

    def calculate_hedge_strike(self, sold_strike, option_type):
        sold = int(sold_strike)
        opt = str(option_type or "").upper()
        if opt in ("PE", "PUT"):
            return sold - HEDGE_POINTS
        return sold + HEDGE_POINTS

    # ---------------------------------------------------------------- time

    def _ist_ts(self, candle: dict) -> pd.Timestamp:
        ts = pd.Timestamp(candle["timestamp"])
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts.tz_convert(IST)

    def _trade_date(self, candle: dict) -> date:
        return self._ist_ts(candle).date()

    def _ist_clock(self, candle: dict) -> time:
        return self._ist_ts(candle).time().replace(second=0, microsecond=0)

    def _is_decision_bar(self, candle: dict) -> bool:
        return self._ist_clock(candle) in DECISION_TIMES

    def should_evaluate(self, candle):
        return self._is_decision_bar(candle)

    # ---------------------------------------------------------------- session

    def _remember_session_open(self, candle: dict, ctx=None) -> Optional[float]:
        symbol = str(candle.get("symbol") or "")
        trade_date = self._trade_date(candle)
        key = (symbol, trade_date)
        if key in self._session_open:
            return self._session_open[key]

        candidates = [candle]
        if ctx is not None and hasattr(ctx, "get_recent_candles"):
            try:
                candidates = list(ctx.get_recent_candles(48) or []) + candidates
            except Exception:
                candidates = [candle]

        for bar in candidates:
            if not isinstance(bar, dict) or str(bar.get("symbol") or symbol) != symbol:
                continue
            try:
                if self._trade_date(bar) != trade_date:
                    continue
                if self._ist_clock(bar) != SESSION_OPEN_TIME:
                    continue
                opened = float(bar.get("open") or bar.get("close") or 0)
            except (TypeError, ValueError, KeyError):
                continue
            if opened > 0:
                self._session_open[key] = opened
                return opened
        return self._session_open.get(key)

    def _daily_colour(self, candle: dict, ctx=None) -> Optional[str]:
        """GREEN when the 15:15 close is above the 09:15 open, else RED."""
        opened = self._remember_session_open(candle, ctx)
        if opened is None or opened <= 0:
            return None
        close = float(candle["close"])
        return "GREEN" if close > opened else "RED"

    # ---------------------------------------------------------------- levels

    @staticmethod
    def magical_line(spot: float, direction: str) -> float:
        if direction == "SHORT_PE":
            return spot * (1.0 - MAGICAL_LINE_PCT)
        return spot * (1.0 + MAGICAL_LINE_PCT)

    @staticmethod
    def strike_near(magical_line: float, step: int = STRIKE_STEP) -> int:
        step = int(step) or STRIKE_STEP
        return int(round(float(magical_line) / step) * step)

    @staticmethod
    def band_contains_line(spot: float, magical_line: float, pct: float = LEVEL_GAP_PCT) -> bool:
        if spot <= 0 or magical_line <= 0:
            return False
        return spot * (1.0 - pct) <= magical_line <= spot * (1.0 + pct)

    @staticmethod
    def adverse_distance(direction: str, spot: float, magical_line: float) -> float:
        """Fraction spot has moved through the line (0 when still on the safe side)."""
        if magical_line <= 0 or spot <= 0:
            return 0.0
        if direction == "SHORT_PE":
            if spot >= magical_line:
                return 0.0
            return (magical_line - spot) / magical_line
        if spot <= magical_line:
            return 0.0
        return (spot - magical_line) / magical_line

    @staticmethod
    def inside_buffer(spot: float, magical_line: float) -> bool:
        if magical_line <= 0 or spot <= 0:
            return False
        return abs(spot - magical_line) / magical_line <= BUFFER_PCT

    def _structure_id(self, meta: _MlMeta) -> str:
        return (
            f"{self.name}:{meta.symbol}:L{meta.level}:{meta.direction}:"
            f"{meta.entry_date.isoformat()}:{meta.magical_line:.2f}:{uuid.uuid4().hex[:6]}"
        )

    def _meta_from_structure_id(self, structure_id: str) -> Optional[_MlMeta]:
        parts = str(structure_id or "").split(":")
        # MagicalLines : SYMBOL : L{n} : SHORT_PE|SHORT_CE : YYYY-MM-DD : ml : uid
        if len(parts) < 6 or parts[0] != self.name:
            return None
        level_token = parts[2]
        if not level_token.startswith("L"):
            return None
        direction = parts[3]
        if direction not in ("SHORT_PE", "SHORT_CE"):
            return None
        try:
            meta = _MlMeta(
                symbol=parts[1],
                entry_date=date.fromisoformat(parts[4]),
                magical_line=float(parts[5]),
                direction=direction,
                level=int(level_token[1:]),
                option_type="PE" if direction == "SHORT_PE" else "CE",
            )
        except (TypeError, ValueError):
            return None
        return meta

    def _meta_for(self, position) -> Optional[_MlMeta]:
        sid = str(getattr(position, "structure_id", "") or "")
        meta = self._meta_by_structure_id.get(sid)
        if meta is None:
            meta = self._meta_from_structure_id(sid)
            if meta is not None:
                self._meta_by_structure_id[sid] = meta
        return meta

    def _open_metas(self, candle: dict, ctx) -> List[_MlMeta]:
        symbol = str(candle.get("symbol") or "")
        store = getattr(ctx, "position_store", None)
        if store is None:
            return []
        try:
            positions = store.get_open_positions(underlying=symbol, strategy=self.name) or []
        except TypeError:
            positions = store.get_open_positions(strategy=self.name) or []
        metas: List[_MlMeta] = []
        for pos in positions:
            if str(getattr(pos, "tag", "") or "").upper() != "MAIN":
                continue
            if int(getattr(pos, "net_qty", 0) or 0) == 0:
                continue
            inst = getattr(pos, "instrument", None)
            underlying = str(getattr(inst, "underlying_symbol", "") or getattr(inst, "symbol", "") or "")
            sid = str(getattr(pos, "structure_id", "") or "")
            if underlying and underlying.upper() not in (symbol.upper(), ""):
                if not sid.startswith(f"{self.name}:{symbol}:"):
                    continue
            meta = self._meta_for(pos)
            if meta is not None and meta.symbol == symbol:
                metas.append(meta)
        return metas

    def _quarterly_expiry(self, candle: dict, ctx) -> Optional[date]:
        trade_date = self._trade_date(candle)
        expiry_list = []
        if ctx is not None and hasattr(ctx, "get_expiry_list"):
            try:
                expiry_list = ctx.get_expiry_list() or []
            except Exception:
                expiry_list = []
        try:
            resolved = ExpiryResolver.resolve(
                expiry_list=expiry_list,
                trade_date=trade_date,
                api=self.api,
                expiry_pref="QUARTERLY",
            )
        except (TypeError, ValueError):
            resolved = None
        if resolved is not None and ExpiryResolver.is_calendar_expiry(resolved):
            return ExpiryResolver.as_calendar_date(resolved)
        return ExpiryResolver.quarterly_target_expiry_date(trade_date)

    def _in_expiry_exit_week(self, trade_day: date, expiry: date) -> bool:
        return trade_day >= (expiry - timedelta(days=EXPIRY_EXIT_DAYS))

    def _entry_plan(
        self, candle: dict, ctx, metas: List[_MlMeta]
    ) -> Optional[Tuple[str, int]]:
        """
        Return (direction, level) for a 15:15 entry, or None.

        Flat book: candle colour picks the side.
        Open book: only add when spot is outside every open line's ±3% band,
        at least 3% beyond the first line, and today's colour matches that side.
        """
        colour = self._daily_colour(candle, ctx)
        if colour is None:
            logger.info(
                "MagicalLines entry skipped: session open missing sym=%s ts=%s",
                candle.get("symbol"),
                candle.get("timestamp"),
            )
            return None

        if not metas:
            direction = "SHORT_PE" if colour == "GREEN" else "SHORT_CE"
            return direction, 1

        spot = float(candle["close"])
        if any(self.band_contains_line(spot, m.magical_line) for m in metas):
            return None

        first = min(metas, key=lambda m: (m.level, m.entry_date.toordinal()))
        if first.direction == "SHORT_PE":
            if colour != "GREEN":
                return None
            if spot < first.magical_line * (1.0 + LEVEL_GAP_PCT):
                return None
        elif first.direction == "SHORT_CE":
            if colour != "RED":
                return None
            if spot > first.magical_line * (1.0 - LEVEL_GAP_PCT):
                return None
        else:
            return None
        return first.direction, max(m.level for m in metas) + 1

    # ---------------------------------------------------------------- chain / intents

    def _resolve_main_expiry(self, candle: dict, ctx) -> Optional[date]:
        self.fetch_option_chain(
            candle,
            ctx,
            "CE",
            expiry_pref="QUARTERLY",
        )
        expiry = self._selected_expiry_calendar_date(ctx)
        if expiry is not None:
            return expiry
        return self._quarterly_expiry(candle, ctx)

    def _row_for_strike(self, candle, ctx, option_type: str, strike: int):
        strikes = [int(s) for s in (getattr(ctx, "otm_strikes", None) or [])]
        if strike not in strikes:
            strikes.append(strike)
        hedge = self.calculate_hedge_strike(strike, option_type)
        if hedge not in strikes:
            strikes.append(hedge)
        ctx.otm_strikes = strikes

        params = {
            "exchange": ctx.exchange,
            "interval": self._option_data_interval(),
            "expiry_code": ctx.selected_expiry,
            "strike": [str(s) for s in strikes],
            "option_type": option_type,
            "instrument": "OPTIDX",
            "exchangeSegment": "NSE_FNO",
            "expiry_flag": self._dhan_expiry_flag(),
            "securityId": self._dhan_option_security_id(),
        }
        if str(self.api or "").upper() == "DHAN" and RUN_MODE != RunMode.BACKTEST:
            chain = self._fetch_live_option_chain_with_retry(
                ctx, params, expiry_pref="QUARTERLY"
            )
        else:
            chain = ctx.option_chain_service.get_chain(
                api=self.api, ctx=ctx, params=params
            )
        self._remember_chain_fetch_expiry(ctx, chain)
        chain_exp = self._expiry_from_option_chain(chain)
        selected = self._selected_expiry_calendar_date(ctx)
        if chain_exp is not None and selected is not None and chain_exp != selected:
            logger.warning(
                "MagicalLines chain expiry %s != selected %s",
                chain_exp,
                selected,
            )
            return None
        if chain is not None:
            self._last_option_chain = chain

        row = self._strike_row_from_chain(chain, strike, option_type) if chain is not None else None
        if row is not None:
            return row

        if RUN_MODE == RunMode.BACKTEST:
            px = self.get_option_price_at_candle(
                candle,
                ctx,
                strike,
                option_type,
                self._selected_expiry_calendar_date(ctx),
            )
            if px is not None and float(px) > 0:
                return {"close": float(px), "strike": strike}
        return None

    def _build_entry_intents(
        self,
        candle: dict,
        ctx,
        *,
        direction: str,
        level: int,
        entry_date: Optional[date] = None,
    ) -> Optional[List[Any]]:
        symbol = str(candle.get("symbol") or "")
        spot = float(candle["close"])
        option_type = "PE" if direction == "SHORT_PE" else "CE"
        ml = self.magical_line(spot, direction)
        strike = self.strike_near(ml)
        trade_day = entry_date or self._trade_date(candle)

        signal_key = f"{symbol}|{trade_day.isoformat()}|{direction}|L{level}|{strike}"
        if signal_key in self._entry_signaled_keys:
            return None

        expiry = self._resolve_main_expiry(candle, ctx)
        if expiry is None:
            logger.warning(
                "MagicalLines entry skipped: no quarterly expiry sym=%s ts=%s",
                symbol,
                candle.get("timestamp"),
            )
            return None
        if self._in_expiry_exit_week(trade_day, expiry):
            logger.info(
                "MagicalLines entry skipped: inside expiry week sym=%s trade=%s expiry=%s",
                symbol,
                trade_day,
                expiry,
            )
            return None

        row = self._row_for_strike(candle, ctx, option_type, strike)
        if row is None:
            logger.warning(
                "MagicalLines entry skipped: no premium sym=%s strike=%s opt=%s expiry=%s",
                symbol,
                strike,
                option_type,
                expiry,
            )
            return None

        trading_symbol = ExpiryResolver.build_option_symbol(
            symbol, expiry, strike, option_type, include_year=True
        )
        inst = ctx.instrument_store.intent_creation_details(
            trading_symbol,
            ctx.exchange,
            expiry,
            option_type,
            strike,
            prefer_monthly=True,
        )
        if inst is None:
            logger.warning(
                "MagicalLines entry skipped: instrument missing %s", trading_symbol
            )
            return None

        meta = _MlMeta(
            symbol=symbol,
            entry_date=trade_day,
            magical_line=ml,
            direction=direction,
            level=level,
            option_type=option_type,
        )
        structure_id = self._structure_id(meta)
        premium = self._ltp_from_strike_row_backtest(row, option_type)
        if RUN_MODE in (RunMode.LIVE, RunMode.PAPER):
            live_px = self._execution_price_from_chain_row(row, option_type, "SELL")
            if live_px is not None and live_px > 0:
                premium = live_px

        extras = pack_strategy_meta(
            self.name,
            {
                "symbol": symbol,
                "direction": direction,
                "option_type": option_type,
                "level": level,
                "magical_line": ml,
                "entry_date": trade_day.isoformat(),
                "entry_spot": spot,
                "main_strike": strike,
                "main_expiry": expiry.isoformat(),
                "main_symbol": trading_symbol,
                "entry_main_premium": premium,
            },
        )
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
            metadata_extras=extras,
        )
        hedge_intent = self.create_hedge_intent(
            parent_sell_intent=sell_intent,
            candle=candle,
            ctx=ctx,
        )
        if hedge_intent is not None:
            hedge_inst = hedge_intent.instrument
            hedge_expiry = pd.to_datetime(hedge_inst.expiry).date()
            if hedge_expiry != expiry or int(hedge_inst.strike) != self.calculate_hedge_strike(
                strike, option_type
            ):
                logger.warning(
                    "MagicalLines hedge mismatch main=%s %s hedge=%s %s; dropping hedge",
                    expiry,
                    strike,
                    hedge_expiry,
                    hedge_inst.strike,
                )
                hedge_intent = None
            else:
                hedge_intent = replace(hedge_intent, metadata_extras=extras)

        self._meta_by_structure_id[structure_id] = meta
        self._entry_signaled_keys.add(signal_key)
        logger.info(
            "MagicalLines entry L%s %s ml=%.2f strike=%s expiry=%s hedge=%s",
            level,
            direction,
            ml,
            strike,
            expiry,
            getattr(getattr(hedge_intent, "instrument", None), "strike", None),
        )
        if hedge_intent is not None:
            return [hedge_intent, sell_intent]
        return [sell_intent]

    def on_candle(self, candle, ctx):
        if not self._is_decision_bar(candle):
            return None
        self._remember_session_open(candle, ctx)

        expiry = self._quarterly_expiry(candle, ctx)
        trade_day = self._trade_date(candle)
        if expiry is not None and self._in_expiry_exit_week(trade_day, expiry):
            return None

        metas = self._open_metas(candle, ctx)
        plan = self._entry_plan(candle, ctx, metas)
        if plan is None:
            return None
        direction, level = plan
        return self._build_entry_intents(
            candle, ctx, direction=direction, level=level, entry_date=trade_day
        )

    # ---------------------------------------------------------------- exits

    def _exit_reason(self, position, candle, ctx) -> Optional[str]:
        meta = self._meta_for(position)
        if meta is None:
            return None
        trade_day = self._trade_date(candle)
        expiry = getattr(getattr(position, "instrument", None), "expiry", None)
        if expiry is not None:
            try:
                exp_d = pd.to_datetime(expiry).date()
            except (TypeError, ValueError):
                exp_d = None
            if exp_d is not None and self._in_expiry_exit_week(trade_day, exp_d):
                return "EXPIRY_WEEK"

        spot = float(candle["close"])
        dist = self.adverse_distance(meta.direction, spot, meta.magical_line)
        if dist >= ADVERSE_EXIT_PCT:
            return "ADVERSE"

        if not self._is_decision_bar(candle):
            return None
        if trade_day <= meta.entry_date:
            return None
        if self.inside_buffer(spot, meta.magical_line):
            return None
        if dist > BUFFER_PCT:
            return "REVERSAL"
        return None

    def should_exit(self, position, candle, ctx=None):
        if str(getattr(position, "tag", "") or "").upper() != "MAIN":
            return False
        sid = str(getattr(position, "structure_id", "") or "")
        if sid in self._pending_exit_structure_ids:
            return False
        self._remember_session_open(candle, ctx)
        reason = self._exit_reason(position, candle, ctx)
        if not reason:
            return False
        self._exit_reason_by_structure_id[sid] = reason
        logger.info(
            "MagicalLines exit %s structure=%s spot=%s",
            reason,
            sid,
            candle.get("close"),
        )
        return True

    def _arm_reversal(self, position, candle, ctx) -> None:
        meta = self._meta_for(position)
        if meta is None:
            return
        reverse = "SHORT_CE" if meta.direction == "SHORT_PE" else "SHORT_PE"
        intents = self._build_entry_intents(
            candle,
            ctx,
            direction=reverse,
            level=1,
            entry_date=self._trade_date(candle),
        )
        if not intents:
            logger.warning(
                "MagicalLines reversal not armed: opposite entry unavailable structure=%s",
                position.structure_id,
            )
            return
        self._pending_reversal_by_exit_structure_id[str(position.structure_id)] = (
            _PendingReversal(
                intents=list(intents),
                candle={
                    "symbol": candle.get("symbol"),
                    "timestamp": candle.get("timestamp"),
                    "open": candle.get("open"),
                    "close": candle.get("close"),
                    "exchange": candle.get("exchange"),
                },
            )
        )
        logger.info(
            "MagicalLines reversal armed %s → %s structure=%s",
            meta.direction,
            reverse,
            position.structure_id,
        )

    def on_position_exit(self, position, candle, ctx):
        structure_id = str(position.structure_id)
        intent_store = getattr(ctx, "intent_store", None)
        if intent_store is not None and intent_store.has_pending_intent(
            strategy=self.name,
            structure_id=structure_id,
            tags=["MAIN_EXIT"],
            actions=["EXIT"],
        ):
            return []

        self._pending_exit_structure_ids.add(structure_id)
        reason = self._exit_reason_by_structure_id.get(structure_id)

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
        exit_intent = self.create_order_intent(
            inst=position.instrument,
            side="BUY" if position.net_qty < 0 else "SELL",
            qty=qty_lots,
            price=price,
            order_type="LIMIT",
            strategy=self.name,
            candle_ts=candle["timestamp"],
            structure_id=structure_id,
            tag="MAIN_EXIT",
            symbol=candle["symbol"],
            action="EXIT",
        )
        intents = [exit_intent]
        hedge_exit = self.create_hedge_exit_intent(position, candle, ctx)
        if hedge_exit:
            intents.append(hedge_exit)

        if reason == "REVERSAL":
            self._arm_reversal(position, candle, ctx)
        return intents

    def on_main_exit_filled(self, **kwargs: Any) -> List[Tuple[Any, dict]]:
        tag_u = str(kwargs.get("tag") or "").upper()
        if tag_u != "MAIN_EXIT":
            return []
        sid = str(kwargs.get("structure_id") or "")
        pending = self._pending_reversal_by_exit_structure_id.pop(sid, None)
        if pending is None:
            return []
        self._pending_exit_structure_ids.discard(sid)
        logger.info(
            "MagicalLines reversal ENTRY on MAIN_EXIT fill structure=%s intents=%s",
            sid,
            len(pending.intents),
        )
        return [(intent, pending.candle) for intent in pending.intents]

    def on_structure_exit(self, structure_id, **kwargs):
        super().on_structure_exit(structure_id, **kwargs)
        sid = str(structure_id or "")
        self._pending_exit_structure_ids.discard(sid)
        self._exit_reason_by_structure_id.pop(sid, None)
        self._pending_reversal_by_exit_structure_id.pop(sid, None)

    def on_forced_exit(self, **kwargs: Any) -> None:
        sid = str(kwargs.get("structure_id") or "")
        if not sid:
            return
        self._pending_reversal_by_exit_structure_id.pop(sid, None)
        if bool(kwargs.get("position_closed")):
            self.on_structure_exit(structure_id=sid)
        else:
            self._pending_exit_structure_ids.discard(sid)
