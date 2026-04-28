from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd

from core.strategies.IndiaMktMixins import IST, IndiaMktMixins
from core.strategies.base import BaseStrategy
from core.utils.expiry_resolver import ExpiryResolver
from run.config import RUN_MODE, RunMode


ENTRY_SNAPSHOT_TIME = time(9, 30)
ENTRY_EVAL_TIME = time(10, 45)
EOD_REVIEW_TIME = time(15, 15)

PREMIUM_MIN = 180
PREMIUM_MAX = 220
PREMIUM_CHANGE_LIMIT_PCT = 80
TARGET_MULTIPLIER = 1.5
STOP_LOSS_PCT = 0.40


@dataclass(frozen=True)
class OISnapshot:
    option_type: str
    strike: int
    premium: float
    oi: float
    ts: pd.Timestamp


@dataclass
class PositionMeta:
    symbol: str
    option_type: str
    strike: int
    benchmark_premium: float
    benchmark_oi: float
    entry_premium: float
    entry_date: date
    structure_id: str


@dataclass(frozen=True)
class PendingEntry:
    entry_intent: Any


class OIPositionalBuy(IndiaMktMixins, BaseStrategy):
    """
    OI Positional Buy for Dhan

    Rules implemented:
    - 09:30: capture benchmark snapshot
    - 10:45: classify OI signal vs 09:30 and buy best "LONG" candidate
    - Intraday: TP at +50% / 1.5x and SL at -40% (no re-entry on SL day)
    - 15:15: if signal unchanged hold overnight, else exit and optionally rotate
    """

    name = "OIPositionalBuy"
    timeframe = "15"
    required_context = ["option_chain"]
    api = "DHAN"
    expiryType = "MONTHLY"
    otm_strike_step = 100
    otm_strike_count = 30

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._benchmarks_by_day: Dict[date, Dict[str, List[OISnapshot]]] = {}
        self._position_meta_by_sid: Dict[str, PositionMeta] = {}
        self._sl_blocked_day_by_symbol: Dict[str, date] = {}
        self._pending_exit_sids: set[str] = set()
        self._exit_reason_by_sid: Dict[str, str] = {}
        self._pending_entry_by_exit_sid: Dict[str, PendingEntry] = {}

    def get_warmup_period(self):
        return 0

    def should_evaluate(self, candle):
        return True

    def _ist_time(self, candle: dict) -> time:
        ts = pd.Timestamp(candle["timestamp"])
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts.tz_convert(IST).time().replace(second=0, microsecond=0)

    def _trade_date(self, candle: dict) -> date:
        ts = pd.Timestamp(candle["timestamp"])
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts.tz_convert(IST).date()

    def _snapshot_enabled_for_candle(self, candle: dict) -> bool:
        t = self._ist_time(candle)
        return t in {ENTRY_SNAPSHOT_TIME, ENTRY_EVAL_TIME, EOD_REVIEW_TIME}

    def _snapshot_params(self, candle: dict) -> Dict[str, Any]:
        ts = pd.Timestamp(candle["timestamp"])
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        ts_ist = ts.tz_convert(IST)
        enabled = self._snapshot_enabled_for_candle(candle)
        return {
            "snapshot": enabled,
            "snapshot_date": ts_ist.strftime("%Y-%m-%d"),
            "snapshot_time": ts_ist.strftime("%H%M"),
        }

    def _oi_column(self, df: pd.DataFrame, option_type: str) -> Optional[str]:
        opt = option_type.upper()
        candidates = []
        for c in df.columns:
            cu = str(c).upper()
            if "OI" not in cu and "OPEN INTEREST" not in cu:
                continue
            if opt in cu:
                candidates.append(c)
        if candidates:
            return candidates[0]
        for c in df.columns:
            cu = str(c).upper()
            if "OI" in cu or "OPEN INTEREST" in cu:
                return c
        return None

    def _fetch_chain_df(self, candle: dict, ctx: Any, option_type: str) -> Optional[pd.DataFrame]:
        strikes = self.fetch_option_chain(candle, ctx, option_type)
        if not strikes:
            return None
        strike_param = [str(int(float(s))) for s in strikes]
        params = {
            "exchange": ctx.exchange,
            "interval": self.timeframe,
            "expiry_code": ctx.selected_expiry,
            "strike": strike_param,
            "option_type": option_type,
            "instrument": "OPTIDX",
            "exchangeSegment": "NSE_FNO",
            "expiry_flag": "MONTH",
            "securityId": "13",
        }
        params.update(self._snapshot_params(candle))
        raw = ctx.option_chain_service.get_chain(api=self.api, ctx=ctx, params=params)
        df = raw.get("chain") if isinstance(raw, dict) else raw
        if not isinstance(df, pd.DataFrame) or df.empty:
            return None
        if "datetime" in df.columns:
            wall = pd.to_datetime(df["datetime"]).dt.strftime("%Y-%m-%d %H:%M")
            wall_c = pd.Timestamp(candle["timestamp"]).tz_localize(None).strftime("%Y-%m-%d %H:%M")
            filt = df[wall == wall_c]
            if not filt.empty:
                df = filt
        return df

    def _extract_snapshots(
        self,
        candle: dict,
        ctx: Any,
        option_type: str,
        strikes_filter: Optional[set[int]] = None,
        apply_premium_filter: bool = True,
    ) -> List[OISnapshot]:
        df = self._fetch_chain_df(candle, ctx, option_type)
        if df is None or df.empty:
            return []
        strike_col = self._option_chain_strike_column(df)
        prem_col = self._option_chain_premium_column(df, option_type)
        oi_col = self._oi_column(df, option_type)
        if not strike_col or not prem_col or not oi_col:
            return []
        out: List[OISnapshot] = []
        ts = pd.Timestamp(candle["timestamp"])
        for _, row in df.iterrows():
            try:
                strike = int(float(row[strike_col]))
                premium = float(row[prem_col])
                oi = float(row[oi_col])
            except (TypeError, ValueError):
                continue
            if strike % 100 != 0:
                continue
            if strikes_filter is not None and strike not in strikes_filter:
                continue
            if apply_premium_filter and not (PREMIUM_MIN <= premium <= PREMIUM_MAX):
                continue
            out.append(
                OISnapshot(
                    option_type=option_type,
                    strike=strike,
                    premium=premium,
                    oi=oi,
                    ts=ts,
                )
            )
        return out

    def _snapshot_for_strike(
        self, candle: dict, ctx: Any, option_type: str, strike: int
    ) -> Optional[OISnapshot]:
        rows = self._extract_snapshots(
            candle,
            ctx,
            option_type,
            {int(strike)},
            apply_premium_filter=False,
        )
        return rows[0] if rows else None

    def _capture_930_snapshot(self, candle: dict, ctx: Any):
        d = self._trade_date(candle)
        symbol = candle["symbol"]
        data = {"CE": [], "PE": []}
        open_main = [
            p
            for p in ctx.position_store.get_open_positions(underlying=symbol, strategy=self.name)
            if getattr(p, "tag", None) == "MAIN" and getattr(p, "net_qty", 0) > 0
        ]
        held = open_main[0] if open_main else None

        if held is not None:
            sid = held.structure_id
            meta = self._position_meta_by_sid.get(sid)
            held_opt = (held.instrument.option_type or "").upper()
            held_opt = "CE" if held_opt in ("CE", "CALL") else "PE"
            held_strike = int(float(held.instrument.strike))
            held_row = self._extract_snapshots(
                candle,
                ctx,
                held_opt,
                {held_strike},
                apply_premium_filter=False,
            )
            if held_row:
                data[held_opt] = held_row
            opposite = "PE" if held_opt == "CE" else "CE"
            data[opposite] = self._extract_snapshots(candle, ctx, opposite)
            if meta:
                meta.benchmark_premium = held_row[0].premium if held_row else meta.benchmark_premium
                meta.benchmark_oi = held_row[0].oi if held_row else meta.benchmark_oi
        else:
            data["CE"] = self._extract_snapshots(candle, ctx, "CE")
            data["PE"] = self._extract_snapshots(candle, ctx, "PE")

        self._benchmarks_by_day[d] = data

    def _signal_vs_benchmark(self, snap: OISnapshot, bench: OISnapshot) -> Tuple[str, float, float, float]:
        if bench.oi <= 0 or bench.premium <= 0:
            return "NONE", 0.0, 0.0, 0.0
        oi_chg_pct = ((snap.oi - bench.oi) / bench.oi) * 100.0
        prem_chg_pct = ((snap.premium - bench.premium) / bench.premium) * 100.0
        if prem_chg_pct >= PREMIUM_CHANGE_LIMIT_PCT:
            return "LATE", oi_chg_pct, prem_chg_pct, -1e9
        if oi_chg_pct > 0 and prem_chg_pct > 0:
            score = oi_chg_pct + prem_chg_pct
            return "LONG", oi_chg_pct, prem_chg_pct, score
        return "NONE", oi_chg_pct, prem_chg_pct, -1e9

    def _build_symbol_from_ctx_expiry(
        self, candle: dict, ctx: Any, strike: int, option_type: str
    ) -> Optional[Union[date, str]]:
        expiry = ctx.selected_expiry
        if expiry is None:
            return None
        if isinstance(expiry, int):
            td = self._trade_date(candle)
            return ExpiryResolver.dhan_expiry_index_to_date(td, expiry)
        return expiry

    def _entry_intent_from_snapshot(
        self,
        candle: dict,
        ctx: Any,
        snap: OISnapshot,
        bench: OISnapshot,
        structure_id: str,
    ) -> Optional[Any]:
        expiry = self._build_symbol_from_ctx_expiry(candle, ctx, snap.strike, snap.option_type)
        if expiry is None:
            return None
        trading_symbol = ExpiryResolver.build_option_symbol(
            self, candle["symbol"], expiry, snap.strike, snap.option_type
        )
        inst = ctx.instrument_store.intent_creation_details(
            trading_symbol, ctx.exchange, expiry, snap.option_type, snap.strike
        )
        if inst is None:
            return None
        strike_row = {"close": snap.premium, "strike": snap.strike}
        intent = self.map_instrument_to_intent(
            inst=inst,
            strike_row=strike_row,
            strategy=self.name,
            side="BUY",
            structure_id=structure_id,
            candle_ts=candle["timestamp"],
            tag="MAIN",
            symbol=candle["symbol"],
            action="ENTRY",
        )
        self._position_meta_by_sid[structure_id] = PositionMeta(
            symbol=candle["symbol"],
            option_type=snap.option_type,
            strike=snap.strike,
            benchmark_premium=bench.premium,
            benchmark_oi=bench.oi,
            entry_premium=snap.premium,
            entry_date=self._trade_date(candle),
            structure_id=structure_id,
        )
        return intent

    def _open_main_positions(self, ctx: Any, symbol: str) -> List[Any]:
        return [
            p
            for p in ctx.position_store.get_open_positions(underlying=symbol, strategy=self.name)
            if getattr(p, "tag", None) == "MAIN" and getattr(p, "net_qty", 0) > 0
        ]

    def _evaluate_entry_1045(self, candle: dict, ctx: Any) -> Optional[List[Any]]:
        symbol = candle["symbol"]
        d = self._trade_date(candle)
        if self._sl_blocked_day_by_symbol.get(symbol) == d:
            return None
        if getattr(ctx, "intent_store", None) and ctx.intent_store.has_pending_intent(
            strategy=self.name,
            tags=["MAIN", "MAIN_EXIT"],
            actions=["ENTRY", "EXIT"],
        ):
            return None
        if self._open_main_positions(ctx, symbol):
            return None
        bench = self._benchmarks_by_day.get(d)
        if not bench:
            return None

        candidates: List[Tuple[float, OISnapshot, OISnapshot]] = []
        for opt in ("CE", "PE"):
            snaps = self._extract_snapshots(candle, ctx, opt)
            bench_map = {(b.option_type, b.strike): b for b in bench.get(opt, [])}
            for s in snaps:
                b = bench_map.get((s.option_type, s.strike))
                if b is None:
                    continue
                signal, _, _, score = self._signal_vs_benchmark(s, b)
                if signal == "LONG":
                    candidates.append((score, s, b))
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        _, best_snap, best_bench = candidates[0]
        sid = f"{self.name}:{symbol}:{d}:L1:{best_snap.option_type}:{best_snap.strike}"
        intent = self._entry_intent_from_snapshot(candle, ctx, best_snap, best_bench, sid)
        return [intent] if intent else None

    def _current_premium(self, candle: dict, ctx: Any, pos: Any) -> Optional[float]:
        px = self.get_option_price_at_candle(
            candle,
            ctx,
            pos.instrument.strike,
            pos.instrument.option_type,
            pos.instrument.expiry,
            trading_symbol=pos.instrument.trading_symbol,
        )
        if px is None and RUN_MODE == RunMode.BACKTEST:
            try:
                return float(candle["close"])
            except (TypeError, ValueError):
                return None
        return px

    def _reason_to_exit(self, pos: Any, candle: dict, ctx: Any) -> Optional[str]:
        sid = pos.structure_id
        meta = self._position_meta_by_sid.get(sid)
        if meta is None:
            return None
        px = self._current_premium(candle, ctx, pos)
        if px is None:
            return None
        if px <= meta.entry_premium * (1.0 - STOP_LOSS_PCT):
            return "SL"
        if px >= meta.entry_premium * TARGET_MULTIPLIER:
            return "TARGET"
        if self._ist_time(candle) == EOD_REVIEW_TIME:
            d = self._trade_date(candle)
            bench = self._benchmarks_by_day.get(d, {})
            bmap = {(b.option_type, b.strike): b for b in bench.get(meta.option_type, [])}
            b = bmap.get((meta.option_type, meta.strike))
            if b is None:
                return "EOD_EXIT"
            cur_snap = self._snapshot_for_strike(candle, ctx, meta.option_type, meta.strike)
            if cur_snap is None:
                return "EOD_EXIT"
            cur = OISnapshot(
                meta.option_type,
                meta.strike,
                float(px),
                float(cur_snap.oi),
                pd.Timestamp(candle["timestamp"]),
            )
            signal, _, _, _ = self._signal_vs_benchmark(cur, b)
            if signal == "LONG":
                return None
            return "EOD_ROTATE"
        return None

    def on_candle(self, candle: dict, ctx: Any):
        t = self._ist_time(candle)
        if t == ENTRY_SNAPSHOT_TIME:
            self._capture_930_snapshot(candle, ctx)
            return None
        if t == ENTRY_EVAL_TIME:
            return self._evaluate_entry_1045(candle, ctx)
        return None

    def should_exit(self, position: Any, candle: dict, ctx: Any = None) -> bool:
        if position.tag != "MAIN":
            return False
        sid = position.structure_id
        if sid in self._pending_exit_sids:
            return False
        reason = self._reason_to_exit(position, candle, ctx)
        if reason:
            self._exit_reason_by_sid[sid] = reason
            return True
        return False

    def on_position_exit(self, position: Any, candle: dict, ctx: Any):
        sid = position.structure_id
        self._pending_exit_sids.add(sid)
        px = self._current_premium(candle, ctx, position)
        intent = self.create_order_intent(
            inst=position.instrument,
            side="SELL",
            qty=abs(position.net_qty),
            price=px,
            order_type="LIMIT",
            strategy=self.name,
            candle_ts=candle["timestamp"],
            structure_id=sid,
            tag="MAIN_EXIT",
            symbol=candle["symbol"],
            action="EXIT",
        )

        reason = self._exit_reason_by_sid.get(sid)
        if reason == "SL":
            self._sl_blocked_day_by_symbol[candle["symbol"]] = self._trade_date(candle)
            return [intent]

        if reason == "TARGET":
            if self._ist_time(candle) >= ENTRY_EVAL_TIME:
                re = self._evaluate_entry_1045(candle, ctx)
                if re:
                    self._pending_entry_by_exit_sid[sid] = PendingEntry(entry_intent=re[0])
                    return [intent]
        if reason == "EOD_ROTATE":
            re = self._evaluate_entry_1045(candle, ctx)
            if re:
                self._pending_entry_by_exit_sid[sid] = PendingEntry(entry_intent=re[0])
                return [intent]
        return [intent]

    def on_main_exit_filled(self, **kwargs: Any):
        sid = str(kwargs.get("structure_id") or "")
        if not sid:
            return []
        pending = self._pending_entry_by_exit_sid.pop(sid, None)
        if pending is None:
            return []
        return [(pending.entry_intent, {"timestamp": kwargs.get("candle_ts")})]

    def on_forced_exit(self, **kwargs: Any) -> None:
        sid = str(kwargs.get("structure_id") or "")
        if not sid:
            return
        reason = str(kwargs.get("exit_reason") or kwargs.get("execution_source") or "").upper()
        if reason == "SL":
            symbol = kwargs.get("symbol")
            ts = kwargs.get("candle_ts") or kwargs.get("timestamp")
            if symbol and ts is not None:
                d = self._trade_date({"timestamp": ts, "symbol": symbol})
                self._sl_blocked_day_by_symbol[symbol] = d
        self._pending_entry_by_exit_sid.pop(sid, None)
        self._pending_exit_sids.discard(sid)
        self._exit_reason_by_sid.pop(sid, None)

    def on_structure_exit(self, structure_id: str, **kwargs):
        self._pending_exit_sids.discard(structure_id)
        self._exit_reason_by_sid.pop(structure_id, None)
        self._pending_entry_by_exit_sid.pop(structure_id, None)
        self._position_meta_by_sid.pop(structure_id, None)
        super().on_structure_exit(structure_id=structure_id, **kwargs)
