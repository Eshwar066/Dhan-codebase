"""
BTCUSD One-Day Magical Line (Intraday Option Selling)

Rules (per user spec)
1. On 1hr candles, at `17:30` IST candle close mark spot as `ML1`.
2. At `17:30`, if candle is green (close > open) => short `PE` else short `CE`.
3. If market crosses `ML1`, reverse direction (above line => PE short, below => CE short):
   - Currently short `PE` => reverse to short `CE` when spot crosses **below** ML1
   - Currently short `CE` => reverse to short `PE` when spot crosses **above** ML1
5. From short premium use 15% as SL:
   - If option premium rises by >= 15% from entry premium => exit.

Implementation notes
- Uses `IndiaMktMixins` for option strike/premium selection and option LTP fetching.
- Delta product symbols via `DeltaMktMixins.delta_option_trading_symbol` (see `deltaMktMixins.py`).
- Broker SL (`MAIN_SL`) is placed only after the MAIN sell fills (avoids Delta `no_open_position`).
- On reversal: emit `MAIN_EXIT` first; when that exit fills, emit reversal ENTRY; SL again after the new MAIN fills.
- If broker/forced exit closes a MAIN leg at SL, queue next-candle SL re-entry as well.
- The magical line (spot at entry) is stored per opened position via `structure_id` for reversal + SL.


Pending:
    1. 1 week before the expiry exit the trades.--> to be implemented in the strategy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, time
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import uuid
import pdb
from core.strategies.IndiaMktMixins import IndiaMktMixins
from core.strategies.deltaMktMixins import DeltaMktMixins
from core.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

VALID_TIME_1730 = {time(18, 30)}  # 1hr candle close time (IST)

# Strike/premium selection (kept conservative and similar to `MagicalLines`)
STRIKE_STEP = 500
STRIKE_LOOKBACK = 5  # +/- 15 steps around ATM => 31 strikes
TARGET_PREMIUM_MIN = 700
TARGET_PREMIUM_MAX = 1500
TARGET_DELTA = 0.25
DELTA_RANGE = (0.2, 0.4)

# Risk
SL_PCT = 0.15  # 15% rise in short option premium triggers exit
NEXT_DAY_ML_GAP_PCT = 0.03  # Next-day 17:30 MAIN entry only if spot is outside +/-3% of previous ML
MAX_REVERSALS = 5  # max reversal levels per ML1 day (L1 initial + reversals)
_CANDLE_CACHE_MAX = 1000


@dataclass(frozen=True)
class _PosMeta:
    symbol: str
    entry_date: date
    magical_line: float
    entry_premium: float
    level: int


@dataclass(frozen=True)
class _PendingReversal:
    entry_intent: Any
    candle: dict


@dataclass(frozen=True)
class _PendingSLReentry:
    meta: _PosMeta
    exit_candle_ts: Any


class OneDayMagicalLine(IndiaMktMixins, DeltaMktMixins, BaseStrategy):
    """
    One-Day Magical Line strategy for intraday BTCUSD option selling.
    """

    name = "OneDayMagicalLine"
    timeframe = "60"  # change to 60min later
    required_context = ["option_chain"]
    api = "DELTA"
    expiryType = "Monthly"
    valid_times = VALID_TIME_1730
    delta = TARGET_DELTA
    delta_range = DELTA_RANGE

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._meta_by_structure_id: Dict[str, _PosMeta] = {}
        self._pending_exit_structure_ids: set[str] = set()
        self._reversal_level_counter: Dict[Tuple[str, date], int] = {}
        self._exit_reason_by_structure_id: Dict[str, str] = {}
        # For reversal cross detection in both backtest + live:
        # - `_last_spot_close_by_symbol` is the previous candle close (committed)
        # - `_pending_spot_close_by_symbol` is the current candle close (set in on_candle, committed next candle)
        self._last_spot_close_by_symbol: Dict[str, float] = {}
        self._pending_spot_close_by_symbol: Dict[str, float] = {}
        self._candle_cache: Dict[Any, Any] = {}
        self._pending_reversal_by_exit_structure_id: Dict[str, _PendingReversal] = {}
        self._pending_sl_reentry_by_symbol: Dict[str, _PendingSLReentry] = {}
        # Last daily ML used for 17:30 MAIN entry gating on following days.
        self._last_daily_ml_by_symbol: Dict[str, Tuple[date, float]] = {}

    def get_warmup_period(self):
        return 0

    def _strategy_meta_dict(self, meta: _PosMeta) -> dict:
        return {
            "one_day_magical_line": {
                "symbol": meta.symbol,
                "entry_date": meta.entry_date.isoformat(),
                "magicalLine": meta.magical_line,
                "entry_premium": meta.entry_premium,
                "level": meta.level,
            }
        }

    def _try_merge_odml_meta_from_raw(self, structure_id: str, raw: dict) -> bool:
        """
        Parse persisted ``one_day_magical_line`` payload into ``_meta_by_structure_id``.
        Returns True if ``structure_id`` is present after the call.
        """
        if structure_id in self._meta_by_structure_id:
            return True
        try:
            ml_val = raw.get("magicalLine", raw.get("ml1"))
            if ml_val is None:
                return False
            meta = _PosMeta(
                symbol=str(raw["symbol"]),
                entry_date=date.fromisoformat(str(raw["entry_date"])),
                magical_line=float(ml_val),
                entry_premium=float(raw["entry_premium"]),
                level=int(raw["level"]),
            )
        except (KeyError, TypeError, ValueError):
            return False
        self._meta_by_structure_id[structure_id] = meta
        k = (meta.symbol, meta.entry_date)
        self._reversal_level_counter[k] = max(
            self._reversal_level_counter.get(k, 0), meta.level
        )
        return True

    def _restore_odml_meta_from_position(self, pos: Any, position_store: Any) -> None:
        if not pos or not getattr(pos, "structure_id", None):
            return
        if pos.structure_id in self._meta_by_structure_id:
            return
        sym = pos.instrument.trading_symbol
        bucket = position_store.get_position_metadata(sym)
        if not bucket:
            return
        sm = bucket.get("strategy_meta") or {}
        raw = sm.get("one_day_magical_line") or sm.get("one_day_ml1")
        if not isinstance(raw, dict):
            return
        self._try_merge_odml_meta_from_raw(str(pos.structure_id), raw)

    def _ensure_odml_meta_for_main_fill(
        self,
        structure_id: str,
        instrument: Any,
        ctx: Any,
        intent_id: Optional[str],
        metadata_extras: Any,
    ) -> None:
        """
        Repopulate in-memory ODML meta when the MAIN entry fill runs after restart or
        whenever ``_meta_by_structure_id`` was cleared (``on_main_entry_filled`` needs it for SL).
        """
        if structure_id in self._meta_by_structure_id:
            return
        if isinstance(metadata_extras, dict):
            raw = metadata_extras.get("one_day_magical_line") or metadata_extras.get(
                "one_day_ml1"
            )
            if isinstance(raw, dict):
                self._try_merge_odml_meta_from_raw(structure_id, raw)
        if structure_id in self._meta_by_structure_id:
            return
        ps = getattr(ctx, "position_store", None)
        sym = getattr(instrument, "trading_symbol", None) if instrument else None
        if ps is not None and sym and callable(getattr(ps, "get_position_metadata", None)):
            bucket = ps.get_position_metadata(sym)
            if bucket:
                sm = bucket.get("strategy_meta") or {}
                raw = sm.get("one_day_magical_line") or sm.get("one_day_ml1")
                if isinstance(raw, dict):
                    self._try_merge_odml_meta_from_raw(structure_id, raw)
        if structure_id in self._meta_by_structure_id:
            return
        ist = getattr(ctx, "intent_store", None)
        if ist is not None and intent_id and callable(getattr(ist, "get", None)):
            rec = ist.get(intent_id)
            if rec:
                payload = rec.get("payload") or {}
                sm = payload.get("strategy_meta")
                if isinstance(sm, dict):
                    raw = sm.get("one_day_magical_line") or sm.get("one_day_ml1")
                    if isinstance(raw, dict):
                        self._try_merge_odml_meta_from_raw(structure_id, raw)

    def _build_structure_id(self, symbol: str, trade_dt: date, level: int) -> str:
        return f"{self.name}:{symbol}:ML1:{trade_dt}:L{level}:{uuid.uuid4().hex[:6]}"

    def _get_cached_strike_in_premium_range(
        self,
        candle: dict,
        ctx: Any,
        symbol: str,
        option_type: str,
    ):
        strike_cache_key = (symbol, option_type, candle["timestamp"])
        if strike_cache_key not in self._candle_cache:
            self._candle_cache[strike_cache_key] = self.find_strike_in_premium_range(
                candle,
                ctx,
                option_type,
                min_prem=TARGET_PREMIUM_MIN,
                max_prem=TARGET_PREMIUM_MAX,
            )
        return self._candle_cache[strike_cache_key]

    def _get_cached_option_price(
        self,
        candle: dict,
        ctx: Any,
        position: Any,
    ) -> Optional[float]:
        key = ("opt_px", position.instrument.trading_symbol, candle["timestamp"])
        if key not in self._candle_cache:
            ot = self._resolved_option_type_ce_pe(position.instrument)
            self._candle_cache[key] = self.get_option_price_at_candle(
                candle=candle,
                ctx=ctx,
                strike=position.instrument.strike,
                option_type=ot or position.instrument.option_type,
                expiry=position.instrument.expiry,
                trading_symbol=position.instrument.trading_symbol,
            )
        return self._candle_cache[key]

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
            # Intent payload symbol is usually option tradingsymbol (C-BTC-...),
            # while this method receives underlying symbol (BTCUSD). Match via
            # strategy metadata / structure_id when available.
            rec_underlyings = set()
            strategy_meta = payload.get("strategy_meta") or {}
            odml_meta = None
            if isinstance(strategy_meta, dict):
                odml_meta = strategy_meta.get(
                    "one_day_magical_line"
                ) or strategy_meta.get("one_day_ml1")
            if isinstance(odml_meta, dict) and odml_meta.get("symbol"):
                rec_underlyings.add(str(odml_meta.get("symbol")))
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
                # Backward-compat fallback when metadata/structure are missing.
                continue

            # Any non-final MAIN/MAIN_EXIT signal for this symbol means
            # a position lifecycle is still in flight; avoid opposite entry.
            tag = str(payload.get("tag") or rec.get("tag") or "").upper()
            action = str(payload.get("action") or rec.get("action") or "").upper()
            if tag == "MAIN_SL":
                continue
            if tag in {"MAIN", "MAIN_EXIT"} or action in {"ENTRY", "EXIT"}:
                return True
        return False

    def _build_main_sl_intent(
        self,
        entry_intent: Any,
        trigger_price: float,
        candle_ts: Any,
        symbol: str,
    ) -> Any:
        return self.create_order_intent(
            inst=entry_intent.instrument,
            side="BUY",
            qty=entry_intent.qty,
            price=float(trigger_price),
            order_type="SL-M",  # STOP_LIMIT (to be used here)
            strategy=self.name,
            candle_ts=candle_ts,
            structure_id=entry_intent.structure_id,
            tag="MAIN_SL",
            symbol=symbol,
            action="FORCE_EXIT",
            parent_intent_id=entry_intent.intent_id,
            trigger_price=float(trigger_price),
        )

    def _normalize_order_qty(self, instrument: Any, fill_qty: Any) -> int:
        """Integer qty for SL intent ref; align with fill size and instrument lot_size."""
        lot = int(getattr(instrument, "lot_size", None) or 1) or 1
        if fill_qty is None:
            return lot
        try:
            q = int(round(float(fill_qty)))
        except (TypeError, ValueError):
            return lot
        if q <= 0:
            return lot
        return q

    # Strike selection: backtest = Delta tick CSV; live/paper = products + tickers (``deltaMktMixins``).
    # Branch uses ``run.config.RUN_MODE`` — for live engines set global ``RUN_MODE`` or ensure it matches the job.
    def find_strike_in_premium_range(
        self,
        candle,
        ctx,
        option_type,
        min_prem=600,
        max_prem=1500,
        lookback_sec=60,
    ):
        return self.find_strike_in_premium_range_by_mode(
            candle,
            ctx,
            option_type,
            min_prem=min_prem,
            max_prem=max_prem,
            lookback_sec=lookback_sec,
            expiry=self.expiryType,
            side="SELL",
            target_delta=self.delta,
            delta_min=self.delta_range[0],
            delta_max=self.delta_range[1],
        )

    # ==================================================
    # TIME FILTER
    # ==================================================
    def should_evaluate(self, candle: dict):
        """
        Used by the engine mainly to decide whether to call `on_candle` + `should_exit`.

        For this strategy we need exit checks (reversal + SL) on every 1hr candle
        after entry, so we keep this permissive.
        """
        return True

    def should_enter(self, candle: dict) -> bool:
        """Only enter at `17:30` IST candle close."""
        ts = pd.to_datetime(candle["timestamp"])

        return self._is_valid_time(ts, self.valid_times)
        # return True

    def _direction_at_1730(self, candle: dict) -> str:
        open_ = float(candle.get("open", candle.get("close", 0)) or 0)
        close = float(candle["close"])

        # Green => short PE, else short CE
        return "SHORT_PE" if close > open_ else "SHORT_CE"

    def _option_type_for_direction(self, direction: str) -> str:
        return "PE" if direction == "SHORT_PE" else "CE"

    def _resolved_option_type_ce_pe(self, inst: Any) -> str:
        return self.resolved_option_type_ce_pe(inst)

    # ==================================================
    # Magical-line cross detection (uses stored prev candle close)
    # ==================================================
    def _is_reversal_cross(
        self,
        position: Any,
        candle: dict,
        magical_line: float,
    ) -> bool:
        symbol = candle["symbol"]
        prev_close = self._last_spot_close_by_symbol.get(symbol)
        curr_close = float(candle["close"])
        print(">>prev_close", prev_close, ">>current close", curr_close)
        if prev_close is None:
            return False

        opt_side = self._resolved_option_type_ce_pe(position.instrument)

        # Above line => PE short, below => CE short: reverse when leaving that zone.
        # Short PE (above): reverse to CE when spot crosses below magical line.
        if opt_side == "PE":
            return prev_close >= magical_line and curr_close < magical_line
        # Short CE (below): reverse to PE when spot crosses above magical line.
        if opt_side == "CE":
            return prev_close <= magical_line and curr_close > magical_line
        return False

    # ==================================================
    # STOPLOSS (15% rise in option premium)
    # ==================================================
    def _is_sl_triggered(
        self, position: Any, candle: dict, ctx: Any, meta: _PosMeta
    ) -> bool:
        curr_prem = self._get_cached_option_price(candle, ctx, position)
        if curr_prem is None:
            return False
        return curr_prem >= meta.entry_premium * (1.0 + SL_PCT)

    def _get_exit_reason(
        self, position: Any, candle: dict, ctx: Any, meta: _PosMeta
    ) -> Optional[str]:
        """SL takes strict priority over reversal when both could apply same candle."""
        if self._is_sl_triggered(position, candle, ctx, meta):
            return "SL"
        if self._is_reversal_cross(position, candle, meta.magical_line):
            return "REVERSAL"
        return None

    def _reference_ml_from_position_store(self, symbol: str, ctx: Any) -> Optional[float]:
        position_store = getattr(ctx, "position_store", None)
        if position_store is None or not hasattr(position_store, "get_position_metadata"):
            return None
        try:
            bucket = position_store.get_position_metadata(symbol) or {}
        except Exception:
            return None
        sm = bucket.get("strategy_meta") if isinstance(bucket, dict) else None
        if not isinstance(sm, dict):
            return None
        raw = sm.get("one_day_magical_line") or sm.get("one_day_ml1")
        if not isinstance(raw, dict):
            return None
        ml = raw.get("magicalLine", raw.get("ml1"))
        if ml is None:
            return None
        try:
            return float(ml)
        except (TypeError, ValueError):
            return None

    def _log_main_entry_ml_gap(self, **fields: Any) -> None:
        """Structured log for ±3% next-day MAIN entry rule (grep: MAIN_ENTRY:ML_GAP)."""
        parts = []
        for key, value in fields.items():
            if value is None:
                continue
            parts.append(f"{key}={value}")
        msg = f"[{self.name}][MAIN_ENTRY:ML_GAP] " + " | ".join(parts)
        print(msg)
        logger.info(msg)

    def _passes_next_day_ml_gap_filter(
        self, symbol: str, trade_dt: date, spot_close: float, ctx: Any
    ) -> bool:
        """
        For fresh 18:30 MAIN entries on a new day, require spot to move at least
        +/-3% from the previous day's stored magical line for that symbol.
        """
        pct = NEXT_DAY_ML_GAP_PCT
        prev_ml_store = self._reference_ml_from_position_store(symbol=symbol, ctx=ctx)
        prev = self._last_daily_ml_by_symbol.get(symbol)
        prev_ml = prev_ml_store

        if prev is None and prev_ml is None:
            self._log_main_entry_ml_gap(
                outcome="NOT_EVALUATED",
                applied=False,
                rule=f"spot must be outside prior ML ±{pct:.2%}",
                reason="no prior ML: _last_daily_ml_by_symbol empty and position_store has no ML for this underlying",
                symbol=symbol,
                trade_dt=trade_dt,
                spot_close=spot_close,
            )
            return True

        if prev is not None:
            prev_dt, prev_ml_mem = prev
            if trade_dt <= prev_dt:
                self._log_main_entry_ml_gap(
                    outcome="NOT_EVALUATED",
                    applied=False,
                    rule=f"spot must be outside prior ML ±{pct:.2%}",
                    reason="calendar day <= last_daily_ml_date (intra-day repeat; ±3% gate is for a later day vs that date)",
                    symbol=symbol,
                    trade_dt=trade_dt,
                    last_ml_date=prev_dt,
                    last_ml_value=prev_ml_mem,
                    spot_close=spot_close,
                )
                return True
            if prev_ml is None:
                prev_ml = prev_ml_mem

        if prev_ml is None or prev_ml <= 0:
            self._log_main_entry_ml_gap(
                outcome="FAIL",
                applied=True,
                rule=f"spot must be outside prior ML ±{pct:.2%}",
                reason="previous magical line missing or non-positive after resolve",
                symbol=symbol,
                trade_dt=trade_dt,
                prev_ml_effective=prev_ml,
                spot_close=spot_close,
            )
            self._log_skip(
                stage="entry_ml_gap",
                reason="previous magical line is non-positive",
                symbol=symbol,
                trade_dt=trade_dt,
                prev_ml=prev_ml,
                spot_close=spot_close,
            )
            return False

        lo = prev_ml * (1.0 - NEXT_DAY_ML_GAP_PCT)
        hi = prev_ml * (1.0 + NEXT_DAY_ML_GAP_PCT)
        passes = spot_close <= lo or spot_close >= hi
        prev_source = (
            "position_store"
            if prev_ml_store is not None
            else "last_daily_ml_memory"
        )
        if passes:
            self._log_main_entry_ml_gap(
                outcome="PASS",
                applied=True,
                rule=f"spot outside prior ML ±{pct:.2%}",
                symbol=symbol,
                trade_dt=trade_dt,
                prev_ml=prev_ml,
                prev_ml_source=prev_source,
                spot_close=spot_close,
                band_low=lo,
                band_high=hi,
            )
        else:
            self._log_main_entry_ml_gap(
                outcome="FAIL",
                applied=True,
                rule=f"spot inside prior ML ±{pct:.2%} band (no entry)",
                symbol=symbol,
                trade_dt=trade_dt,
                prev_ml=prev_ml,
                prev_ml_source=prev_source,
                spot_close=spot_close,
                band_low=lo,
                band_high=hi,
            )
            self._log_skip(
                stage="entry_ml_gap",
                reason="spot close within previous ML +/- gap band",
                symbol=symbol,
                trade_dt=trade_dt,
                prev_ml=prev_ml,
                spot_close=spot_close,
                lower_band=lo,
                upper_band=hi,
            )
        return passes

    def _log_skip(self, stage: str, reason: str, **details: Any) -> None:
        parts = []
        for key, value in details.items():
            if value is None:
                continue
            parts.append(f"{key}={value}")
        suffix = f" | {', '.join(parts)}" if parts else ""
        msg = f"[{self.name}][SKIP:{stage}] {reason}{suffix}"
        print(msg)
        logger.info(msg)

    def _build_sl_reentry_on_next_candle(
        self,
        pending: _PendingSLReentry,
        candle: dict,
        ctx: Any,
        curr_spot_close: float,
    ) -> Optional[Any]:
        """
        After SL exit, re-enter on the next candle only:
        close > magical_line => short PE, close < magical_line => short CE.
        """
        if candle["timestamp"] == pending.exit_candle_ts:
            self._log_skip(
                stage="sl_reentry",
                reason="waiting for next candle after SL exit",
                symbol=pending.meta.symbol,
                exit_candle_ts=pending.exit_candle_ts,
                candle_ts=candle["timestamp"],
            )
            return None

        meta = pending.meta
        if curr_spot_close > meta.magical_line:
            option_type = "PE"
        else:
            option_type = "CE"

        next_level = (
            self._reversal_level_counter.get((meta.symbol, meta.entry_date), meta.level)
            + 1
        )
        if next_level > MAX_REVERSALS:
            self._log_skip(
                stage="sl_reentry",
                reason="max reversals reached",
                symbol=meta.symbol,
                entry_date=meta.entry_date,
                next_level=next_level,
                max_reversals=MAX_REVERSALS,
            )
            return None

        structure_id_new = self._build_structure_id(
            meta.symbol, meta.entry_date, next_level
        )
        if ctx.position_store.has_open_structure(
            strategy=self.name, structure_id=structure_id_new, tag="MAIN"
        ):
            self._log_skip(
                stage="sl_reentry",
                reason="target structure already open",
                symbol=meta.symbol,
                structure_id=structure_id_new,
            )
            return None
        if getattr(ctx, "intent_store", None) and ctx.intent_store.has_pending_intent(
            strategy=self.name,
            structure_id=structure_id_new,
            tags=["MAIN"],
            actions=["ENTRY"],
        ):
            self._log_skip(
                stage="sl_reentry",
                reason="pending MAIN ENTRY already exists",
                symbol=meta.symbol,
                structure_id=structure_id_new,
            )
            return None

        result = self._get_cached_strike_in_premium_range(
            candle, ctx, meta.symbol, option_type
        )
        if not result:
            self._log_skip(
                stage="sl_reentry",
                reason="no strike found in premium range",
                symbol=meta.symbol,
                option_type=option_type,
                premium_min=TARGET_PREMIUM_MIN,
                premium_max=TARGET_PREMIUM_MAX,
            )
            return None
        strike, premium, row = result
        if not strike:
            self._log_skip(
                stage="sl_reentry",
                reason="resolved strike is empty",
                symbol=meta.symbol,
                option_type=option_type,
            )
            return None

        expiry = ctx.selected_expiry
        trading_symbol = self.delta_option_trading_symbol(
            row,
            float(strike),
            option_type,
            str(expiry),
        )
        inst = ctx.instrument_store.intent_creation_details(
            trading_symbol,
            ctx.exchange,
            expiry,
            option_type,
            strike,
        )
        if inst is None:
            self._log_skip(
                stage="sl_reentry",
                reason="instrument details unavailable for resolved strike",
                symbol=meta.symbol,
                trading_symbol=trading_symbol,
                option_type=option_type,
                strike=strike,
            )
            return None

        self._reversal_level_counter[(meta.symbol, meta.entry_date)] = next_level
        entry_ml = float(curr_spot_close)
        new_meta = _PosMeta(
            symbol=meta.symbol,
            entry_date=meta.entry_date,
            magical_line=entry_ml,
            entry_premium=float(premium),
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
            metadata_extras=self._strategy_meta_dict(new_meta),
        )
        self._meta_by_structure_id[structure_id_new] = new_meta
        self._exit_reason_by_structure_id.pop(structure_id_new, None)
        self._last_daily_ml_by_symbol[meta.symbol] = (
            pd.to_datetime(candle["timestamp"]).date(),
            entry_ml,
        )
        return entry_intent

    # ==================================================
    # ENTRY
    # ==================================================
    def on_candle(self, candle: dict, ctx: Any):
        """Lag diagnostics: set ``ALGO_LAG_DIAG=1`` (see ``cursor.md`` / ``core/utils/lag_diag.py``)."""
        from datetime import datetime

        from core.utils.lag_diag import IST, lag_diag_enabled

        _t0 = datetime.now(IST) if lag_diag_enabled() else None
        if _t0 is not None:
            print("🚀 on_candle start:", _t0)
        try:
            return self._on_candle_body(candle, ctx)
        finally:
            if _t0 is not None and lag_diag_enabled():
                print(
                    "⚙️ Strategy execution time (sec):",
                    (datetime.now(IST) - _t0).total_seconds(),
                )

    def _on_candle_body(self, candle: dict, ctx: Any):
        symbol = candle["symbol"]
        try:
            # Commit previous candle close for cross detection.
            if symbol in self._pending_spot_close_by_symbol:
                self._last_spot_close_by_symbol[symbol] = (
                    self._pending_spot_close_by_symbol.pop(symbol)
                )

            spot_key = (symbol, candle["timestamp"])
            if spot_key not in self._candle_cache:
                self._candle_cache[spot_key] = {"spot": float(candle["close"])}
            curr_spot_close = self._candle_cache[spot_key]["spot"]

            # Entry lock: block new entries while current lifecycle is still in flight.
            if self._has_pending_main_intent(ctx, symbol):
                self._pending_spot_close_by_symbol[symbol] = curr_spot_close
                self._log_skip(
                    stage="entry",
                    reason="pending MAIN lifecycle intent exists",
                    symbol=symbol,
                    candle_ts=candle["timestamp"],
                )
                return None

            # Always stage current close for the next candle's cross detection.
            self._pending_spot_close_by_symbol[symbol] = curr_spot_close

            # SL re-entry flow: after SL MAIN_EXIT fill, wait for next candle and
            # choose side by close vs magical line (above=>short PE, below=>short CE).
            pending_sl = self._pending_sl_reentry_by_symbol.get(symbol)
            if pending_sl is not None:
                reentry_intent = self._build_sl_reentry_on_next_candle(
                    pending_sl=pending_sl,
                    candle=candle,
                    ctx=ctx,
                    curr_spot_close=float(curr_spot_close),
                )
                if reentry_intent is not None:
                    self._pending_sl_reentry_by_symbol.pop(symbol, None)
                    return [reentry_intent]

            # --------------------------------------------------
            # Initial entry: only at 17:30 (reversal ENTRY is handled in
            # on_position_exit after MAIN exit).
            # --------------------------------------------------
            if not self.should_enter(candle):
                self._log_skip(
                    stage="entry",
                    reason="candle time is not in valid entry window",
                    symbol=symbol,
                    candle_ts=candle["timestamp"],
                    valid_times=self.valid_times,
                )
                return None

            trade_dt = pd.to_datetime(candle["timestamp"]).date()
            if not self._passes_next_day_ml_gap_filter(
                symbol=symbol,
                trade_dt=trade_dt,
                spot_close=float(curr_spot_close),
                ctx=ctx,
            ):
                # Failure already logged inside _passes_next_day_ml_gap_filter (entry_ml_gap).
                return None
            open_positions = ctx.position_store.get_open_positions(
                underlying=symbol, strategy=self.name
            )
            # pdb.set_trace()
            max_positions = 5

            open_main_positions = [
                p
                for p in open_positions
                if getattr(p, "tag", None) == "MAIN" and getattr(p, "net_qty", 0) != 0
            ]

            if len(open_main_positions) >= max_positions:
                self._log_skip(
                    stage="entry",
                    reason="max open MAIN positions reached",
                    symbol=symbol,
                    open_main_positions=len(open_main_positions),
                    max_positions=max_positions,
                )
                return None

            direction = self._direction_at_1730(candle)
            option_type = self._option_type_for_direction(direction)

            magical_line = float(candle["close"])

            level = 1
            self._reversal_level_counter[(symbol, trade_dt)] = level

            structure_id = self._build_structure_id(symbol, trade_dt, level)

            if ctx.position_store.has_open_structure(
                strategy=self.name, structure_id=structure_id, tag="MAIN"
            ):
                self._log_skip(
                    stage="entry",
                    reason="structure already open",
                    symbol=symbol,
                    structure_id=structure_id,
                )
                return None

            has_pending = (
                ctx.intent_store.has_pending_intent(
                    strategy=self.name,
                    structure_id=structure_id,
                )
                if getattr(ctx, "intent_store", None)
                else False
            )
            if has_pending:
                self._log_skip(
                    stage="entry",
                    reason="pending intent exists for structure",
                    symbol=symbol,
                    structure_id=structure_id,
                )
                return None

            result = self._get_cached_strike_in_premium_range(
                candle, ctx, symbol, option_type
            )

            if result is None:
                self._log_skip(
                    stage="entry",
                    reason="no strike found in premium range",
                    symbol=symbol,
                    option_type=option_type,
                    premium_min=TARGET_PREMIUM_MIN,
                    premium_max=TARGET_PREMIUM_MAX,
                )
                return None

            strike, premium, row = result
            if not strike:
                self._log_skip(
                    stage="entry",
                    reason="resolved strike is empty",
                    symbol=symbol,
                    option_type=option_type,
                )
                return None

            expiry = ctx.selected_expiry

            trading_symbol = self.delta_option_trading_symbol(
                row,
                float(strike),
                option_type,
                str(expiry),
            )
            inst = ctx.instrument_store.intent_creation_details(
                trading_symbol, ctx.exchange, expiry, option_type, strike
            )
            if inst is None:
                self._log_skip(
                    stage="entry",
                    reason="instrument details unavailable for resolved strike",
                    symbol=symbol,
                    trading_symbol=trading_symbol,
                    option_type=option_type,
                    strike=strike,
                )
                return None

            meta = _PosMeta(
                symbol=symbol,
                entry_date=trade_dt,
                magical_line=magical_line,
                entry_premium=float(premium),
                level=level,
            )
            entry_intent = self.map_instrument_to_intent(
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
            print(">>entry_intent", entry_intent)
            main_ent = (
                f"[{self.name}][MAIN_ENTRY] emit L1 ENTRY | symbol={symbol} "
                f"trade_dt={trade_dt} magical_line_spot={magical_line} "
                f"option_type={option_type} trading_symbol={trading_symbol} "
                f"structure_id={structure_id}"
            )
            print(main_ent)
            logger.info(main_ent)
            self._meta_by_structure_id[structure_id] = meta
            self._exit_reason_by_structure_id.pop(structure_id, None)
            self._last_daily_ml_by_symbol[symbol] = (trade_dt, magical_line)

            return [entry_intent]
        finally:
            if len(self._candle_cache) > _CANDLE_CACHE_MAX:
                self._candle_cache.clear()

    # ==================================================
    # EXIT: reverse on magical line cross, else SL by premium
    # ==================================================
    def should_exit(self, position: Any, candle: dict, ctx: Any = None) -> bool:
        if position.tag != "MAIN":
            return False

        structure_id = position.structure_id
        if structure_id in self._pending_exit_structure_ids:
            return False

        if ctx is not None:
            self._restore_odml_meta_from_position(position, ctx.position_store)
        meta = self._meta_by_structure_id.get(structure_id)
        print(">>position", position)
        print(">>meta", meta)
        if meta is None:
            return False

        reason = self._get_exit_reason(position, candle, ctx, meta)
        if reason:
            self._exit_reason_by_structure_id[structure_id] = reason
            return True
        return False

    def on_main_entry_filled(
        self,
        *,
        ctx: Any,
        instrument: Any,
        structure_id: Optional[str],
        intent_id: Optional[str],
        candle_ts: Any,
        metadata_extras: Any = None,
        **kw: Any,
    ) -> List[Any]:
        """Engine calls after MAIN ENTRY fill; place broker SL when position exists."""
        if not structure_id or not intent_id:
            return []
        sid = str(structure_id)
        self._ensure_odml_meta_for_main_fill(
            sid, instrument, ctx, intent_id, metadata_extras
        )
        meta = self._meta_by_structure_id.get(sid)
        if meta is None:
            self._log_skip(
                stage="main_entry_fill",
                reason="no ODML meta after restore; broker SL skipped",
                structure_id=sid,
                intent_id=intent_id,
            )
            return []
        sl_trigger = float(meta.entry_premium * (1.0 + SL_PCT))
        fill_qty = kw.get("qty")
        ref = SimpleNamespace(
            instrument=instrument,
            structure_id=structure_id,
            intent_id=intent_id,
            qty=self._normalize_order_qty(instrument, fill_qty),
        )
        return [self._build_main_sl_intent(ref, sl_trigger, candle_ts, meta.symbol)]

    def on_main_exit_filled(self, **kwargs: Any) -> List[Tuple[Any, dict]]:
        """Engine calls after MAIN_EXIT fill; emit deferred reversal ENTRY if any."""
        structure_id = kwargs.get("structure_id")
        if not structure_id:
            return []
        structure_id = str(structure_id)
        meta = self._meta_by_structure_id.get(structure_id)
        reason_u = str(kwargs.get("exit_reason") or "").upper()
        tag_u = str(kwargs.get("tag") or "").upper()
        action_u = str(kwargs.get("action") or "").upper()
        is_sl_exit = (
            tag_u == "MAIN_SL"
            or action_u == "FORCE_EXIT"
            or reason_u == "SL"
        )
        if meta is not None and is_sl_exit:
            self._pending_sl_reentry_by_symbol[meta.symbol] = _PendingSLReentry(
                meta=meta,
                exit_candle_ts=kwargs.get("candle_ts"),
            )
        pending = self._pending_reversal_by_exit_structure_id.pop(
            structure_id, None
        )
        if pending is None:
            return []
        return [(pending.entry_intent, pending.candle)]

    def on_position_exit(self, position: Any, candle: dict, ctx: Any):
        structure_id = position.structure_id
        # Do not treat MAIN_SL (FORCE_EXIT) as blocking; it shares structure_id with MAIN.
        if getattr(ctx, "intent_store", None) and ctx.intent_store.has_pending_intent(
            strategy=self.name,
            structure_id=structure_id,
            tags=["MAIN_EXIT"],
            actions=["EXIT"],
        ):
            return []

        # Prevent duplicate exit intents if broker fill is delayed
        self._pending_exit_structure_ids.add(structure_id)

        price = self._get_cached_option_price(candle, ctx, position)
        exit_intent = self.create_order_intent(
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

        meta = self._meta_by_structure_id.get(structure_id)
        reason = self._exit_reason_by_structure_id.get(structure_id)

        if reason != "REVERSAL" or meta is None:
            return [exit_intent]

        opt_side = self._resolved_option_type_ce_pe(position.instrument)
        if opt_side not in ("PE", "CE"):
            return [exit_intent]
        reverse_option_type = "CE" if opt_side == "PE" else "PE"

        next_level = (
            self._reversal_level_counter.get((meta.symbol, meta.entry_date), meta.level)
            + 1
        )
        if next_level > MAX_REVERSALS:
            return [exit_intent]

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

        result = self._get_cached_strike_in_premium_range(
            candle, ctx, meta.symbol, reverse_option_type
        )
        if not result:
            return [exit_intent]
        strike, premium, row = result
        if not strike:
            return [exit_intent]

        expiry = ctx.selected_expiry
        trading_symbol = self.delta_option_trading_symbol(
            row,
            float(strike),
            reverse_option_type,
            str(expiry),
        )
        inst = ctx.instrument_store.intent_creation_details(
            trading_symbol,
            ctx.exchange,
            expiry,
            reverse_option_type,
            strike,
        )
        if inst is None:
            return [exit_intent]

        self._reversal_level_counter[(meta.symbol, meta.entry_date)] = next_level
        entry_ml = float(candle.get("close", meta.magical_line) or meta.magical_line)

        new_meta = _PosMeta(
            symbol=meta.symbol,
            entry_date=meta.entry_date,
            magical_line=entry_ml,
            entry_premium=float(premium),
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
            metadata_extras=self._strategy_meta_dict(new_meta),
        )
        self._meta_by_structure_id[structure_id_new] = new_meta
        self._exit_reason_by_structure_id.pop(structure_id_new, None)
        self._last_daily_ml_by_symbol[meta.symbol] = (
            pd.to_datetime(candle["timestamp"]).date(),
            entry_ml,
        )

        self._pending_reversal_by_exit_structure_id[structure_id] = _PendingReversal(
            entry_intent=entry_intent,
            candle={
                "symbol": meta.symbol,
                "timestamp": candle["timestamp"],
                "close": float(candle.get("close", 0) or 0),
                "open": candle.get("open"),
                "exchange": candle.get("exchange"),
            },
        )

        return [exit_intent]

    # ==================================================
    # CLEANUP: remove cached magical-line meta for exited structures
    # ==================================================
    def on_structure_exit(self, structure_id: str, **kwargs):
        super().on_structure_exit(structure_id=structure_id, **kwargs)
        self._pending_exit_structure_ids.discard(structure_id)
        self._exit_reason_by_structure_id.pop(structure_id, None)
        self._meta_by_structure_id.pop(structure_id, None)

    def on_forced_exit(self, **kwargs):
        """Broker-driven close (liquidation, external reduce-only); keeps strategy state in sync."""
        structure_id = kwargs.get("structure_id")
        if not structure_id:
            return
        structure_id = str(structure_id)
        meta = self._meta_by_structure_id.get(structure_id)
        reason = str(
            kwargs.get("exit_reason")
            or kwargs.get("execution_source")
            or kwargs.get("tag")
            or "FORCED"
        ).upper()
        candle_ts = kwargs.get("candle_ts") or kwargs.get("timestamp")
        tag_u = str(kwargs.get("tag") or "").upper()
        action_u = str(kwargs.get("action") or "").upper()

        # Broker-side SL/forced exits may bypass on_position_exit/on_main_exit_filled.
        # Queue next-candle SL re-entry so behavior stays consistent.
        is_sl_forced_exit = (
            reason in {"SL", "MAIN_SL", "FORCE_EXIT"}
            or tag_u == "MAIN_SL"
            or action_u == "FORCE_EXIT"
        )
        if meta is not None and is_sl_forced_exit:
            self._pending_sl_reentry_by_symbol[meta.symbol] = _PendingSLReentry(
                meta=meta, exit_candle_ts=candle_ts
            )

        self._pending_reversal_by_exit_structure_id.pop(str(structure_id), None)
        position_closed = bool(kwargs.get("position_closed"))
        if position_closed:
            self.on_structure_exit(structure_id=structure_id)
        else:
            self._exit_reason_by_structure_id[structure_id] = reason
            self._pending_exit_structure_ids.discard(structure_id)
