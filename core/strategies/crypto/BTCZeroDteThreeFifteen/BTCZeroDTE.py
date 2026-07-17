"""
BTC/ETH Zero-DTE short strangles (Delta).

Rules
- 15:15 IST: BTC premium-band CE + PE near $100.
- 15:15 IST: BTC OTM2 CE + PE.
- 15:30 IST: ETH OTM2 CE + PE.
- Hold through the day; after each MAIN fill place 100% premium stop (SL-M BUY cover).
- One re-entry per leg on the same contract/strike after premium returns to cost.
- Manage remaining leg independently.
- 17:15 IST: exit all remaining MAIN positions.

Eval style: scheduled slots (like BankNiftyBTST). ``backtest_timeframe="5"`` so
backtest bar closes at :00/:05 can hit 15:15 and 17:15 IST.

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

ENTRY_TIME = time(15, 15)
ETH_ENTRY_TIME = time(15, 30)
EXIT_TIME = time(17, 15)

# Entry switches. A disabled family cannot place initial or SL re-entry orders;
# already-open positions retain their SL/target and scheduled exit handling.
ENABLE_PREMIUM_ENTRY = True
ENABLE_BTC_OTM2_ENTRY = True
ENABLE_ETH_OTM2_ENTRY = True

# Independent quantities (lots) for the three entry families.
PREMIUM_ENTRY_LOTS = 10
BTC_OTM2_ENTRY_LOTS = 10
ETH_OTM2_ENTRY_LOTS = 10
OTM2_STEPS = 2

# Discrete BTC 0DTE strikes (~$200 spacing) often skip an exact $60–$100 print.
# Keep a band around ~$100 so CE+PE both resolve; live scorer targets band midpoint.
PREM_MIN = 50.0
PREM_MAX = 110.0
IDEAL_PREM = 100.0
# Premium-band strategy: do not inherit MagicalLine-style delta gates (0.15–0.35).
DELTA_MIN = 0.0
DELTA_MAX = 1.0
SL_PREM_MULT = 2.0  # 100% stop on short premium
TP_TRIGGER_PRICE = 0.1
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
    entry_group: str
    selection_mode: str
    otm_steps: int
    qty_lots: int


@dataclass(frozen=True)
class _PendingSLReentry:
    meta: _LegMeta
    instrument: Any
    previous_structure_id: str


class BTCZeroDTE(IndiaMktMixins, DeltaMktMixins, BaseStrategy):
    """Three independently managed BTC/ETH 0DTE short-strangle entries."""

    name = "BTCZeroDTE"
    underlying_symbols = ["BTCUSD", "ETHUSD"]
    bracket_leg_tags = ["MAIN_SL", "MAIN_TARGET"]
    timeframe = None
    backtest_timeframe = "5"
    scheduled_times = [ENTRY_TIME, ETH_ENTRY_TIME, EXIT_TIME]
    required_context = ["option_chain"]
    api = "DELTA"
    expiryType = "Daily"
    order_qty_lots = PREMIUM_ENTRY_LOTS
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
        self._pending_sl_reentry_by_structure_id: Dict[str, _PendingSLReentry] = {}

    def get_warmup_period(self):
        return 0

    @staticmethod
    def _entry_group_enabled(entry_group: str) -> bool:
        group = str(entry_group).upper()
        if group == "E2":
            return ENABLE_BTC_OTM2_ENTRY
        if group == "E3":
            return ENABLE_ETH_OTM2_ENTRY
        return ENABLE_PREMIUM_ENTRY

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

    def _strategy_meta_dict(self, meta: _LegMeta) -> dict:
        payload = {
            "symbol": meta.symbol,
            "entry_date": meta.entry_date.isoformat(),
            "option_type": meta.option_type,
            "entry_premium": meta.entry_premium,
            "reentry_count": meta.reentry_count,
            "entry_group": meta.entry_group,
            "selection_mode": meta.selection_mode,
            "otm_steps": meta.otm_steps,
            "qty_lots": meta.qty_lots,
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
                entry_group=str(raw.get("entry_group", "E1") or "E1").upper(),
                selection_mode=str(
                    raw.get("selection_mode", "PREMIUM") or "PREMIUM"
                ).upper(),
                otm_steps=int(raw.get("otm_steps", 0) or 0),
                qty_lots=int(
                    raw.get("qty_lots", PREMIUM_ENTRY_LOTS)
                    or PREMIUM_ENTRY_LOTS
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

    @staticmethod
    def _ticker_sell_price(source: Any, tickers_map: dict, symbol: str):
        ticker = tickers_map.get(str(symbol).upper()) if tickers_map else None
        if ticker is None and source is not None:
            ticker = source.get_ticker(symbol)
        if not isinstance(ticker, dict):
            return None
        quotes = ticker.get("quotes") or {}
        bid = float(quotes.get("best_bid") or 0)
        ask = float(quotes.get("best_ask") or 0)
        price = bid
        if price <= 0:
            for key in ("mark_price", "close", "price"):
                try:
                    value = float(ticker.get(key) or 0)
                except (TypeError, ValueError):
                    value = 0.0
                if value > 0:
                    price = value
                    break
        if price <= 0:
            return None
        return price, bid, ask

    def find_otm_n_strike(
        self,
        candle,
        ctx,
        option_type,
        *,
        otm_steps: int = OTM2_STEPS,
        lookback_sec: int = 60,
    ):
        """Return the exact Nth listed OTM strike; do not substitute another strike."""
        if RUN_MODE == RunMode.BACKTEST:
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
            selected_expiry = self._resolve_expiry_pref(candle, ctx, "Daily")
            work = work[work["expiry"] == selected_expiry]
            candle_time = pd.to_datetime(candle["timestamp"]).tz_localize(None)
            work = work[work["timestamp"].dt.date == candle_time.date()]
            opt = option_type.strip().upper()[0]
            work = work[work["opt_type"] == opt]
            window = max(60, int(lookback_sec))
            work = work[
                (work["timestamp"] >= candle_time - pd.Timedelta(seconds=window))
                & (work["timestamp"] <= candle_time + pd.Timedelta(seconds=window))
            ]
            if work.empty:
                return None
            latest = (
                work.sort_values("timestamp")
                .groupby("strike", as_index=False)
                .last()
            )
            latest = latest[latest["qty"] > 0]
            spot = float(candle.get("close") or 0)
            if spot <= 0:
                return None
            if opt == "C":
                latest = latest[latest["strike"] >= spot]
            else:
                latest = latest[latest["strike"] <= spot]
            latest = latest.copy()
            latest["dist"] = (latest["strike"] - spot).abs()
            latest = latest.sort_values(["dist", "strike"]).reset_index(drop=True)
            if len(latest) <= otm_steps:
                return None
            selected = latest.iloc[otm_steps]
            return float(selected["strike"]), float(selected["price"]), selected

        prepared = self._prepare_live_atm_otm_chain(
            candle,
            ctx,
            option_type,
            expiry="Daily",
            max_quotes=max(48, otm_steps + 1),
            log_prefix="BTCZeroDTE.find_otm_n_strike",
        )
        if prepared is None:
            return None
        source, _und, selected_expiry, _opt, _spot, scored, tickers_map = prepared
        if len(scored) <= otm_steps:
            logger.warning(
                "BTCZeroDTE: OTM%s unavailable symbol=%s opt=%s expiry=%s",
                otm_steps,
                candle.get("symbol"),
                option_type,
                selected_expiry,
            )
            return None
        _distance, strike, trading_symbol, _product = scored[otm_steps]
        quote = self._ticker_sell_price(source, tickers_map, trading_symbol)
        if quote is None:
            logger.warning(
                "BTCZeroDTE: no quote for OTM%s %s", otm_steps, trading_symbol
            )
            return None
        premium, bid, ask = quote
        row = pd.Series(
            {
                "symbol": trading_symbol,
                "price": premium,
                "strike": strike,
                "close": premium,
                "qty": 1,
                "best_bid": bid,
                "best_ask": ask,
                "expiry": selected_expiry,
            }
        )
        return float(strike), float(premium), row

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
        selection_mode: str = "PREMIUM",
        otm_steps: int = 0,
        qty_lots: int = PREMIUM_ENTRY_LOTS,
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

        # Entry-family level: all three entries can coexist for the same CE/PE.
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
                    return None

        mode = str(selection_mode).upper()
        if mode == "OTM":
            result = self.find_otm_n_strike(
                candle,
                ctx,
                option_type,
                otm_steps=otm_steps,
            )
        else:
            result = self.find_strike_in_premium_range(
                candle, ctx, option_type, min_prem=PREM_MIN, max_prem=PREM_MAX
            )
        if result is None:
            logger.warning(
                "BTCZeroDTE: no strike group=%s symbol=%s mode=%s opt=%s date=%s reentry=%s",
                entry_group,
                symbol,
                mode,
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
        if prem <= 0 or (mode == "PREMIUM" and prem > PREM_MAX):
            logger.info(
                "BTCZeroDTE: reject premium=%.2f mode=%s opt=%s",
                prem,
                mode,
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
            entry_group=str(entry_group).upper(),
            selection_mode=mode,
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
        intent.qty = meta.qty_lots
        self._meta_by_structure_id[structure_id] = meta
        self._entry_signaled_keys.add(guard)
        logger.info(
            "BTCZeroDTE entry %s strike=%s prem=%s expiry=%s lots=%s reentry=%s",
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

    def _build_main_target_intent(
        self,
        entry_ref: Any,
        candle_ts: Any,
        symbol: str,
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
        sid = str(getattr(position, "structure_id", "") or "")
        meta = self._meta_by_structure_id.get(sid)
        position_symbol = (
            meta.symbol
            if meta is not None
            else candle.get("symbol") or getattr(position, "symbol", "")
        )
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
            symbol=position_symbol,
            action="EXIT",
        )

    def _eod_exit_intents(self, candle: dict, ctx) -> List[Any]:
        intents: List[Any] = []
        candle_symbol = str(candle.get("symbol") or "").strip().upper()
        for pos in ctx.position_store.get_open_positions(strategy=self.name) or []:
            if getattr(pos, "tag", None) != "MAIN" or not getattr(pos, "net_qty", 0):
                continue
            sid = str(pos.structure_id or "")
            meta = self._meta_by_structure_id.get(sid)
            position_symbol = str(
                meta.symbol if meta is not None else getattr(pos, "symbol", "") or ""
            ).upper()
            if not position_symbol and sid.startswith(f"{self.name}:"):
                parts = sid.split(":")
                position_symbol = parts[1].upper() if len(parts) > 1 else ""
            if candle_symbol and position_symbol and position_symbol != candle_symbol:
                continue
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

    def _build_same_contract_reentry(
        self,
        pending: _PendingSLReentry,
        candle: dict,
        ctx: Any,
    ) -> Optional[Any]:
        """Re-enter the stopped contract only after its premium returns to cost."""
        meta = pending.meta
        if meta.reentry_count >= MAX_REENTRIES_PER_LEG:
            return None
        if ctx is None or not self._entry_group_enabled(meta.entry_group):
            return None
        candle_symbol = str(candle.get("symbol") or "").strip().upper()
        if candle_symbol and candle_symbol != str(meta.symbol).upper():
            return None

        inst = pending.instrument
        trading_symbol = str(getattr(inst, "trading_symbol", "") or "")
        if not trading_symbol:
            return None
        current_premium = self.get_option_price_at_candle(
            candle,
            ctx,
            getattr(inst, "strike", None),
            getattr(inst, "option_type", None),
            getattr(inst, "expiry", None),
            trading_symbol=trading_symbol,
        )
        if current_premium is None or float(current_premium) <= 0:
            return None
        current_premium = float(current_premium)
        if current_premium > float(meta.entry_premium):
            return None

        reentry_count = meta.reentry_count + 1
        structure_id = self._structure_id(
            meta.symbol,
            meta.entry_date,
            entry_group=meta.entry_group,
            option_type=meta.option_type,
            reentry=reentry_count,
        )
        if ctx.position_store.has_open_structure(
            strategy=self.name, structure_id=structure_id, tag="MAIN"
        ):
            return None
        intent_store = getattr(ctx, "intent_store", None)
        if intent_store is not None and intent_store.has_pending_intent(
            strategy=self.name,
            structure_id=structure_id,
            tags=["MAIN"],
            actions=["ENTRY"],
        ):
            return None

        new_meta = _LegMeta(
            symbol=meta.symbol,
            entry_date=meta.entry_date,
            option_type=meta.option_type,
            entry_premium=current_premium,
            reentry_count=reentry_count,
            entry_group=meta.entry_group,
            selection_mode=meta.selection_mode,
            otm_steps=meta.otm_steps,
            qty_lots=meta.qty_lots,
        )
        row = pd.Series(
            {
                "symbol": trading_symbol,
                "price": current_premium,
                "close": current_premium,
                "strike": getattr(inst, "strike", None),
                "expiry": getattr(inst, "expiry", None),
            }
        )
        intent = self.map_instrument_to_intent(
            inst=inst,
            strike_row=row,
            strategy=self.name,
            side="SELL",
            structure_id=structure_id,
            candle_ts=candle["timestamp"],
            tag="MAIN",
            symbol=meta.symbol,
            action="ENTRY",
            metadata_extras=self._strategy_meta_dict(new_meta),
        )
        intent.qty = meta.qty_lots
        self._meta_by_structure_id[structure_id] = new_meta
        logger.info(
            "BTCZeroDTE same-contract SL re-entry %s contract=%s "
            "premium=%.4f cost=%.4f reentry=%s",
            structure_id,
            trading_symbol,
            current_premium,
            meta.entry_premium,
            reentry_count,
        )
        return intent

    def _pending_sl_reentry_intents(self, candle: dict, ctx: Any) -> List[Any]:
        intents: List[Any] = []
        for sid, pending in list(self._pending_sl_reentry_by_structure_id.items()):
            intent = self._build_same_contract_reentry(pending, candle, ctx)
            if intent is None:
                continue
            self._pending_sl_reentry_by_structure_id.pop(sid, None)
            intents.append(intent)
        return intents

    # ---------- engine hooks ----------

    def should_evaluate(self, candle) -> bool:
        if self._pending_sl_reentry_by_structure_id:
            return True
        slot = self._active_slot(candle)
        if slot not in (ENTRY_TIME, ETH_ENTRY_TIME, EXIT_TIME):
            return False
        prefix = "exit" if slot == EXIT_TIME else f"entry-{slot.strftime('%H:%M')}"
        key = f"{prefix}|{self._evaluate_signal_key(candle)}"
        if key in self._evaluated_signal_keys:
            return False
        self._evaluated_signal_keys.add(key)
        return True

    def on_candle(self, candle, ctx):
        slot = self._active_slot(candle)
        if slot == EXIT_TIME:
            self._pending_sl_reentry_by_structure_id.clear()
            intents = self._eod_exit_intents(candle, ctx)
            return intents or None

        trade_dt = self._trade_date(candle)
        intents: List[Any] = self._pending_sl_reentry_intents(candle, ctx)
        symbol = str(candle.get("symbol") or "").strip().upper()
        entry_specs = []
        if slot == ENTRY_TIME and symbol == "BTCUSD":
            entry_specs = [
                (
                    ENABLE_PREMIUM_ENTRY,
                    "E1",
                    "PREMIUM",
                    0,
                    PREMIUM_ENTRY_LOTS,
                ),
                (
                    ENABLE_BTC_OTM2_ENTRY,
                    "E2",
                    "OTM",
                    OTM2_STEPS,
                    BTC_OTM2_ENTRY_LOTS,
                ),
            ]
        elif slot == ETH_ENTRY_TIME and symbol == "ETHUSD":
            entry_specs = [
                (
                    ENABLE_ETH_OTM2_ENTRY,
                    "E3",
                    "OTM",
                    OTM2_STEPS,
                    ETH_OTM2_ENTRY_LOTS,
                )
            ]
        else:
            return intents or None

        for enabled, entry_group, mode, otm_steps, qty_lots in entry_specs:
            if not enabled:
                continue
            for opt in ("CE", "PE"):
                leg = self._build_leg_entry(
                    candle,
                    ctx,
                    opt,
                    trade_dt,
                    entry_group=entry_group,
                    selection_mode=mode,
                    otm_steps=otm_steps,
                    qty_lots=qty_lots,
                    reentry_count=0,
                )
                if leg is not None:
                    intents.append(leg)
        return intents or None

    def should_exit(self, position, candle, ctx=None):
        if getattr(position, "tag", None) != "MAIN":
            return False
        if self._active_slot(candle) == EXIT_TIME:
            sid = str(getattr(position, "structure_id", "") or "")
            meta = self._meta_by_structure_id.get(sid)
            position_symbol = str(
                meta.symbol
                if meta is not None
                else getattr(position, "symbol", "") or ""
            ).upper()
            candle_symbol = str(candle.get("symbol") or "").upper()
            return not position_symbol or not candle_symbol or position_symbol == candle_symbol
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
            logger.warning("BTCZeroDTE: MAIN fill without meta; SL/TP skipped sid=%s", sid)
            return []
        sl_trigger = float(meta.entry_premium) * SL_PREM_MULT
        ref = SimpleNamespace(
            instrument=instrument,
            structure_id=sid,
            intent_id=intent_id,
            qty=self._normalize_order_qty(instrument, kwargs.get("qty")),
        )
        return [
            self._build_main_sl_intent(ref, sl_trigger, candle_ts, meta.symbol),
            self._build_main_target_intent(ref, candle_ts, meta.symbol),
        ]

    def on_main_exit_filled(self, **kwargs: Any) -> List[Tuple[Any, dict]]:
        structure_id = kwargs.get("structure_id")
        if not structure_id:
            return []
        sid = str(structure_id)
        self._pending_exit_structure_ids.discard(sid)
        meta = self._meta_by_structure_id.get(sid)
        tag_u = str(kwargs.get("tag") or "").upper()
        if tag_u != "MAIN_SL":
            self._pending_sl_reentry_by_structure_id.pop(sid, None)
            return []
        instrument = kwargs.get("instrument")
        if meta is None or instrument is None:
            return []
        if meta.reentry_count >= MAX_REENTRIES_PER_LEG:
            return []
        self._pending_sl_reentry_by_structure_id[sid] = _PendingSLReentry(
            meta=meta,
            instrument=instrument,
            previous_structure_id=sid,
        )
        logger.info(
            "BTCZeroDTE SL re-entry waiting sid=%s contract=%s cost=%.4f "
            "next_reentry=%s",
            sid,
            getattr(instrument, "trading_symbol", ""),
            meta.entry_premium,
            meta.reentry_count + 1,
        )
        return []

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
