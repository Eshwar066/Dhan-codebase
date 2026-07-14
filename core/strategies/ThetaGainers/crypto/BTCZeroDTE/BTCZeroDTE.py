"""
BTC Zero-DTE short strangle (Delta).

Rules
- 09:00 IST: sell 1 OTM Call + 1 OTM Put near ~$100 premium (same-day expiry).
- Hold through the day; after each MAIN fill place 100% premium stop (SL-M BUY cover).
- One re-entry per leg at the same premium band after SL.
- Manage remaining leg independently.
- 17:15 IST: exit all remaining MAIN positions.

Eval style: scheduled slots (like BankNiftyBTST). ``backtest_timeframe="5"`` so
backtest bar closes at :00/:05 can hit 10:00 and 17:15 IST.

Run: ``python -m run.main --engine-id delta_engine_one``
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, time
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from run.config import RUN_MODE, RunMode
from core.strategies.base import BaseStrategy
from core.strategies.IndiaMktMixins import IST, IndiaMktMixins
from core.strategies.deltaMktMixins import DeltaMktMixins
from core.strategies.meta import pack_strategy_meta

logger = logging.getLogger(__name__)

ENTRY_TIME = time(10, 10)
EXIT_TIME = time(17, 15)

# Discrete BTC 0DTE strikes (~$200 spacing) often skip an exact $60–$100 print.
# Keep a band around ~$100 so CE+PE both resolve; live scorer targets band midpoint.
PREM_MIN = 50.0
PREM_MAX = 110.0
IDEAL_PREM = 100.0
# Premium-band strategy: do not inherit MagicalLine-style delta gates (0.15–0.35).
DELTA_MIN = 0.0
DELTA_MAX = 1.0
SL_PREM_MULT = 2.0  # 100% stop on short premium
MAX_REENTRIES_PER_LEG = 1

META_KEY = "btc_zero_dte"
REGISTRY_KEY = "BTCZeroDTE"


@dataclass(frozen=True)
class _LegMeta:
    symbol: str
    entry_date: date
    option_type: str
    entry_premium: float
    reentry_count: int


class BTCZeroDTE(IndiaMktMixins, DeltaMktMixins, BaseStrategy):
    """Delta BTC 0DTE OTM short strangle with 100% SL and one re-entry per leg."""

    name = "BTCZeroDTE"
    underlying_symbols = ["BTCUSD"]
    bracket_leg_tags = ["MAIN_SL"]
    timeframe = None
    backtest_timeframe = "5"
    scheduled_times = [ENTRY_TIME, EXIT_TIME]
    required_context = ["option_chain"]
    api = "DELTA"
    expiryType = "Daily"
    otm_strike_step = 200
    otm_strike_count = 12
    option_chain_ideal_premium = IDEAL_PREM

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._meta_by_structure_id: Dict[str, _LegMeta] = {}
        self._evaluated_signal_keys: set[str] = set()
        self._entry_signaled_keys: set[str] = set()
        self._pending_exit_structure_ids: set[str] = set()
        self._snapshot_logged_slots: set[str] = set()

    def get_warmup_period(self):
        return 0

    # ---------- time / slots ----------

    def _bar_minutes(self) -> int:
        tf = getattr(self, "timeframe", None) or getattr(self, "backtest_timeframe", "5")
        return int(tf) if str(tf).isdigit() else 5

    def _scheduled_slot_from_candle(self, candle: dict) -> Optional[time]:
        slot = candle.get("scheduled_slot")
        if isinstance(slot, time):
            return slot.replace(second=0, microsecond=0)
        return None

    def _bar_close_time(self, candle: dict) -> time:
        ts = pd.Timestamp(candle["timestamp"])
        if ts.tzinfo is None:
            ts = ts.tz_localize(IST)
        else:
            ts = ts.tz_convert(IST)
        close_ts = ts + pd.Timedelta(minutes=self._bar_minutes())
        return close_ts.time().replace(second=0, microsecond=0)

    def _active_slot(self, candle: dict) -> Optional[time]:
        slot = self._scheduled_slot_from_candle(candle)
        if slot is not None:
            return slot
        return self._bar_close_time(candle)

    def _trade_date(self, candle: dict) -> date:
        slot = self._scheduled_slot_from_candle(candle)
        ts = pd.Timestamp(candle["timestamp"])
        if ts.tzinfo is None:
            if slot is not None:
                ts = ts.tz_localize("UTC").tz_convert(IST)
            else:
                ts = ts.tz_localize(IST)
        else:
            ts = ts.tz_convert(IST)
        return ts.date()

    def _slot_key(self, candle: dict) -> str:
        slot = self._scheduled_slot_from_candle(candle)
        if slot is not None:
            return f"{self._trade_date(candle)}|{slot.strftime('%H:%M')}"
        ts = pd.Timestamp(candle.get("timestamp"))
        if ts.tzinfo is None:
            ts = ts.tz_localize(IST)
        else:
            ts = ts.tz_convert(IST)
        return ts.strftime("%Y-%m-%d %H:%M")

    def _evaluate_signal_key(self, candle: dict) -> str:
        symbol = str(candle.get("symbol") or "").strip().upper()
        return f"{symbol}|{self._slot_key(candle)}"

    # ---------- meta ----------

    def _structure_id(
        self, symbol: str, trade_dt: date, option_type: str, *, reentry: int = 0
    ) -> str:
        leg = str(option_type).upper()
        if leg in ("CALL", "CE"):
            leg = "CE"
        elif leg in ("PUT", "PE"):
            leg = "PE"
        if reentry > 0:
            return f"{self.name}:{symbol}:{trade_dt}:{leg}:R{reentry}"
        return f"{self.name}:{symbol}:{trade_dt}:{leg}"

    def _strategy_meta_dict(self, meta: _LegMeta) -> dict:
        payload = {
            "symbol": meta.symbol,
            "entry_date": meta.entry_date.isoformat(),
            "option_type": meta.option_type,
            "entry_premium": meta.entry_premium,
            "reentry_count": meta.reentry_count,
        }
        out = pack_strategy_meta(REGISTRY_KEY, payload)
        out[META_KEY] = payload
        return out

    def _try_merge_meta_from_raw(self, structure_id: str, raw: dict) -> bool:
        if structure_id in self._meta_by_structure_id:
            return True
        try:
            meta = _LegMeta(
                symbol=str(raw["symbol"]),
                entry_date=date.fromisoformat(str(raw["entry_date"])),
                option_type=str(raw["option_type"]),
                entry_premium=float(raw["entry_premium"]),
                reentry_count=int(raw.get("reentry_count", 0) or 0),
            )
        except (KeyError, TypeError, ValueError):
            return False
        self._meta_by_structure_id[structure_id] = meta
        return True

    def _ensure_meta_for_fill(
        self,
        structure_id: str,
        instrument: Any,
        ctx: Any,
        intent_id: Optional[str],
        metadata_extras: Any,
    ) -> None:
        sid = str(structure_id)
        if sid in self._meta_by_structure_id:
            return
        if isinstance(metadata_extras, dict):
            raw = metadata_extras.get(META_KEY)
            if isinstance(raw, dict) and self._try_merge_meta_from_raw(sid, raw):
                return
            sm = metadata_extras.get("strategy_meta")
            if isinstance(sm, dict) and self._try_merge_meta_from_raw(sid, sm):
                return
        ps = getattr(ctx, "position_store", None) if ctx is not None else None
        sym = getattr(instrument, "trading_symbol", None) if instrument else None
        if ps is not None and sym and callable(getattr(ps, "get_position_metadata", None)):
            bucket = ps.get_position_metadata(sym) or {}
            sm = bucket.get("strategy_meta") or {}
            if isinstance(sm, dict):
                legacy = sm.get(META_KEY) if isinstance(sm.get(META_KEY), dict) else sm
                if isinstance(legacy, dict) and self._try_merge_meta_from_raw(sid, legacy):
                    return
        ist = getattr(ctx, "intent_store", None) if ctx is not None else None
        if ist is not None and intent_id and callable(getattr(ist, "get", None)):
            rec = ist.get(intent_id)
            if rec:
                payload = rec.get("payload") or {}
                sm = payload.get("strategy_meta") or payload.get(META_KEY)
                if isinstance(sm, dict):
                    body = sm.get(META_KEY) if isinstance(sm.get(META_KEY), dict) else sm
                    if isinstance(body, dict):
                        self._try_merge_meta_from_raw(sid, body)

    # ---------- strike ----------

    def _find_strike_snapshot_params(self, candle, ctx, option_type):
        trade_dt = self._trade_date(candle)
        slot = self._active_slot(candle)
        slot_s = slot.strftime("%H-%M") if slot else "na"
        key = f"{getattr(ctx, 'symbol', '')}|{trade_dt}|{slot_s}|{option_type}"
        if key in self._snapshot_logged_slots:
            return {}
        self._snapshot_logged_slots.add(key)
        return {
            "snapshot": True,
            "snapshot_date": trade_dt.isoformat(),
            "snapshot_time": slot_s,
            "snapshot_target": "btc_zero_dte",
        }

    def find_strike_in_premium_range(
        self,
        candle,
        ctx,
        option_type,
        min_prem=PREM_MIN,
        max_prem=PREM_MAX,
        lookback_sec=60,
    ):
        # Prefer premium band (not Delta prod delta-only path).
        if RUN_MODE == RunMode.BACKTEST:
            return DeltaMktMixins.find_strike_in_premium_range(
                self,
                candle,
                ctx,
                option_type,
                min_prem=min_prem,
                max_prem=max_prem,
                lookback_sec=lookback_sec,
                expiry="Daily",
            )
        return DeltaMktMixins.find_strike_in_premium_range_live(
            self,
            candle,
            ctx,
            option_type,
            min_prem=min_prem,
            max_prem=max_prem,
            lookback_sec=lookback_sec,
            expiry="Daily",
            side="SELL",
            delta_min=DELTA_MIN,
            delta_max=DELTA_MAX,
        )

    def _normalize_order_qty(self, instrument: Any, fill_qty: Any) -> int:
        lot = int(getattr(instrument, "lot_size", None) or 1) or 1
        if fill_qty is None:
            return lot
        try:
            q = int(round(float(fill_qty)))
        except (TypeError, ValueError):
            return lot
        return q if q > 0 else lot

    # ---------- entry / exit helpers ----------

    def _build_leg_entry(
        self,
        candle: dict,
        ctx,
        option_type: str,
        trade_dt: date,
        *,
        reentry_count: int = 0,
    ) -> Optional[Any]:
        symbol = str(candle.get("symbol") or "BTCUSD")
        structure_id = self._structure_id(
            symbol, trade_dt, option_type, reentry=reentry_count
        )
        guard = f"{structure_id}|{self._slot_key(candle)}"
        if guard in self._entry_signaled_keys:
            return None
        if ctx.position_store.has_open_structure(
            strategy=self.name, structure_id=structure_id, tag="MAIN"
        ):
            return None
        ist = getattr(ctx, "intent_store", None)
        if ist is not None and ist.has_pending_intent(
            strategy=self.name,
            structure_id=structure_id,
            actions=["ENTRY"],
        ):
            return None

        # Day-level: skip if any MAIN for this CE/PE already open today.
        if reentry_count == 0:
            leg = str(option_type).upper()
            if leg in ("CALL", "CE"):
                leg = "CE"
            elif leg in ("PUT", "PE"):
                leg = "PE"
            day_prefix = f"{self.name}:{symbol}:{trade_dt}:{leg}"
            for pos in ctx.position_store.get_open_positions(strategy=self.name) or []:
                sid = str(getattr(pos, "structure_id", "") or "")
                if sid.startswith(day_prefix) and getattr(pos, "tag", None) == "MAIN":
                    return None

        result = self.find_strike_in_premium_range(
            candle, ctx, option_type, min_prem=PREM_MIN, max_prem=PREM_MAX
        )
        if result is None:
            logger.warning(
                "BTCZeroDTE: no OTM strike opt=%s prem=%s-%s date=%s reentry=%s",
                option_type,
                PREM_MIN,
                PREM_MAX,
                trade_dt,
                reentry_count,
            )
            return None
        strike, premium, row = result
        if not strike:
            return None
        try:
            prem = float(premium)
        except (TypeError, ValueError):
            return None
        if prem > PREM_MAX or prem <= 0:
            logger.info(
                "BTCZeroDTE: reject premium=%.2f outside <=%s opt=%s",
                prem,
                PREM_MAX,
                option_type,
            )
            return None

        expiry = getattr(ctx, "selected_expiry", None) or self.dailyExpiry(candle, ctx)
        trading_symbol = self.delta_option_trading_symbol(
            row, float(strike), option_type, str(expiry)
        )
        inst = ctx.instrument_store.intent_creation_details(
            trading_symbol, ctx.exchange, expiry, option_type, strike
        )
        if inst is None:
            logger.warning(
                "BTCZeroDTE: instrument missing %s", trading_symbol
            )
            return None

        meta = _LegMeta(
            symbol=symbol,
            entry_date=trade_dt,
            option_type=str(option_type).upper(),
            entry_premium=prem,
            reentry_count=int(reentry_count),
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
            metadata_extras=self._strategy_meta_dict(meta),
        )
        self._meta_by_structure_id[structure_id] = meta
        self._entry_signaled_keys.add(guard)
        logger.info(
            "BTCZeroDTE entry %s strike=%s prem=%s expiry=%s reentry=%s",
            structure_id,
            strike,
            prem,
            expiry,
            reentry_count,
        )
        return intent

    def _build_main_sl_intent(
        self,
        entry_ref: Any,
        trigger_price: float,
        candle_ts: Any,
        symbol: str,
    ) -> Any:
        trig = float(trigger_price)
        return self.create_order_intent(
            inst=entry_ref.instrument,
            side="BUY",
            qty=entry_ref.qty,
            price=trig,
            order_type="SL-M",
            strategy=self.name,
            candle_ts=candle_ts,
            structure_id=entry_ref.structure_id,
            tag="MAIN_SL",
            symbol=symbol,
            action="FORCE_EXIT",
            parent_intent_id=entry_ref.intent_id,
            trigger_price=trig,
        )

    def _exit_intent_for_position(self, position: Any, candle: dict, ctx: Any) -> Any:
        price = None
        if RUN_MODE == RunMode.BACKTEST:
            price = self.get_option_price_at_candle(
                candle,
                ctx,
                position.instrument.strike,
                position.instrument.option_type,
                position.instrument.expiry,
                trading_symbol=position.instrument.trading_symbol,
            )
        qty = abs(int(position.net_qty or 0)) or 1
        return self.create_order_intent(
            inst=position.instrument,
            side="BUY" if position.net_qty < 0 else "SELL",
            qty=qty,
            price=price,
            order_type="LIMIT",
            strategy=self.name,
            candle_ts=candle["timestamp"],
            structure_id=position.structure_id,
            tag="MAIN_EXIT",
            symbol=candle.get("symbol") or getattr(position, "symbol", ""),
            action="EXIT",
        )

    def _eod_exit_intents(self, candle: dict, ctx) -> List[Any]:
        intents: List[Any] = []
        for pos in ctx.position_store.get_open_positions(strategy=self.name) or []:
            if getattr(pos, "tag", None) != "MAIN" or not getattr(pos, "net_qty", 0):
                continue
            sid = str(pos.structure_id or "")
            if sid in self._pending_exit_structure_ids:
                continue
            ist = getattr(ctx, "intent_store", None)
            if ist is not None and ist.has_pending_intent(
                strategy=self.name,
                structure_id=sid,
                tags=["MAIN_EXIT"],
                actions=["EXIT"],
            ):
                continue
            self._pending_exit_structure_ids.add(sid)
            intents.append(self._exit_intent_for_position(pos, candle, ctx))
        return intents

    def _try_reentry_after_sl(
        self, ctx: Any, meta: _LegMeta, candle_stub: dict
    ) -> List[Tuple[Any, dict]]:
        if meta.reentry_count >= MAX_REENTRIES_PER_LEG:
            return []
        if ctx is None:
            return []
        candle = dict(candle_stub)
        if not candle.get("symbol"):
            candle["symbol"] = meta.symbol
        if float(candle.get("close") or 0) <= 0:
            # Need spot for OTM filter; leave as-is and let strike finder fail soft.
            pass
        opt = meta.option_type
        if opt.upper() in ("CALL", "C"):
            opt = "CE"
        elif opt.upper() in ("PUT", "P"):
            opt = "PE"
        intent = self._build_leg_entry(
            candle,
            ctx,
            opt,
            meta.entry_date,
            reentry_count=meta.reentry_count + 1,
        )
        if intent is None:
            return []
        return [(intent, candle)]

    # ---------- engine hooks ----------

    def should_evaluate(self, candle) -> bool:
        slot = self._active_slot(candle)
        if slot not in (ENTRY_TIME, EXIT_TIME):
            return False
        prefix = "entry" if slot == ENTRY_TIME else "exit"
        key = f"{prefix}|{self._evaluate_signal_key(candle)}"
        if key in self._evaluated_signal_keys:
            return False
        self._evaluated_signal_keys.add(key)
        return True

    def on_candle(self, candle, ctx):
        slot = self._active_slot(candle)
        if slot == EXIT_TIME:
            intents = self._eod_exit_intents(candle, ctx)
            return intents or None
        if slot != ENTRY_TIME:
            return None

        trade_dt = self._trade_date(candle)
        intents: List[Any] = []
        for opt in ("CE", "PE"):
            leg = self._build_leg_entry(candle, ctx, opt, trade_dt, reentry_count=0)
            if leg is not None:
                intents.append(leg)
        return intents or None

    def should_exit(self, position, candle, ctx=None):
        if getattr(position, "tag", None) != "MAIN":
            return False
        if self._active_slot(candle) == EXIT_TIME:
            return True
        # Soft 100% SL (backtest / if broker SL not armed yet).
        sid = str(getattr(position, "structure_id", "") or "")
        if ctx is not None and sid:
            self._ensure_meta_for_fill(
                sid,
                position.instrument,
                ctx,
                getattr(position, "intent_id", None),
                None,
            )
        meta = self._meta_by_structure_id.get(sid)
        if meta is None or ctx is None:
            return False
        px = self.get_option_price_at_candle(
            candle,
            ctx,
            position.instrument.strike,
            position.instrument.option_type,
            position.instrument.expiry,
            trading_symbol=position.instrument.trading_symbol,
        )
        if px is None or px <= 0:
            return False
        return float(px) >= float(meta.entry_premium) * SL_PREM_MULT

    def on_position_exit(self, position, candle, ctx):
        sid = str(position.structure_id or "")
        if sid in self._pending_exit_structure_ids:
            return []
        ist = getattr(ctx, "intent_store", None)
        if ist is not None and ist.has_pending_intent(
            strategy=self.name,
            structure_id=sid,
            tags=["MAIN_EXIT", "MAIN_SL"],
            actions=["EXIT", "FORCE_EXIT"],
        ):
            return []
        self._pending_exit_structure_ids.add(sid)
        return [self._exit_intent_for_position(position, candle, ctx)]

    def on_main_entry_filled(
        self,
        *,
        ctx: Any,
        instrument: Any,
        structure_id: Optional[str],
        intent_id: Optional[str],
        candle_ts: Any,
        metadata_extras: Any = None,
        **kwargs: Any,
    ) -> List[Any]:
        if not structure_id or not intent_id:
            return []
        sid = str(structure_id)
        self._ensure_meta_for_fill(sid, instrument, ctx, intent_id, metadata_extras)
        meta = self._meta_by_structure_id.get(sid)
        if meta is None:
            logger.warning("BTCZeroDTE: MAIN fill without meta; SL skipped sid=%s", sid)
            return []
        sl_trigger = float(meta.entry_premium) * SL_PREM_MULT
        ref = SimpleNamespace(
            instrument=instrument,
            structure_id=sid,
            intent_id=intent_id,
            qty=self._normalize_order_qty(instrument, kwargs.get("qty")),
        )
        return [self._build_main_sl_intent(ref, sl_trigger, candle_ts, meta.symbol)]

    def on_main_exit_filled(self, **kwargs: Any) -> List[Tuple[Any, dict]]:
        structure_id = kwargs.get("structure_id")
        if not structure_id:
            return []
        sid = str(structure_id)
        self._pending_exit_structure_ids.discard(sid)
        meta = self._meta_by_structure_id.get(sid)
        reason_u = str(kwargs.get("exit_reason") or "").upper()
        tag_u = str(kwargs.get("tag") or "").upper()
        action_u = str(kwargs.get("action") or "").upper()
        is_sl = (
            tag_u == "MAIN_SL"
            or action_u == "FORCE_EXIT"
            or reason_u in {"SL", "MAIN_SL", "FORCE_EXIT"}
        )
        if meta is None or not is_sl:
            return []
        ctx = kwargs.get("ctx")
        ts = kwargs.get("candle_ts")
        candle_stub = {
            "symbol": meta.symbol,
            "timestamp": ts,
            "close": float(kwargs.get("spot") or 0.0),
            "exchange": None,
        }
        pairs = self._try_reentry_after_sl(ctx, meta, candle_stub)
        if pairs:
            logger.info(
                "BTCZeroDTE SL re-entry queued from %s -> reentry=%s",
                sid,
                meta.reentry_count + 1,
            )
        return pairs

    def on_forced_exit(self, **kwargs: Any):
        structure_id = kwargs.get("structure_id")
        if not structure_id:
            return
        sid = str(structure_id)
        self._pending_exit_structure_ids.discard(sid)
        # Re-entry is driven by ``on_main_exit_filled`` (engine builds ctx).
        # Do not clear meta here when SL — fill hook still needs it.

    def on_structure_exit(self, structure_id: str, **kwargs):
        super().on_structure_exit(structure_id=structure_id, **kwargs)
        self._pending_exit_structure_ids.discard(str(structure_id))
        # Keep meta until after possible SL re-entry has consumed it; clear later tags.
        sid = str(structure_id)
        meta = self._meta_by_structure_id.get(sid)
        if meta is not None and meta.reentry_count >= MAX_REENTRIES_PER_LEG:
            self._meta_by_structure_id.pop(sid, None)
