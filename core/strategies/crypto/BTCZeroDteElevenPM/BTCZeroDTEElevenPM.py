"""
BTC overnight OTM10 + OTM15 short strangles (Delta).

Rules
- 23:15 IST: sell OTM10 / OTM15 CE+PE (Daily expiry).
- After MAIN fill place 100% premium stop.
- After MAIN_SL: OMS reentry-at-cost (declare ``reentry_at_cost``; poll/persist in OMS).
- Up to 2 successful re-entries per leg; OMS stops once strike is open again.
- 17:15 IST: exit remaining MAIN positions.

Eval style: scheduled slots. OMS owns SL re-entry-at-cost.

Run: ``python -m run.main --engine-id delta_engine_one``
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import date, time, timedelta
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from run.config import RUN_MODE, RunMode
from core.strategies.base import BaseStrategy
from core.strategies.IndiaMktMixins import IST, IndiaMktMixins
from core.strategies.deltaMktMixins import DeltaMktMixins
from core.strategies.meta import pack_strategy_meta

logger = logging.getLogger(__name__)

ENTRY_TIME = time(23, 15)
EXIT_TIME = time(17, 15)

# Entry switches. Disabling a family blocks its initial entries and SL re-entries;
# existing positions still retain their SL/target and 17:15 exit handling.
ENABLE_FIRST_ENTRY = True
ENABLE_SECOND_ENTRY = True

# First entry: OTM10 with fallback to the farthest available OTM.
FIRST_ENTRY_OTM_STEPS = 10
FIRST_ENTRY_LOTS = 10
# Second entry: strict OTM15; CE and PE are resolved independently.
SECOND_ENTRY_OTM_STEPS = 15
SECOND_ENTRY_LOTS = 10
# Backward-compatible alias for the original entry.
OTM_STEPS = FIRST_ENTRY_OTM_STEPS
# Hard floor for every *initial* entry.
MIN_ENTRY_PREMIUM = 5.0
MIN_REENTRY_PREMIUM = 0.1
# Premium SL at 2x entry = 100% stop on short premium.
SL_PREM_MULT = 2.0
TP_TRIGGER_PRICE = 0.1
MAX_REENTRIES_PER_LEG = 2
EXPIRY_PREF = "Daily"

META_KEY = "btc_zero_dte_eleven_pm"
REGISTRY_KEY = "BTCZeroDTEElevenPM"


@dataclass(frozen=True)
class _LegMeta:
    symbol: str
    entry_date: date
    option_type: str
    entry_premium: float
    reentry_count: int
    entry_group: str
    otm_steps: int
    qty_lots: int



class BTCZeroDTEElevenPM(IndiaMktMixins, DeltaMktMixins, BaseStrategy):
    """Delta BTC OTM10 + OTM15 entries with independent leg management."""

    name = "BTCZeroDTEElevenPM"
    underlying_symbols = ["BTCUSD"]
    bracket_leg_tags = ["MAIN_SL", "MAIN_TARGET"]
    timeframe = None
    backtest_timeframe = "5"
    scheduled_times = [ENTRY_TIME, EXIT_TIME]
    required_context = ["option_chain"]
    api = "DELTA"
    expiryType = EXPIRY_PREF
    order_qty_lots = FIRST_ENTRY_LOTS
    otm_strike_step = 200
    otm_strike_count = SECOND_ENTRY_OTM_STEPS + 1
    reentry_at_cost = {
        "enabled": True,
        "max_reentries": MAX_REENTRIES_PER_LEG,
        "poll_interval_sec": 300,
        "min_premium": MIN_REENTRY_PREMIUM,
        "until_expiry": True,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._meta_by_structure_id: Dict[str, _LegMeta] = {}
        self._evaluated_signal_keys: set[str] = set()
        self._entry_signaled_keys: set[str] = set()
        self._pending_exit_structure_ids: set[str] = set()
        self._snapshot_logged_slots: set[str] = set()

    def get_warmup_period(self):
        return 0

    @staticmethod
    def _entry_group_enabled(entry_group: str) -> bool:
        if str(entry_group).upper() == "E2":
            return ENABLE_SECOND_ENTRY
        return ENABLE_FIRST_ENTRY

    def reentry_at_cost_allowed(self, metadata_extras: Any) -> bool:
        from core.strategies.meta import unpack_strategy_meta

        payload = unpack_strategy_meta(metadata_extras) or {}
        if isinstance(metadata_extras, dict) and META_KEY in metadata_extras:
            raw = metadata_extras.get(META_KEY)
            if isinstance(raw, dict):
                payload = raw
        group = str(payload.get("entry_group", "E1") or "E1")
        return self._entry_group_enabled(group)

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
        self,
        symbol: str,
        trade_dt: date,
        option_type: str,
        *,
        entry_group: str = "E1",
        reentry: int = 0,
    ) -> str:
        leg = str(option_type).upper()
        if leg in ("CALL", "CE"):
            leg = "CE"
        elif leg in ("PUT", "PE"):
            leg = "PE"
        group_suffix = "" if str(entry_group).upper() == "E1" else f":{entry_group}"
        if reentry > 0:
            return f"{self.name}:{symbol}:{trade_dt}:{leg}{group_suffix}:R{reentry}"
        return f"{self.name}:{symbol}:{trade_dt}:{leg}{group_suffix}"

    @staticmethod
    def _entry_expiry(trade_dt: date) -> str:
        """The 23:00 entry trades the Daily contract expiring next calendar day."""
        return (trade_dt + timedelta(days=1)).strftime("%d%m%y")

    def _strategy_meta_dict(self, meta: _LegMeta) -> dict:
        payload = {
            "symbol": meta.symbol,
            "entry_date": meta.entry_date.isoformat(),
            "option_type": meta.option_type,
            "entry_premium": meta.entry_premium,
            "reentry_count": meta.reentry_count,
            "entry_group": meta.entry_group,
            "otm_steps": meta.otm_steps,
            "qty_lots": meta.qty_lots,
            "reentry_at_cost": dict(self.reentry_at_cost),
        }
        out = pack_strategy_meta(REGISTRY_KEY, payload)
        out[META_KEY] = payload
        out["reentry_at_cost"] = dict(self.reentry_at_cost)
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
                entry_group=str(raw.get("entry_group", "E1") or "E1").upper(),
                otm_steps=int(
                    raw.get("otm_steps", FIRST_ENTRY_OTM_STEPS)
                    or FIRST_ENTRY_OTM_STEPS
                ),
                qty_lots=int(
                    raw.get("qty_lots", FIRST_ENTRY_LOTS) or FIRST_ENTRY_LOTS
                ),
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

    # ---------- strike (OTM10, fallback to last available) ----------

    def _pick_otm_index(
        self,
        available: int,
        otm_steps: int,
        option_type: str,
        *,
        allow_fallback: bool,
    ) -> Optional[int]:
        """Resolve OTM-N, optionally falling back to the farthest listed strike."""
        if available <= 0:
            return None
        if available > otm_steps:
            return int(otm_steps)
        if not allow_fallback:
            logger.warning(
                "BTCZeroDTEElevenPM: strict OTM%s unavailable opt=%s (have %s); skipping leg",
                otm_steps,
                option_type,
                available,
            )
            return None
        idx = available - 1
        logger.warning(
            "BTCZeroDTEElevenPM: OTM%s unavailable opt=%s (have %s); using last available OTM%s",
            otm_steps,
            option_type,
            available,
            idx,
        )
        return idx

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
            "snapshot_target": META_KEY,
        }

    def _ltp_from_ticker_map(
        self,
        source: Any,
        tickers_map: dict,
        sym: str,
        *,
        side: str = "SELL",
    ) -> Tuple[float, float, float]:
        """Return ``(ltp, bid, ask)``; ltp uses bid for SELL / ask for BUY."""
        sym_u = (sym or "").upper()
        t = tickers_map.get(sym_u) if tickers_map else None
        if t is None and source is not None:
            t = source.get_ticker(sym)
        if not isinstance(t, dict):
            return 0.0, 0.0, 0.0
        quotes = t.get("quotes") or {}
        bid = float(quotes.get("best_bid") or 0)
        ask = float(quotes.get("best_ask") or 0)
        trade_side = str(side or "SELL").upper()
        ltp = ask if trade_side == "BUY" else bid
        if ltp <= 0:
            for key in ("mark_price", "close", "price"):
                try:
                    v = float(t.get(key) or 0)
                except (TypeError, ValueError):
                    v = 0.0
                if v > 0:
                    ltp = v
                    break
        return ltp, bid, ask

    def find_otm_n_strike(
        self,
        candle,
        ctx,
        option_type,
        *,
        otm_steps: int = OTM_STEPS,
        expiry: str = EXPIRY_PREF,
        lookback_sec: int = 60,
        allow_fallback: bool = True,
    ):
        """Pick OTM-N, with optional fallback to the farthest listed strike."""
        if RUN_MODE == RunMode.BACKTEST:
            return self._find_otm_n_strike_backtest(
                candle,
                ctx,
                option_type,
                otm_steps=otm_steps,
                expiry=expiry,
                lookback_sec=lookback_sec,
                allow_fallback=allow_fallback,
            )
        return self._find_otm_n_strike_live(
            candle,
            ctx,
            option_type,
            otm_steps=otm_steps,
            expiry=expiry,
            allow_fallback=allow_fallback,
        )

    def _find_otm_n_strike_backtest(
        self,
        candle,
        ctx,
        option_type,
        *,
        otm_steps: int,
        expiry: str,
        lookback_sec: int,
        allow_fallback: bool,
    ):
        df = self.load_delta_data_for_candle(candle, ctx)
        if df is None or df.empty:
            return None

        work = df.copy()
        work.columns = [
            "symbol",
            "price",
            "qty",
            "timestamp",
            "side",
            "opt_type",
            "strike",
            "expiry",
        ]
        work["timestamp"] = pd.to_datetime(work["timestamp"])
        parts = work["symbol"].str.split("-", expand=True)
        work["opt_type"] = parts[0]
        work["strike"] = parts[2].astype(float)
        work["expiry"] = parts[3]

        selected_expiry = self._resolve_expiry_pref(candle, ctx, expiry)
        if selected_expiry is None:
            return None
        work = work[work["expiry"] == selected_expiry]
        if work.empty:
            return None

        candle_time = pd.to_datetime(candle["timestamp"]).tz_localize(None)
        work = work[work["timestamp"].dt.date == candle_time.date()]
        if work.empty:
            return None

        opt = option_type.strip().upper()[0]
        work = work[work["opt_type"] == opt]
        if work.empty:
            return None

        start_time = candle_time - pd.Timedelta(seconds=max(int(lookback_sec), 60))
        end_time = candle_time + pd.Timedelta(seconds=max(int(lookback_sec), 60))
        work = work[(work["timestamp"] >= start_time) & (work["timestamp"] <= end_time)]
        if work.empty:
            return None

        work = work.sort_values("timestamp")
        latest = work.groupby("strike", as_index=False).last()
        latest = latest[latest["qty"] > 0]
        if latest.empty:
            return None

        spot = float(candle.get("close") or 0)
        if spot <= 0:
            return None
        if opt == "C":
            latest = latest[latest["strike"] >= spot]
        else:
            latest = latest[latest["strike"] <= spot]
        if latest.empty:
            return None

        latest = latest.copy()
        latest["dist"] = (latest["strike"] - spot).abs()
        latest = latest.sort_values(["dist", "strike"]).reset_index(drop=True)
        idx = self._pick_otm_index(
            len(latest),
            otm_steps,
            option_type,
            allow_fallback=allow_fallback,
        )
        if idx is None:
            return None
        selected = latest.iloc[idx]
        return (
            float(selected["strike"]),
            float(selected["price"]),
            selected,
        )

    def _find_otm_n_strike_live(
        self,
        candle,
        ctx,
        option_type,
        *,
        otm_steps: int,
        expiry: str,
        allow_fallback: bool,
    ):
        prepared = self._prepare_live_atm_otm_chain(
            candle,
            ctx,
            option_type,
            expiry=expiry,
            max_quotes=max(48, otm_steps + 1),
            log_prefix="find_otm_n_strike_live",
        )
        if prepared is None:
            return None
        source, _und, selected_expiry, _opt, _spot, scored, tickers_map = prepared
        if str(selected_expiry) != str(expiry):
            logger.warning(
                "BTCZeroDTEElevenPM: strict next-day expiry %s unavailable; "
                "rejecting fallback expiry %s",
                expiry,
                selected_expiry,
            )
            return None
        idx = self._pick_otm_index(
            len(scored),
            otm_steps,
            option_type,
            allow_fallback=allow_fallback,
        )
        if idx is None:
            return None

        # OTM10 may walk inward if the selected quote has no LTP. Strict OTM15
        # checks only index 15, allowing CE and PE to succeed independently.
        indices = range(idx, -1, -1) if allow_fallback else (idx,)
        for try_idx in indices:
            _dist, strike, sym, _prod = scored[try_idx]
            ltp, bid, ask = self._ltp_from_ticker_map(
                source, tickers_map, sym, side="SELL"
            )
            if ltp <= 0:
                continue
            if try_idx != idx:
                logger.warning(
                    "BTCZeroDTEElevenPM: no LTP at OTM%s; using OTM%s %s",
                    idx,
                    try_idx,
                    sym,
                )
            row = pd.Series(
                {
                    "symbol": sym,
                    "price": ltp,
                    "strike": strike,
                    "close": ltp,
                    "qty": 1,
                    "best_bid": bid,
                    "best_ask": ask,
                    "expiry": selected_expiry,
                }
            )
            return float(strike), float(ltp), row

        logger.warning(
            "BTCZeroDTEElevenPM: no LTP among OTM0..OTM%s opt=%s expiry=%s",
            idx,
            option_type,
            selected_expiry,
        )
        return None

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
        entry_group: str = "E1",
        otm_steps: int = FIRST_ENTRY_OTM_STEPS,
        qty_lots: int = FIRST_ENTRY_LOTS,
        allow_fallback: bool = True,
        reentry_count: int = 0,
    ) -> Optional[Any]:
        if not self._entry_group_enabled(entry_group):
            return None
        symbol = str(candle.get("symbol") or "BTCUSD")
        structure_id = self._structure_id(
            symbol,
            trade_dt,
            option_type,
            entry_group=entry_group,
            reentry=reentry_count,
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

        # Entry-family level: E1 and E2 can coexist for the same CE/PE.
        if reentry_count == 0:
            leg = str(option_type).upper()
            if leg in ("CALL", "CE"):
                leg = "CE"
            elif leg in ("PUT", "PE"):
                leg = "PE"
            day_prefix = self._structure_id(
                symbol,
                trade_dt,
                leg,
                entry_group=entry_group,
            )
            for pos in ctx.position_store.get_open_positions(strategy=self.name) or []:
                sid = str(getattr(pos, "structure_id", "") or "")
                if (
                    (sid == day_prefix or sid.startswith(f"{day_prefix}:R"))
                    and getattr(pos, "tag", None) == "MAIN"
                ):
                    logger.info(
                        "BTCZeroDTEElevenPM: skip %s ENTRY %s — MAIN already open (%s)",
                        entry_group,
                        leg,
                        sid,
                    )
                    return None

        expiry = self._entry_expiry(trade_dt)
        # ``_resolve_expiry_pref`` preserves an existing context expiry for explicit
        # DDMMYY values, so pin the context before scanning the option chain.
        ctx.selected_expiry = expiry
        result = self.find_otm_n_strike(
            candle,
            ctx,
            option_type,
            otm_steps=otm_steps,
            expiry=expiry,
            allow_fallback=allow_fallback,
        )
        if result is None:
            logger.warning(
                "BTCZeroDTEElevenPM: no %s OTM%s strike opt=%s date=%s reentry=%s",
                entry_group,
                otm_steps,
                option_type,
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
        if prem <= MIN_ENTRY_PREMIUM:
            logger.info(
                "BTCZeroDTEElevenPM: reject premium=%.4f (min=%.2f) opt=%s",
                prem,
                MIN_ENTRY_PREMIUM,
                option_type,
            )
            return None

        trading_symbol = self.delta_option_trading_symbol(
            row, float(strike), option_type, str(expiry)
        )
        inst = ctx.instrument_store.intent_creation_details(
            trading_symbol, ctx.exchange, expiry, option_type, strike
        )
        if inst is None:
            logger.warning(
                "BTCZeroDTEElevenPM: instrument missing %s", trading_symbol
            )
            return None

        meta = _LegMeta(
            symbol=symbol,
            entry_date=trade_dt,
            option_type=str(option_type).upper(),
            entry_premium=prem,
            reentry_count=int(reentry_count),
            entry_group=str(entry_group).upper(),
            otm_steps=int(otm_steps),
            qty_lots=max(1, int(qty_lots)),
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
        # Keep E1/E2 sizing independent of the engine-wide ORDER_QTY_LOTS value.
        intent = replace(intent, qty=meta.qty_lots)
        self._meta_by_structure_id[structure_id] = meta
        self._entry_signaled_keys.add(guard)
        logger.info(
            "BTCZeroDTEElevenPM entry %s strike=%s prem=%s expiry=%s lots=%s reentry=%s",
            structure_id,
            strike,
            prem,
            expiry,
            meta.qty_lots,
            reentry_count,
        )
        return intent

    def _build_main_sl_intent(
        self,
        entry_ref: Any,
        trigger_price: float,
        candle_ts: Any,
        symbol: str,
        meta: Optional[_LegMeta] = None,
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
            metadata_extras=self._strategy_meta_dict(meta) if meta is not None else None,
        )

    def _build_main_target_intent(
        self,
        entry_ref: Any,
        candle_ts: Any,
        symbol: str,
        meta: Optional[_LegMeta] = None,
    ) -> Any:
        target = float(TP_TRIGGER_PRICE)
        return self.create_order_intent(
            inst=entry_ref.instrument,
            side="BUY",
            qty=entry_ref.qty,
            price=target,
            order_type="SL-M",
            strategy=self.name,
            candle_ts=candle_ts,
            structure_id=entry_ref.structure_id,
            tag="MAIN_TARGET",
            symbol=symbol,
            action="FORCE_EXIT",
            parent_intent_id=entry_ref.intent_id,
            trigger_price=target,
            metadata_extras=self._strategy_meta_dict(meta) if meta is not None else None,
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

        intents: List[Any] = []
        trade_dt = self._trade_date(candle)
        entry_specs = (
            (
                ENABLE_FIRST_ENTRY,
                "E1",
                FIRST_ENTRY_OTM_STEPS,
                FIRST_ENTRY_LOTS,
                True,
            ),
            (
                ENABLE_SECOND_ENTRY,
                "E2",
                SECOND_ENTRY_OTM_STEPS,
                SECOND_ENTRY_LOTS,
                False,
            ),
        )
        for enabled, entry_group, otm_steps, qty_lots, allow_fallback in entry_specs:
            if not enabled:
                continue
            for opt in ("CE", "PE"):
                leg = self._build_leg_entry(
                    candle,
                    ctx,
                    opt,
                    trade_dt,
                    entry_group=entry_group,
                    otm_steps=otm_steps,
                    qty_lots=qty_lots,
                    allow_fallback=allow_fallback,
                    reentry_count=0,
                )
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
            logger.warning(
                "BTCZeroDTEElevenPM: MAIN fill without meta; SL/TP skipped sid=%s", sid
            )
            return []
        sl_trigger = float(meta.entry_premium) * SL_PREM_MULT
        ref = SimpleNamespace(
            instrument=instrument,
            structure_id=sid,
            intent_id=intent_id,
            qty=self._normalize_order_qty(instrument, kwargs.get("qty")),
        )
        return [
            self._build_main_sl_intent(ref, sl_trigger, candle_ts, meta.symbol, meta),
            self._build_main_target_intent(ref, candle_ts, meta.symbol, meta),
        ]

    def on_main_exit_filled(self, **kwargs: Any) -> List[Tuple[Any, dict]]:
        # OMS ReentryAtCostBook arms from metadata_extras.reentry_at_cost on MAIN_SL.
        structure_id = kwargs.get("structure_id")
        if structure_id:
            self._pending_exit_structure_ids.discard(str(structure_id))
        return []

    def on_forced_exit(self, **kwargs: Any):
        structure_id = kwargs.get("structure_id")
        if not structure_id:
            return
        sid = str(structure_id)
        self._pending_exit_structure_ids.discard(sid)

    def on_structure_exit(self, structure_id: str, **kwargs):
        super().on_structure_exit(structure_id=structure_id, **kwargs)
        self._pending_exit_structure_ids.discard(str(structure_id))
        sid = str(structure_id)
        meta = self._meta_by_structure_id.get(sid)
        if meta is not None and meta.reentry_count >= MAX_REENTRIES_PER_LEG:
            self._meta_by_structure_id.pop(sid, None)
