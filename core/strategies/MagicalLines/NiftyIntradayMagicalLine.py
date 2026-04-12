"""
Nifty Intraday Magical Line (Dhan / NSE index options)

Rules (spec)
- Entry on the **9:15–9:30** 15m bar (closes **9:30**): **green** (close > open) → short **PE**;
  **red** → short **CE**. **Magical line** = that bar’s **close** (9:30 close), fixed for the
  session; reversal entries do **not** replace it with the reversal candle close.
- After entry, risk is reviewed on the same schedule as broker / TradingView **1h** bars
  closing at **10:15, 11:15, …, 15:15 IST** (minute ``:15``), plus **15:15** square-off.
  Entry remains on the **15m** bar that closes **9:30** (9:15–9:30 window).
- Stop loss: 15% rise in short option premium from entry.
- Monthly expiry; after the 15th calendar day use the next monthly series (rollover).
- Strike: prefer |delta| in [0.20, 0.30] when chain columns expose delta; else first suitable row.
- Re-entry after SL: wait 1 hour; if the 15m candle is still the same colour as at entry and
  spot is back within tolerance of the prior entry spot (“previous sell point”), allow one
  re-sell for that session.
- **Reversal:** compare **spot** to the **session** ``meta.magical_line`` (9:30 close from first
  entry): **spot > ML → short PE**, else **short CE**. New legs after reversal keep the same ML.

Use a **15**-minute feed so the 9:15–9:30 close (9:30) exists; SL/EOD still align to **:15**
hourly closes (10:15 … 15:15) on those 15m candles.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, time
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd

from run.config import RUN_MODE, RunMode
from core.strategies.base import BaseStrategy
from core.strategies.IndiaMktMixins import IndiaMktMixins, IST
from core.utils.expiry_resolver import ExpiryResolver


# Session (IST)
ENTRY_CANDLE_TIME = time(9, 15)  # close of 9:15–9:30 15m bar (formation window 9:15–9:30)
EOD_EXIT_TIME = time(15, 15)

# 1h bar closes (IST) per Dhan / TradingView alignment — use 15m candles whose close time matches.
HOURLY_MONITOR_HOUR_START = 10  # first 1h close after entry is 10:15
HOURLY_MONITOR_HOUR_END = 15  # … through 15:15 (EOD)

STRIKE_STEP = 100

DELTA_ABS_MIN = 0.20
DELTA_ABS_MAX = 0.30

SL_PCT = 0.15
ANCHOR_SPOT_TOLERANCE = 0.001  # 0.1% around prior entry spot for re-entry


@dataclass(frozen=True)
class _NimlMeta:
    symbol: str
    entry_date: date
    magical_line: float
    entry_premium: float
    entry_spot: float
    entry_green: bool
    direction: str
    level: int


@dataclass
class _ReentryWait:
    after_ts: pd.Timestamp
    entry_green: bool
    anchor_spot: float
    trade_dt: date
    next_level: int


@dataclass(frozen=True)
class _PendingReversal:
    entry_intent: Any
    candle: dict


class NiftyIntradayMagicalLine(IndiaMktMixins, BaseStrategy):
    """
    Intraday Nifty option selling for Dhan (NSE OPTIDX chain via ``api='NSE'``).
    """

    name = "NiftyIntradayMagicalLine"
    timeframe = "15"
    required_context = ["option_chain"]
    api = "DHAN"
    expiryType = "MONTHLY"
    valid_times = {ENTRY_CANDLE_TIME}
    delta_abs_min = DELTA_ABS_MIN
    delta_abs_max = DELTA_ABS_MAX

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._meta_by_structure_id: Dict[str, _NimlMeta] = {}
        self._exit_reason_by_structure_id: Dict[str, str] = {}
        self._pending_exit_structure_ids: set[str] = set()
        self._reentry_wait: Dict[str, _ReentryWait] = {}
        self._pending_reversal_by_exit_structure_id: Dict[str, _PendingReversal] = {}

    def get_warmup_period(self):
        return 0

    def should_evaluate(self, candle) -> bool:
        return True

    def _calendar_expiry_for_symbol(self, ctx) -> Optional[Union[date, str]]:
        """
        DHAN keeps ``ctx.selected_expiry`` as chain index (0/1) for rolling option data; map to a
        calendar expiry for symbol strings and instrument store. NSE paths already store a date.
        """
        e = ctx.selected_expiry
        if e is None:
            return None
        if isinstance(e, int):
            td = pd.Timestamp(ctx.timestamp).date()
            return ExpiryResolver.dhan_expiry_index_to_date(td, e)
        return e

    # Option chain / strikes: inherited from ``IndiaMktMixins.fetch_option_chain``
    # (ExpiryResolver + OTM strikes for ``api`` / ``expiryType``).

    @staticmethod
    def _direction_from_candle(candle: dict) -> str:
        """9:15–9:30 bar: green → short PE, red → short CE."""
        o = float(candle.get("open", candle.get("close", 0)) or 0)
        c = float(candle["close"])
        return "SHORT_PE" if c > o else "SHORT_CE"

    @staticmethod
    def _direction_from_spot_vs_anchor(spot: float, anchor: float) -> str:
        """Above anchor → short PE; below or equal → short CE."""
        if spot > anchor:
            return "SHORT_PE"
        return "SHORT_CE"

    def _strategy_meta(self, meta: _NimlMeta) -> dict:
        return {
            "nifty_intraday_magical_line": {
                "symbol": meta.symbol,
                "entry_date": meta.entry_date.isoformat(),
                "magicalLine": meta.magical_line,
                "entry_premium": meta.entry_premium,
                "entry_spot": meta.entry_spot,
                "entry_green": meta.entry_green,
                "direction": meta.direction,
                "level": meta.level,
            }
        }

    def _build_structure_id(self, symbol: str, trade_dt: date, level: int) -> str:
        return f"{self.name}:{symbol}:{trade_dt}:L{level}:{uuid.uuid4().hex[:8]}"

    def _ist_time(self, candle: dict) -> time:
        ts = pd.Timestamp(candle["timestamp"])
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts.tz_convert(IST).time().replace(second=0, microsecond=0)

    def _is_entry_candle(self, candle: dict) -> bool:
        return self._ist_time(candle) == ENTRY_CANDLE_TIME

    def _is_sl_monitor_candle(self, candle: dict) -> bool:
        t = self._ist_time(candle)
        if t >= EOD_EXIT_TIME:
            return True
        # Match 1h candle closes at :15 (10:15, 11:15, …, 15:15). Excludes 9:15 (hour < 10).
        return (
            t.minute == 15
            and HOURLY_MONITOR_HOUR_START <= t.hour <= HOURLY_MONITOR_HOUR_END
        )

    def _emit_entry(
        self,
        candle: dict,
        ctx: Any,
        *,
        trade_dt: date,
        level: int,
    ) -> Optional[List[Any]]:
        symbol = candle["symbol"]

        spot = float(candle["close"])
        direction = self._direction_from_candle(candle)
        option_type = "PE" if direction == "SHORT_PE" else "CE"
        ml = spot
        o = float(candle.get("open", spot) or 0)
        entry_green = spot > o

        structure_id = self._build_structure_id(symbol, trade_dt, level)

        if ctx.position_store.has_open_structure(
            strategy=self.name, structure_id=structure_id, tag="MAIN"
        ):
            return None

        result = self.find_strike_in_premium_range(
            candle,
            ctx,
            option_type,
            delta_min=DELTA_ABS_MIN,
            delta_max=DELTA_ABS_MAX,
        )

        if result is None:
            return None

        strike, premium, row = result
        try:
            strike = int(float(strike))
        except (TypeError, ValueError):
            return None
        if strike % STRIKE_STEP != 0:
            return None
        expiry = self._calendar_expiry_for_symbol(ctx)
        if expiry is None:
            return None
        trading_symbol = ExpiryResolver.build_option_symbol(
            self, candle["symbol"], expiry, strike, option_type
        )
        inst = ctx.instrument_store.intent_creation_details(
            trading_symbol, ctx.exchange, expiry, option_type, strike
        )
        if inst is None:
            return None

        meta = _NimlMeta(
            symbol=symbol,
            entry_date=trade_dt,
            magical_line=ml,
            entry_premium=float(premium),
            entry_spot=spot,
            entry_green=entry_green,
            direction=direction,
            level=level,
        )
        intent = self.map_instrument_to_intent(
            inst=inst,
            strike_row=row,
            strategy=self.name,
            side="SELL",
            structure_id=structure_id,
            candle_ts=candle["timestamp"],
            tag="MAIN",
            symbol=symbol,
            action="ENTRY",
            metadata_extras=self._strategy_meta(meta),
        )
        self._meta_by_structure_id[structure_id] = meta
        self._exit_reason_by_structure_id.pop(structure_id, None)
        return [intent]

    def on_candle(self, candle: dict, ctx: Any):
        symbol = candle["symbol"]
        trade_dt = pd.to_datetime(candle["timestamp"]).date()
        ct = pd.Timestamp(candle["timestamp"])
        
        # Stale re-entry wait from prior day
        for sym in list(self._reentry_wait.keys()):
            w = self._reentry_wait[sym]
            if w.trade_dt != trade_dt:
                self._reentry_wait.pop(sym, None)

        if getattr(ctx, "intent_store", None) and self._has_pending_main_intent(
            ctx, symbol
        ):
            return None

        # Re-entry path (after SL + 1h + conditions)
        wait = self._reentry_wait.get(symbol)
        if wait is not None and ct >= wait.after_ts:
            o = float(candle.get("open", candle.get("close", 0)) or 0)
            c = float(candle["close"])
            is_green = c > o
            if is_green == wait.entry_green:
                spot = float(candle["close"])
                if (
                    abs(spot - wait.anchor_spot) / max(wait.anchor_spot, 1e-9)
                    <= ANCHOR_SPOT_TOLERANCE
                ):
                    intents = self._emit_entry(
                        candle, ctx, trade_dt=wait.trade_dt, level=wait.next_level
                    )
                    if intents:
                        self._reentry_wait.pop(symbol, None)
                        return intents

        if not self._is_entry_candle(candle):
            return None

        open_positions = ctx.position_store.get_open_positions(
            underlying=symbol, strategy=self.name
        )
        main_open = [
            p
            for p in open_positions
            if getattr(p, "tag", None) == "MAIN" and getattr(p, "net_qty", 0) != 0
        ]
        if main_open:
            return None

        return self._emit_entry(candle, ctx, trade_dt=trade_dt, level=1)

    def _is_eod(self, candle: dict) -> bool:
        return self._ist_time(candle) >= EOD_EXIT_TIME

    def _resolved_option_type_ce_pe(self, inst: Any) -> str:
        ot = (getattr(inst, "option_type", None) or "").upper()
        if ot in ("PUT", "PE"):
            return "PE"
        if ot in ("CALL", "CE"):
            return "CE"
        return str(ot or "")

    def _is_reversal_cross(
        self, position: Any, candle: dict, magical_line: float
    ) -> bool:
        """True when current short leg does not match spot vs stored ML (spot > ML → target PE)."""
        spot = float(candle["close"])
        target_dir = self._direction_from_spot_vs_anchor(spot, magical_line)
        opt_side = self._resolved_option_type_ce_pe(position.instrument)
        current_dir = "SHORT_PE" if opt_side == "PE" else "SHORT_CE"
        return target_dir != current_dir

    def _get_exit_reason(
        self, position: Any, candle: dict, ctx: Any, meta: _NimlMeta
    ) -> Optional[str]:
        if not self._is_sl_monitor_candle(candle):
            return None
        if self._is_eod(candle):
            return "EOD"
        # SL is handled by SimulatedBroker resting MAIN_SL (backtest/paper); avoid double exit.
        if self._is_reversal_cross(position, candle, meta.magical_line):
            return "REVERSAL"
        return None

    def should_exit(self, position: Any, candle: dict, ctx: Any = None) -> bool:
        if position.tag != "MAIN":
            return False
        sid = position.structure_id
        if sid in self._pending_exit_structure_ids:
            return False

        meta = self._meta_by_structure_id.get(sid)
        if meta is None:
            return False

        reason = self._get_exit_reason(position, candle, ctx, meta)
        if reason:
            self._exit_reason_by_structure_id[sid] = reason
            return True
        return False

    def _has_pending_main_intent(self, ctx: Any, symbol: str) -> bool:
        intent_store = getattr(ctx, "intent_store", None)
        if intent_store is None:
            return False
        terminal_statuses = {"FILLED", "CANCELLED", "REJECTED", "EXPIRED"}
        intents = getattr(intent_store, "intents", {}) or {}
        for rec in intents.values():
            status = rec.get("status")
            status_value = getattr(status, "value", status)
            if str(status_value) in terminal_statuses:
                continue
            payload = rec.get("payload") or {}
            if payload.get("strategy_id") != self.name:
                continue
            rec_underlyings = set()
            strategy_meta = payload.get("strategy_meta") or {}
            niml_meta = None
            if isinstance(strategy_meta, dict):
                niml_meta = strategy_meta.get("nifty_intraday_magical_line")
            if isinstance(niml_meta, dict) and niml_meta.get("symbol"):
                rec_underlyings.add(str(niml_meta.get("symbol")))
            structure_id = str(
                payload.get("structure_id") or rec.get("structure_id") or ""
            )
            parts = structure_id.split(":")
            if len(parts) >= 3 and parts[0] == self.name:
                rec_underlyings.add(parts[1])
            if rec_underlyings:
                if symbol not in rec_underlyings:
                    continue
            elif payload.get("symbol") != symbol:
                continue
            tag = str(payload.get("tag") or rec.get("tag") or "").upper()
            action = str(payload.get("action") or rec.get("action") or "").upper()
            if tag == "MAIN_SL":
                continue
            if tag in {"MAIN", "MAIN_EXIT"} or action in {"ENTRY", "EXIT"}:
                return True
        return False

    def _build_main_sl_intent(
        self,
        entry_ref: Any,
        trigger_price: float,
        candle_ts: Any,
        symbol: str,
    ) -> Any:
        return self.create_order_intent(
            inst=entry_ref.instrument,
            side="BUY",
            qty=entry_ref.qty,
            price=float(trigger_price),
            order_type="SL-M",
            strategy=self.name,
            candle_ts=candle_ts,
            structure_id=entry_ref.structure_id,
            tag="MAIN_SL",
            symbol=symbol,
            action="FORCE_EXIT",
            parent_intent_id=entry_ref.intent_id,
            trigger_price=float(trigger_price),
        )

    def on_main_entry_filled(
        self,
        *,
        ctx: Any,
        instrument: Any,
        structure_id: Optional[str],
        intent_id: Optional[str],
        candle_ts: Any,
        metadata_extras: Any = None,
        **_: Any,
    ) -> List[Any]:
        """After MAIN entry fill, arm broker SL (resting stop in SimulatedBroker)."""
        del ctx, metadata_extras
        if not structure_id or not intent_id:
            return []
        meta = self._meta_by_structure_id.get(structure_id)
        if meta is None:
            return []
        sl_trigger = float(meta.entry_premium * (1.0 + SL_PCT))
        ref = SimpleNamespace(
            instrument=instrument,
            structure_id=structure_id,
            intent_id=intent_id,
            qty=int(getattr(instrument, "lot_size", 0) or 0),
        )
        return [self._build_main_sl_intent(ref, sl_trigger, candle_ts, meta.symbol)]

    def on_main_exit_filled(self, **kwargs: Any) -> List[Tuple[Any, dict]]:
        structure_id = kwargs.get("structure_id")
        if not structure_id:
            return []
        pending = self._pending_reversal_by_exit_structure_id.pop(
            str(structure_id), None
        )
        if pending is None:
            return []
        return [(pending.entry_intent, pending.candle)]

    def on_position_exit(self, position: Any, candle: dict, ctx: Any):
        structure_id = position.structure_id
        if getattr(ctx, "intent_store", None) and ctx.intent_store.has_pending_intent(
            strategy=self.name,
            structure_id=structure_id,
            tags=["MAIN_EXIT"],
            actions=["EXIT"],
        ):
            return []

        self._pending_exit_structure_ids.add(structure_id)

        price = self.get_option_price_at_candle(
            candle,
            ctx,
            position.instrument.strike,
            position.instrument.option_type,
            position.instrument.expiry,
            trading_symbol=position.instrument.trading_symbol,
        )
        if RUN_MODE == RunMode.BACKTEST and price is None:
            price = float(candle.get("close", 0) or 0)

        exit_intent = self.create_order_intent(
            inst=position.instrument,
            side="BUY" if position.net_qty < 0 else "SELL",
            qty=abs(position.net_qty),
            price=price,
            order_type="LIMIT",
            strategy=self.name,
            candle_ts=candle["timestamp"],
            structure_id=structure_id,
            tag="MAIN_EXIT",
            symbol=candle["symbol"],
            action="EXIT",
        )

        meta = self._meta_by_structure_id.get(structure_id)
        reason = self._exit_reason_by_structure_id.get(structure_id)

        if reason != "REVERSAL" or meta is None:
            return [exit_intent]

        opt_side = self._resolved_option_type_ce_pe(position.instrument)
        if opt_side not in ("PE", "CE"):
            return [exit_intent]

        reverse_option_type = "CE" if opt_side == "PE" else "PE"
        reverse_direction = (
            "SHORT_CE" if reverse_option_type == "CE" else "SHORT_PE"
        )

        next_level = meta.level + 1

        structure_id_new = self._build_structure_id(
            meta.symbol, meta.entry_date, next_level
        )

        if ctx.position_store.has_open_structure(
            strategy=self.name, structure_id=structure_id_new, tag="MAIN"
        ):
            return [exit_intent]
        if getattr(ctx, "intent_store", None) and ctx.intent_store.has_pending_intent(
            strategy=self.name,
            structure_id=structure_id_new,
            tags=["MAIN"],
            actions=["ENTRY"],
        ):
            return [exit_intent]

        result = self.find_strike_in_premium_range(
            candle,
            ctx,
            reverse_option_type,
            delta_min=DELTA_ABS_MIN,
            delta_max=DELTA_ABS_MAX,
        )
        if not result:
            return [exit_intent]
        strike, premium, row = result
        try:
            strike = int(float(strike))
        except (TypeError, ValueError):
            return [exit_intent]
        if strike % STRIKE_STEP != 0:
            return [exit_intent]

        spot = float(candle["close"])
        expiry = self._calendar_expiry_for_symbol(ctx)
        if expiry is None:
            return [exit_intent]
        trading_symbol = ExpiryResolver.build_option_symbol(
            self, meta.symbol, expiry, strike, reverse_option_type
        )
        inst = ctx.instrument_store.intent_creation_details(
            trading_symbol, ctx.exchange, expiry, reverse_option_type, strike
        )
        if inst is None:
            return [exit_intent]

        o = float(candle.get("open", spot) or 0)
        entry_green = spot > o

        new_meta = _NimlMeta(
            symbol=meta.symbol,
            entry_date=meta.entry_date,
            magical_line=meta.magical_line,
            entry_premium=float(premium),
            entry_spot=spot,
            entry_green=entry_green,
            direction=reverse_direction,
            level=next_level,
        )
        entry_intent = self.map_instrument_to_intent(
            inst=inst,
            strike_row=row,
            strategy=self.name,
            side="SELL",
            structure_id=structure_id_new,
            candle_ts=candle["timestamp"],
            tag="MAIN",
            symbol=meta.symbol,
            action="ENTRY",
            metadata_extras=self._strategy_meta(new_meta),
        )
        self._meta_by_structure_id[structure_id_new] = new_meta
        self._exit_reason_by_structure_id.pop(structure_id_new, None)

        self._pending_reversal_by_exit_structure_id[structure_id] = _PendingReversal(
            entry_intent=entry_intent,
            candle={
                "symbol": meta.symbol,
                "timestamp": candle["timestamp"],
                "close": spot,
                "open": candle.get("open"),
                "exchange": candle.get("exchange"),
            },
        )

        return [exit_intent]

    def on_forced_exit(self, **kwargs: Any) -> None:
        structure_id = kwargs.get("structure_id")
        if not structure_id:
            return
        self._pending_reversal_by_exit_structure_id.pop(str(structure_id), None)
        position_closed = bool(kwargs.get("position_closed"))
        reason = str(
            kwargs.get("exit_reason") or kwargs.get("execution_source") or "FORCED"
        )
        if position_closed:
            self.on_structure_exit(structure_id=structure_id)
        else:
            self._exit_reason_by_structure_id[str(structure_id)] = reason
            self._pending_exit_structure_ids.discard(str(structure_id))

    def on_structure_exit(self, structure_id: str, **kwargs):
        reason = self._exit_reason_by_structure_id.pop(structure_id, None) or kwargs.get(
            "exit_reason"
        )
        meta = self._meta_by_structure_id.get(structure_id)

        if reason == "SL" and meta is not None:
            ct = kwargs.get("candle_ts")
            if ct is not None:
                after = pd.Timestamp(ct) + pd.Timedelta(hours=1)
                self._reentry_wait[meta.symbol] = _ReentryWait(
                    after_ts=after,
                    entry_green=meta.entry_green,
                    anchor_spot=meta.entry_spot,
                    trade_dt=meta.entry_date,
                    next_level=meta.level + 1,
                )

        self._meta_by_structure_id.pop(structure_id, None)
        self._pending_exit_structure_ids.discard(structure_id)
        super().on_structure_exit(structure_id=structure_id, **kwargs)
