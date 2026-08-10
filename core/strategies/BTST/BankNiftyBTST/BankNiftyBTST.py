"""
Bank Nifty BTST (Buy Today Sell Tomorrow) — Dhan index options.

Rules (see readme.md)
- 9:15 IST: if overnight MAIN is open and no SL is resting, arm MAIN_SL.
- 9:20 IST: pick CE and PE strikes near ~100 premium; HYBRID_GTT BUY each at premium × 1.5.
- After fill: resting SL-SELL at 50% of the limit entry price.
- 15:20 IST: cancel any unfilled ENTRY (GTT / fallback LIMIT / watches) placed today.
- If SL not hit: exit next session at 9:25 IST.


python -m run.main --engine-id dhan_banknifty_btst
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Union

import pandas as pd

from run.config import RUN_MODE, RunMode
from core.strategies.base import BaseStrategy
from core.strategies.IndiaMktMixins import IST, IndiaMktMixins
from core.utils.expiry_resolver import ExpiryResolver
from core.utils.price_tick import resolve_tick_size, round_by_tick_size

ARM_SL_TIME = time(9, 15)
ENTRY_TIME = time(9, 20)
EXIT_TIME = time(9, 25)
CANCEL_TIME = time(15, 20)

TARGET_PREMIUM = 100.0
PREM_MIN = 80.0
PREM_MAX = 120.0
LIMIT_PREM_MULT = 1.5
SL_OF_LIMIT = 0.5
# Live ENTRY: Dhan Forever (GTT) + engine watch (HYBRID_GTT).
# Watch fires when premium (LTP) reaches GTT price from below; if Forever
# still unfilled, cancel THAT leg's GTT only and place resting LIMIT at best ask/bid
# only when ask/ltp < max_fallback_price (170). Never place on top of TRIGGERED Forever.
# The other leg (e.g. PE) stays on Forever until 15:20.
# After MAIN fill: place SL (STOPLIMIT) on that position.
ENTRY_EXECUTION_MODE = "HYBRID_GTT"


BTST_META_KEY = "banknifty_btst"


@dataclass(frozen=True)
class _BtstLegMeta:
    symbol: str
    entry_date: date
    option_type: str
    ref_premium: float
    limit_price: float


class BankNiftyBTST(IndiaMktMixins, BaseStrategy):
    """
    Bank Nifty BTST: buy CE + PE near 100 premium, SL at half of limit entry, exit T+1 9:25.
    Live: wall-clock scheduled evaluation (no websocket candles).
    Backtest: 5m bar close alignment via ``backtest_timeframe``.
    """

    name = "BankNiftyBTST"
    underlying_symbols = ["BANKNIFTY"]
    bracket_leg_tags = ["MAIN_SL"]
    timeframe = None
    backtest_timeframe = "5"
    scheduled_times = [ARM_SL_TIME, ENTRY_TIME, CANCEL_TIME, EXIT_TIME]
    required_context = ["option_chain"]
    api = "DHAN"
    expiryType = "MONTHLY"
    dhan_monthly_expiry_weekday = 1  # BANKNIFTY monthly expiry: Tuesday
    dhan_monthly_rollover_days_before_expiry = 3
    dhan_option_security_id = "25"

    otm_strike_step = 100
    otm_strike_count = 10
    option_chain_strike_step = 100
    option_chain_ideal_premium = TARGET_PREMIUM

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._meta_by_structure_id: Dict[str, _BtstLegMeta] = {}
        self._snapshot_logged_slots: set[str] = set()
        self._entry_signaled_keys: set[str] = set()
        self._evaluated_signal_keys: set[str] = set()
        self._cancel_evaluated_signal_keys: set[str] = set()
        self._arm_sl_signaled_keys: set[str] = set()
        # One broker reconcile per exit slot evaluation (candle key → positions map).
        self._exit_broker_recon_key: Optional[str] = None
        self._exit_broker_positions: Optional[Dict[str, Any]] = None

    def get_warmup_period(self):
        return 0

    def _bar_minutes(self) -> int:
        tf = getattr(self, "timeframe", None) or getattr(self, "backtest_timeframe", "5")
        return int(tf) if str(tf).isdigit() else 5

    def _scheduled_slot_from_candle(self, candle: dict) -> Optional[time]:
        slot = candle.get("scheduled_slot")
        if isinstance(slot, time):
            return slot.replace(second=0, microsecond=0)
        return None

    def _active_slot(self, candle: dict) -> Optional[time]:
        slot = self._scheduled_slot_from_candle(candle)
        if slot is not None:
            return slot
        return self._bar_close_time(candle)

    def _bar_close_time(self, candle: dict) -> time:
        ts = pd.Timestamp(candle["timestamp"])
        if ts.tzinfo is None:
            ts = ts.tz_localize(IST)
        else:
            ts = ts.tz_convert(IST)
        close_ts = ts + pd.Timedelta(minutes=self._bar_minutes())
        return close_ts.time().replace(second=0, microsecond=0)

    def _candle_close_ts_ist(self, candle: dict) -> pd.Timestamp:
        """Bar close in IST. Scheduled engine candles store naive UTC in ``timestamp``."""
        slot = self._scheduled_slot_from_candle(candle)
        ts = pd.Timestamp(candle["timestamp"])
        if ts.tzinfo is None:
            if slot is not None:
                ts = ts.tz_localize("UTC").tz_convert(IST)
            else:
                ts = ts.tz_localize(IST)
        else:
            ts = ts.tz_convert(IST)
        if slot is not None:
            return ts.replace(
                hour=slot.hour, minute=slot.minute, second=0, microsecond=0
            )
        return ts + pd.Timedelta(minutes=self._bar_minutes())

    def _find_strike_snapshot_params(self, candle, ctx, option_type):
        ts_ist = self._candle_close_ts_ist(candle)
        snapshot_date = ts_ist.strftime("%Y-%m-%d")
        snapshot_time = ts_ist.strftime("%H-%M")
        # One full-chain snapshot per slot (CE + PE share the same wide table).
        slot_key = "|".join(
            [
                str(getattr(ctx, "symbol", "") or ""),
                snapshot_date,
                snapshot_time,
            ]
        )
        if slot_key in self._snapshot_logged_slots:
            return {}
        self._snapshot_logged_slots.add(slot_key)
        return {
            "snapshot": True,
            "snapshot_date": snapshot_date,
            "snapshot_time": snapshot_time,
            "snapshot_target": "banknifty_btst",
        }

    def _calendar_expiry_for_symbol(self, ctx) -> Optional[Union[date, str]]:
        exp = self._expiry_from_option_chain()
        if exp is not None:
            return exp
        sel = ctx.selected_expiry
        if sel is None:
            return None
        if isinstance(sel, int):
            td = pd.Timestamp(ctx.timestamp).date()
            wd = int(getattr(self, "dhan_monthly_expiry_weekday", 3))
            return ExpiryResolver.dhan_expiry_index_to_date(
                td, sel, monthly_expiry_weekday=wd
            )
        return sel

    def _slot_key(self, candle: dict) -> str:
        slot = self._scheduled_slot_from_candle(candle)
        if slot is not None:
            trade_dt = pd.Timestamp(candle["timestamp"]).date()
            return f"{trade_dt}|{slot.strftime('%H:%M')}"
        bucket = candle.get("bucket_ts")
        if bucket is not None:
            try:
                ts = pd.to_datetime(int(float(bucket)), unit="s", utc=True).tz_convert(IST)
                return ts.strftime("%Y-%m-%d %H:%M")
            except (TypeError, ValueError):
                pass
        ts = pd.Timestamp(candle.get("timestamp"))
        if ts.tzinfo is None:
            ts = ts.tz_localize(IST)
        else:
            ts = ts.tz_convert(IST)
        return ts.strftime("%Y-%m-%d %H:%M")

    def _entry_signal_guard_key(self, candle: dict, structure_id: str) -> str:
        # Structure already contains strategy, underlying, trade date and CE/PE.
        # Do not include slot/time: a delayed scheduler retry must not create another
        # order for the same leg later in the day.
        return structure_id

    def _evaluate_signal_key(self, candle: dict) -> str:
        symbol = str(candle.get("symbol") or "").strip().upper()
        return f"{symbol}|{self._slot_key(candle)}"

    def _structure_id(self, symbol: str, trade_dt: date, option_type: str) -> str:
        leg = str(option_type).upper()
        if leg in ("CALL", "CE"):
            leg = "CE"
        elif leg in ("PUT", "PE"):
            leg = "PE"
        return f"{self.name}:{symbol}:{trade_dt}:{leg}"

    def _strategy_meta(self, meta: _BtstLegMeta) -> dict:
        return {
            BTST_META_KEY: {
                "symbol": meta.symbol,
                "entry_date": meta.entry_date.isoformat(),
                "option_type": meta.option_type,
                "ref_premium": meta.ref_premium,
                "limit_price": meta.limit_price,
            }
        }

    def _try_merge_btst_meta_from_raw(self, structure_id: str, raw: dict) -> bool:
        """Parse persisted ``banknifty_btst`` payload into ``_meta_by_structure_id``."""
        if structure_id in self._meta_by_structure_id:
            return True
        try:
            limit_price = float(raw["limit_price"])
            ref_raw = raw.get("ref_premium")
            if ref_raw is None or float(ref_raw) <= 0:
                # Recovered GTT watches may only persist limit (= ref × LIMIT_PREM_MULT).
                ref_premium = (
                    limit_price / float(LIMIT_PREM_MULT)
                    if float(LIMIT_PREM_MULT) > 0
                    else limit_price
                )
            else:
                ref_premium = float(ref_raw)
            meta = _BtstLegMeta(
                symbol=str(raw["symbol"]),
                entry_date=date.fromisoformat(str(raw["entry_date"])),
                option_type=str(raw["option_type"]),
                ref_premium=ref_premium,
                limit_price=limit_price,
            )
        except (KeyError, TypeError, ValueError):
            return False
        self._meta_by_structure_id[structure_id] = meta
        return True

    def _restore_btst_meta_from_position(self, pos: Any, position_store: Any) -> None:
        if not pos or not getattr(pos, "structure_id", None):
            return
        sid = str(pos.structure_id)
        if sid in self._meta_by_structure_id:
            return
        sym = getattr(pos.instrument, "trading_symbol", None) if pos.instrument else None
        if sym and position_store is not None:
            bucket = position_store.get_position_metadata(sym) or {}
            sm = bucket.get("strategy_meta") or {}
            raw = sm.get(BTST_META_KEY) if isinstance(sm, dict) else None
            if isinstance(raw, dict):
                self._try_merge_btst_meta_from_raw(sid, raw)

    def _ensure_btst_meta_for_main_fill(
        self,
        structure_id: str,
        instrument: Any,
        ctx: Any,
        intent_id: Optional[str],
        metadata_extras: Any,
    ) -> None:
        """
        Repopulate BTST meta after restart from fill kwargs, open-positions CSV,
        or the original ENTRY intent in intent_store (LIMIT pending/filled).
        """
        sid = str(structure_id)
        if sid in self._meta_by_structure_id:
            return
        if isinstance(metadata_extras, dict):
            raw = metadata_extras.get(BTST_META_KEY)
            if isinstance(raw, dict):
                self._try_merge_btst_meta_from_raw(sid, raw)
        if sid in self._meta_by_structure_id:
            return
        ps = getattr(ctx, "position_store", None) if ctx is not None else None
        sym = getattr(instrument, "trading_symbol", None) if instrument else None
        if ps is not None and sym and callable(getattr(ps, "get_position_metadata", None)):
            bucket = ps.get_position_metadata(sym) or {}
            sm = bucket.get("strategy_meta") or {}
            raw = sm.get(BTST_META_KEY) if isinstance(sm, dict) else None
            if isinstance(raw, dict):
                self._try_merge_btst_meta_from_raw(sid, raw)
        if sid in self._meta_by_structure_id:
            return
        ist = getattr(ctx, "intent_store", None) if ctx is not None else None
        if ist is not None and intent_id and callable(getattr(ist, "get", None)):
            rec = ist.get(intent_id)
            if rec:
                payload = rec.get("payload") or {}
                sm = payload.get("strategy_meta")
                if isinstance(sm, dict):
                    raw = sm.get(BTST_META_KEY)
                    if isinstance(raw, dict):
                        self._try_merge_btst_meta_from_raw(sid, raw)
        if sid in self._meta_by_structure_id:
            return
        if ps is not None:
            for pos in ps.get_open_positions(strategy=self.name) or []:
                if str(getattr(pos, "structure_id", "")) == sid:
                    self._restore_btst_meta_from_position(pos, ps)
                    break

    def _cancel_evaluate_signal_key(self, candle: dict) -> str:
        return f"cancel|{self._evaluate_signal_key(candle)}"

    def _cancel_unfilled_entry_orders(self, candle: dict, ctx: Any) -> None:
        router = getattr(ctx, "order_router", None)
        if router is None or not hasattr(router, "cancel_unfilled_strategy_orders"):
            print("⚠️ BankNiftyBTST: order_router unavailable; cannot cancel unfilled orders")
            return
        trade_dt = pd.Timestamp(candle["timestamp"]).date()
        n = router.cancel_unfilled_strategy_orders(
            self.name,
            tags=["MAIN"],
            actions=["ENTRY"],
            trade_date=trade_dt,
        )
        book = getattr(router, "gtt_fallback_book", None)
        if book is not None:
            n += book.cancel_all_for_strategy(self.name, trade_date=trade_dt)
        if n:
            print(
                f"BankNiftyBTST: cancelled {n} unfilled ENTRY order(s) at "
                f"{CANCEL_TIME.strftime('%H:%M')} IST"
            )

    def should_evaluate(self, candle) -> bool:
        slot = self._active_slot(candle)
        if slot == ARM_SL_TIME:
            eval_key = f"arm_sl|{self._evaluate_signal_key(candle)}"
            if eval_key in self._evaluated_signal_keys:
                return False
            self._evaluated_signal_keys.add(eval_key)
            return True
        if slot == CANCEL_TIME:
            eval_key = self._cancel_evaluate_signal_key(candle)
            if eval_key in self._cancel_evaluated_signal_keys:
                return False
            self._cancel_evaluated_signal_keys.add(eval_key)
            return True
        if slot == EXIT_TIME:
            eval_key = f"exit|{self._evaluate_signal_key(candle)}"
            if eval_key in self._evaluated_signal_keys:
                return False
            self._evaluated_signal_keys.add(eval_key)
            return True
        if slot != ENTRY_TIME:
            return False
        eval_key = self._evaluate_signal_key(candle)
        if eval_key in self._evaluated_signal_keys:
            return False
        self._evaluated_signal_keys.add(eval_key)
        return True

    def _round_order_price(
        self,
        price: float,
        trading_symbol: str,
        ctx: Any,
        *,
        instrument: Any = None,
        side: str = "BUY",
    ) -> float:
        """Round to NSE tick (e.g. 0.05 for index options) to avoid EXCH:16283 rejections."""
        store = getattr(ctx, "instrument_store", None)
        tick = resolve_tick_size(trading_symbol, store, instrument=instrument)
        mode = "ceil" if str(side).upper() == "BUY" else "floor"
        rounded = round_by_tick_size(float(price), tick, floor_or_ceil=mode)
        return float(rounded if rounded is not None else price)

    def _build_entry_intent(
        self,
        candle: dict,
        ctx: Any,
        *,
        option_type: str,
        trade_dt: date,
    ) -> Optional[Any]:
        symbol = candle["symbol"]
        structure_id = self._structure_id(symbol, trade_dt, option_type)

        signal_key = self._entry_signal_guard_key(candle, structure_id)
        if signal_key in self._entry_signaled_keys:
            return None

        if ctx.position_store.has_open_structure(
            strategy=self.name, structure_id=structure_id, tag="MAIN"
        ):
            return None

        intent_store = getattr(ctx, "intent_store", None)
        if (
            intent_store is not None
            and callable(getattr(intent_store, "has_entry_for_structure", None))
            and intent_store.has_entry_for_structure(
                self.name,
                structure_id,
                ist_date=trade_dt,
                tags=["MAIN"],
            )
        ):
            self._entry_signaled_keys.add(signal_key)
            return None
        if intent_store is not None and intent_store.has_pending_intent(
            strategy=self.name,
            structure_id=structure_id,
            tags=["MAIN"],
            actions=["ENTRY"],
        ):
            self._entry_signaled_keys.add(signal_key)
            return None

        result = self.find_strike_in_premium_range(
            candle,
            ctx,
            option_type,
            min_prem=PREM_MIN,
            max_prem=PREM_MAX,
        )
        if result is None:
            print(f"⚠️ BankNiftyBTST: no {option_type} strike near {TARGET_PREMIUM} at {candle['timestamp']}")
            return None

        strike, ref_premium, row = result
        if not strike:
            return None

        try:
            strike = int(float(strike))
        except (TypeError, ValueError):
            return None
        if strike % 100 != 0:
            return None

        expiry = self._calendar_expiry_for_symbol(ctx)
        if expiry is None:
            print(f"⚠️ BankNiftyBTST: no expiry at {candle['timestamp']}")
            return None

        trading_symbol = ExpiryResolver.build_option_symbol(
            symbol, expiry, strike, option_type
        )
        inst = ctx.instrument_store.intent_creation_details(
            trading_symbol, ctx.exchange, expiry, option_type, strike
        )
        if inst is None:
            print(f"❌ BankNiftyBTST: instrument not found for {trading_symbol}")
            return None

        ref_premium = float(ref_premium or 0.0)
        if ref_premium <= 0:
            return None
        limit_price = self._round_order_price(
            ref_premium * LIMIT_PREM_MULT,
            trading_symbol,
            ctx,
            instrument=inst,
            side="BUY",
        )

        meta = _BtstLegMeta(
            symbol=symbol,
            entry_date=trade_dt,
            option_type=option_type,
            ref_premium=ref_premium,
            limit_price=limit_price,
        )
        self._meta_by_structure_id[structure_id] = meta
        self._entry_signaled_keys.add(signal_key)

        use_gtt = RUN_MODE == RunMode.LIVE
        strategy_meta = self._strategy_meta(meta)
        if use_gtt:
            strategy_meta["execution_mode"] = ENTRY_EXECUTION_MODE
            # Premium starts ~100; GTT limit is ~150. Fire when LTP rises to
            # limit (not ask<=limit, which is true immediately and caused LPP rejects).
            strategy_meta["gtt_fallback"] = {
                "trigger_field": "ltp",
                "trigger_op": ">=",
                "active_until": CANCEL_TIME.strftime("%H:%M"),
                "confirm_ticks": 2,
                # Do not chase premium: fallback LIMIT only if ask/ltp < 170.
                "max_fallback_price": 170.0,
            }

        return self.create_order_intent(
            inst=inst,
            side="BUY",
            qty=self._entry_order_qty(inst),
            price=float(limit_price),
            order_type="LIMIT",
            strategy=self.name,
            candle_ts=candle["timestamp"],
            structure_id=structure_id,
            tag="MAIN",
            symbol=symbol,
            action="ENTRY",
            trigger_price=float(limit_price) if use_gtt else None,
            metadata_extras=strategy_meta,
        )

    def _has_resting_main_sl(self, ctx: Any, structure_id: str) -> bool:
        intent_store = getattr(ctx, "intent_store", None)
        if intent_store is None:
            return False
        return bool(
            intent_store.has_pending_intent(
                strategy=self.name,
                structure_id=structure_id,
                tags=["MAIN_SL"],
                actions=["FORCE_EXIT"],
            )
        )

    def _exit_recon_cache_key(self, candle: dict) -> str:
        slot = self._active_slot(candle)
        slot_s = slot.strftime("%H:%M") if isinstance(slot, time) else str(slot)
        return f"{self._evaluate_signal_key(candle)}|{slot_s}"

    def _reconcile_broker_positions_for_exit(
        self, candle: dict, ctx: Any
    ) -> Optional[Dict[str, Any]]:
        """
        Live Dhan: fetch broker positions once per exit slot and sync PM.
        Returns the broker map (may be empty). None only when the fetch failed
        (caller may fall back to local). Backtest/paper skip the round-trip.
        """
        if RUN_MODE != RunMode.LIVE:
            return {}
        cache_key = self._exit_recon_cache_key(candle)
        if (
            self._exit_broker_recon_key == cache_key
            and self._exit_broker_positions is not None
        ):
            return self._exit_broker_positions

        router = getattr(ctx, "order_router", None)
        broker = getattr(router, "broker", None) if router is not None else None
        pm = getattr(ctx, "position_store", None)
        getter = getattr(broker, "get_positions_for_recon", None) if broker else None
        if not callable(getter):
            self._exit_broker_recon_key = cache_key
            self._exit_broker_positions = {}
            return {}

        try:
            broker_positions = getter() or {}
        except Exception as exc:
            print(
                f"BankNiftyBTST: broker reconcile before exit failed: {exc}; "
                "falling back to local open positions"
            )
            self._exit_broker_recon_key = cache_key
            self._exit_broker_positions = None
            return None

        if pm is not None and hasattr(pm, "reconcile_with_broker"):
            try:
                # Only claim BANKNIFTY orphans — never stamp shared-engine NIFTY
                # LEAPS legs (or other underlyings) as BankNiftyBTST.
                pm.reconcile_with_broker(
                    broker_positions,
                    strategy=self.name,
                    claim_underlying="BANKNIFTY",
                )
            except Exception as exc:
                print(
                    f"BankNiftyBTST: position_store reconcile before exit failed: {exc}"
                )

        self._exit_broker_recon_key = cache_key
        self._exit_broker_positions = dict(broker_positions)
        print(
            f"BankNiftyBTST: reconciled broker positions before exit "
            f"({len(broker_positions)} symbol(s))"
        )
        return self._exit_broker_positions

    @staticmethod
    def _position_symbol_keys(position: Any) -> set[str]:
        from core.utils.expiry_resolver import ExpiryResolver

        keys: set[str] = set()
        inst = getattr(position, "instrument", None)
        candidates = []
        if inst is not None:
            candidates.extend(
                [
                    getattr(inst, "trading_symbol", None),
                    getattr(inst, "custom_symbol", None),
                ]
            )
            place = getattr(inst, "place_order_symbol", None)
            if callable(place):
                try:
                    candidates.append(place())
                except Exception:
                    pass
        for raw in candidates:
            s = str(raw or "").strip()
            if not s:
                continue
            keys.add(s.upper())
            keys.add("".join(ch for ch in s.upper() if ch.isalnum()))
            ik = ExpiryResolver.option_identity_key(s)
            if ik:
                keys.add(ik)
        keys.discard("")
        return keys

    def _broker_has_open_position(
        self,
        position: Any,
        broker_positions: Optional[Dict[str, Any]],
    ) -> bool:
        """True if broker book still shows non-zero qty for this local MAIN."""
        if broker_positions is None:
            # Fetch failed — do not block exit on local truth.
            return int(getattr(position, "net_qty", 0) or 0) != 0
        if not broker_positions:
            return False
        from core.utils.expiry_resolver import ExpiryResolver

        want = self._position_symbol_keys(position)
        if not want:
            return int(getattr(position, "net_qty", 0) or 0) != 0
        for b_sym, row in broker_positions.items():
            b_keys = {
                str(b_sym or "").strip().upper(),
                "".join(ch for ch in str(b_sym or "").upper() if ch.isalnum()),
            }
            ik = ExpiryResolver.option_identity_key(str(b_sym or ""))
            if ik:
                b_keys.add(ik)
            if not (want & b_keys):
                continue
            try:
                qty = int((row or {}).get("qty") or 0)
            except (TypeError, ValueError):
                qty = 0
            return qty != 0
        return False

    def _arm_missing_sl_intents(self, candle: dict, ctx: Any) -> List[Any]:
        """
        For each open MAIN leg with no resting MAIN_SL, place SL until T+1 9:25 exit.
        Used at 9:15 (market open) and as catch-up at 9:20 before new entries.
        """
        ps = getattr(ctx, "position_store", None)
        if ps is None or not hasattr(ps, "get_open_positions"):
            return []
        trade_dt = pd.Timestamp(candle["timestamp"]).date()
        intents: List[Any] = []
        for pos in ps.get_open_positions(strategy=self.name) or []:
            if str(getattr(pos, "tag", "") or "").upper() != "MAIN":
                continue
            net_qty = int(getattr(pos, "net_qty", 0) or 0)
            if net_qty <= 0:
                continue
            inst = getattr(pos, "instrument", None)
            if inst is None:
                continue
            sid = str(getattr(pos, "structure_id", "") or "")
            if not sid:
                continue
            self._ensure_btst_meta_for_main_fill(
                sid,
                inst,
                ctx,
                getattr(pos, "intent_id", None),
                None,
            )
            meta = self._meta_by_structure_id.get(sid)
            entry_date = meta.entry_date if meta is not None else None
            # Only protect overnight / prior-day carries (not same-day new entries).
            if entry_date is not None and entry_date >= trade_dt:
                continue
            arm_key = f"{sid}|{trade_dt.isoformat()}"
            if arm_key in self._arm_sl_signaled_keys:
                continue
            if self._has_resting_main_sl(ctx, sid):
                self._arm_sl_signaled_keys.add(arm_key)
                continue

            limit_price = None
            if meta is not None and float(meta.limit_price or 0) > 0:
                limit_price = float(meta.limit_price)
            else:
                try:
                    avg = float(getattr(pos, "avg_price", 0) or 0)
                except (TypeError, ValueError):
                    avg = 0.0
                if avg > 0:
                    limit_price = avg
            if limit_price is None or limit_price <= 0:
                continue

            sym = getattr(inst, "trading_symbol", None) or (
                meta.symbol if meta is not None else candle.get("symbol")
            )
            sl_trigger = self._round_order_price(
                float(limit_price * SL_OF_LIMIT),
                str(sym or ""),
                ctx,
                instrument=inst,
                side="SELL",
            )
            ref = SimpleNamespace(
                instrument=inst,
                structure_id=sid,
                intent_id=getattr(pos, "intent_id", None),
                qty=self._order_qty_in_lots(inst, abs(net_qty)),
            )
            intents.append(
                self._build_main_sl_intent(
                    ref, sl_trigger, candle["timestamp"], str(sym or "BANKNIFTY")
                )
            )
            self._arm_sl_signaled_keys.add(arm_key)
            print(
                f"BankNiftyBTST: arming missing MAIN_SL for {sid} "
                f"@ {sl_trigger} (limit/avg base={limit_price})"
            )
        return intents

    def _build_overnight_exit_intents(self, candle: dict, ctx: Any) -> List[Any]:
        """T+1 9:25 square-off for open MAIN legs entered on a prior session."""
        ps = getattr(ctx, "position_store", None)
        if ps is None or not hasattr(ps, "get_open_positions"):
            return []

        # Live Dhan: reconcile once, then only exit legs still open at broker.
        broker_positions = self._reconcile_broker_positions_for_exit(candle, ctx)

        trade_dt = pd.Timestamp(candle["timestamp"]).date()
        intents: List[Any] = []
        # Prefer strategy-scoped; fall back to all opens and filter by structure_id.
        # Re-read after reconcile so locally-dropped flats are not exited.
        positions = list(ps.get_open_positions(strategy=self.name) or [])
        if not positions:
            positions = list(ps.get_open_positions() or [])
        for position in positions:
            if int(getattr(position, "net_qty", 0) or 0) <= 0:
                continue
            tag_u = str(getattr(position, "tag", "") or "").upper()
            sid = str(getattr(position, "structure_id", "") or "")
            strat = str(getattr(position, "strategy", "") or "")
            if strat and strat != self.name and not sid.startswith(f"{self.name}:"):
                continue
            if tag_u and tag_u != "MAIN" and not tag_u.startswith("MAIN_"):
                continue
            if sid:
                self._ensure_btst_meta_for_main_fill(
                    sid,
                    getattr(position, "instrument", None),
                    ctx,
                    getattr(position, "intent_id", None),
                    None,
                )
            meta = self._meta_by_structure_id.get(sid) if sid else None
            entry_date = meta.entry_date if meta is not None else None
            if entry_date is None and sid:
                # structure_id: BankNiftyBTST:BANKNIFTY:YYYY-MM-DD:CE
                parts = sid.split(":")
                if len(parts) >= 3:
                    try:
                        entry_date = date.fromisoformat(parts[2])
                    except ValueError:
                        entry_date = None
            if entry_date is None or trade_dt <= entry_date:
                continue
            if self._active_slot(candle) != EXIT_TIME:
                continue
            if not self._broker_has_open_position(position, broker_positions):
                sym = getattr(
                    getattr(position, "instrument", None), "trading_symbol", sid
                )
                print(
                    f"BankNiftyBTST: skip MAIN_EXIT for {sym} — "
                    "not open on broker after reconcile"
                )
                continue
            # Ensure tag is MAIN for exit intent builders / OMS bookkeeping.
            if not getattr(position, "tag", None):
                position.tag = "MAIN"
            if not getattr(position, "strategy", None):
                position.strategy = self.name
            exit_intents = self.on_position_exit(position, candle, ctx) or []
            intents.extend(exit_intents)
        return intents

    def on_candle(self, candle, ctx):
        slot = self._active_slot(candle)
        if slot == ARM_SL_TIME:
            return self._arm_missing_sl_intents(candle, ctx) or None
        if slot == CANCEL_TIME:
            self._cancel_unfilled_entry_orders(candle, ctx)
            return None
        if slot == EXIT_TIME:
            # Belt-and-suspenders: exit service may miss legs that lost strategy/tag
            # after broker reconcile; emit MAIN_EXIT here too.
            return self._build_overnight_exit_intents(candle, ctx) or None
        if slot != ENTRY_TIME:
            return None

        # Catch-up if engine missed 9:15: arm missing overnight SLs before new entries.
        intents: List[Any] = list(self._arm_missing_sl_intents(candle, ctx))

        trade_dt = pd.Timestamp(candle["timestamp"]).date()
        for opt in ("CE", "PE"):
            leg_intent = self._build_entry_intent(
                candle, ctx, option_type=opt, trade_dt=trade_dt
            )
            if leg_intent is not None:
                intents.append(leg_intent)

        return intents or None

    def _build_main_sl_intent(
        self,
        entry_ref: Any,
        trigger_price: float,
        candle_ts: Any,
        symbol: str,
    ) -> Any:
        # Dhan/Tradehull accepts STOPLIMIT ("SL"), not raw "SL-M" (KeyError).
        # SELL stop-limit: trigger arms when premium falls; limit must be
        # strictly below trigger (DH-906 rejects trigger == price).
        trig = float(trigger_price)
        tick = resolve_tick_size(
            str(symbol or ""),
            None,
            instrument=getattr(entry_ref, "instrument", None),
        )
        limit = float(
            round_by_tick_size(trig - tick, tick, floor_or_ceil="floor")
            or max(tick, trig - tick)
        )
        if limit <= 0 or limit >= trig:
            limit = max(float(tick), trig - float(tick))
        return self.create_order_intent(
            inst=entry_ref.instrument,
            side="SELL",
            qty=entry_ref.qty,
            price=limit,
            order_type="SL",
            strategy=self.name,
            candle_ts=candle_ts,
            structure_id=entry_ref.structure_id,
            tag="MAIN_SL",
            symbol=symbol,
            action="FORCE_EXIT",
            parent_intent_id=entry_ref.intent_id,
            trigger_price=trig,
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
        **kwargs: Any,
    ) -> List[Any]:
        if not structure_id or not intent_id:
            return []
        sid = str(structure_id)
        # Idempotent: never arm a second MAIN_SL for the same structure.
        if self._has_resting_main_sl(ctx, sid):
            return []
        self._ensure_btst_meta_for_main_fill(
            sid, instrument, ctx, intent_id, metadata_extras
        )
        meta = self._meta_by_structure_id.get(sid)
        if meta is None:
            return []
        store = getattr(ctx, "instrument_store", None)
        sym = getattr(instrument, "trading_symbol", None) or meta.symbol
        sl_trigger = self._round_order_price(
            float(meta.limit_price * SL_OF_LIMIT),
            sym,
            ctx,
            instrument=instrument,
            side="SELL",
        )
        fill_qty = kwargs.get("qty")
        ref = SimpleNamespace(
            instrument=instrument,
            structure_id=sid,
            intent_id=intent_id,
            qty=self._normalize_order_qty(instrument, fill_qty),
        )
        return [self._build_main_sl_intent(ref, sl_trigger, candle_ts, meta.symbol)]

    def should_exit(self, position, candle, ctx=None):
        net_qty = int(getattr(position, "net_qty", 0) or 0)
        if net_qty <= 0:
            return False
        tag_u = str(getattr(position, "tag", "") or "").upper()
        # After broker reconcile, tag/strategy may be blank; allow exit if structure
        # still identifies this as a BTST MAIN (or tag is empty).
        sid = str(getattr(position, "structure_id", "") or "")
        if tag_u and tag_u != "MAIN" and not tag_u.startswith("MAIN_"):
            return False
        if not tag_u and sid and not sid.startswith(f"{self.name}:"):
            return False
        if sid:
            self._ensure_btst_meta_for_main_fill(
                sid,
                position.instrument,
                ctx,
                getattr(position, "intent_id", None),
                None,
            )
        meta = self._meta_by_structure_id.get(sid) if sid else None
        entry_date = meta.entry_date if meta is not None else None
        if entry_date is None and sid:
            parts = sid.split(":")
            if len(parts) >= 3:
                try:
                    entry_date = date.fromisoformat(parts[2])
                except ValueError:
                    entry_date = None
        if entry_date is None:
            return False
        trade_dt = pd.Timestamp(candle["timestamp"]).date()
        if trade_dt <= entry_date:
            return False
        if self._active_slot(candle) != EXIT_TIME:
            return False
        if ctx is not None:
            broker_positions = self._reconcile_broker_positions_for_exit(candle, ctx)
            if not self._broker_has_open_position(position, broker_positions):
                return False
        return True

    def on_position_exit(self, position, candle, ctx):
        price = (
            self.get_option_price_at_candle(
                candle,
                ctx,
                position.instrument.strike,
                position.instrument.option_type,
                position.instrument.expiry,
                trading_symbol=position.instrument.trading_symbol,
            )
            if RUN_MODE == RunMode.BACKTEST
            else None
        )
        return [
            self.create_order_intent(
                inst=position.instrument,
                side="SELL",
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
        ]
