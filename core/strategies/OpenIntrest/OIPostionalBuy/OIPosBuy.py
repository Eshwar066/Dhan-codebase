"""
OI Positional Buy strategy — entry/exit logic and position state.

Option-chain fetch, snapshots, and parsing: oi_option_chain.OIOptionChainMixin
Shared types / schedule: oi_types
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd

from core.strategies.IndiaMktMixins import IST, IndiaMktMixins
from core.strategies.base import BaseStrategy
from core.utils.expiry_resolver import ExpiryResolver
from run.config import RUN_MODE, RunMode

from .oi_option_chain import OIOptionChainMixin
from .oi_types import (
    ENTRY_EVAL_TIME,
    ENTRY_SNAPSHOT_TIME,
    EOD_REVIEW_TIME,
    OISnapshot,
    PendingEntry,
    PositionMeta,
)

_LOGGER = logging.getLogger(__name__)

PREMIUM_CHANGE_LIMIT_PCT = 80
TARGET_MULTIPLIER = 1.5
STOP_LOSS_PCT = 0.40


class OIPositionalBuy(OIOptionChainMixin, IndiaMktMixins, BaseStrategy):
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
    dhan_monthly_rollover_after_calendar_day = 16
    otm_strike_step = 100
    otm_strike_count = 30

    def __init__(self, *args, **kwargs):
        self._init_option_chain_state()
        super().__init__(*args, **kwargs)
        self._benchmarks_by_day: Dict[date, Dict[str, List[OISnapshot]]] = {}
        self._position_meta_by_sid: Dict[str, PositionMeta] = {}
        self._sl_blocked_day_by_symbol: Dict[str, date] = {}
        self._pending_exit_sids: set[str] = set()
        self._exit_reason_by_sid: Dict[str, str] = {}
        self._pending_entry_by_exit_sid: Dict[str, PendingEntry] = {}
        self._defer_eod_review: bool = False
        self._eod_review_candle: Optional[dict] = None

    def get_warmup_period(self):
        return 0

    def should_evaluate(self, candle):
        return True

    def _find_strike_snapshot_params(
        self, candle: dict, ctx: Any, option_type: str
    ) -> Dict[str, Any]:
        """Mixin hook; snapshots via _persist_reference_snapshot."""
        _ = (candle, ctx, option_type)
        return {}

    def _benchmark_log_slot(self) -> str:
        return ENTRY_SNAPSHOT_TIME.strftime("%H-%M")

    def _benchmark_candle_for_date(self, candle: dict, trade_date: date) -> dict:
        close_ist = pd.Timestamp(
            year=trade_date.year,
            month=trade_date.month,
            day=trade_date.day,
            hour=ENTRY_SNAPSHOT_TIME.hour,
            minute=ENTRY_SNAPSHOT_TIME.minute,
            tz=IST,
        )
        open_ist = close_ist - pd.Timedelta(minutes=self._bar_tf_minutes())
        bucket_ts = int(open_ist.tz_convert("UTC").timestamp())
        out = dict(candle)
        out["bucket_ts"] = bucket_ts
        out["timestamp"] = bucket_ts
        return out

    def _benchmark_data_from_chain_df(
        self, df: pd.DataFrame, bench_candle: dict
    ) -> Dict[str, List[OISnapshot]]:
        return {
            "CE": self._snapshots_from_df(df, bench_candle, "CE"),
            "PE": self._snapshots_from_df(df, bench_candle, "PE"),
        }

    def _load_benchmark_from_logs(
        self, candle: dict, trade_date: date
    ) -> Optional[Dict[str, List[OISnapshot]]]:
        df = self._read_oi_log_chain_df(trade_date, self._benchmark_log_slot())
        if df is None:
            return None
        bench_candle = self._benchmark_candle_for_date(candle, trade_date)
        data = self._benchmark_data_from_chain_df(df, bench_candle)
        if not data.get("CE") and not data.get("PE"):
            return None
        return data

    def _ensure_benchmark(
        self, candle: dict, ctx: Any, trade_date: date
    ) -> Optional[Dict[str, List[OISnapshot]]]:
        bench = self._benchmarks_by_day.get(trade_date)
        if bench:
            return bench
        bench = self._load_benchmark_from_logs(candle, trade_date)
        if bench:
            self._benchmarks_by_day[trade_date] = bench
        return bench

    def _capture_930_benchmark(self, candle: dict, ctx: Any) -> None:
        d = self._trade_date(candle)
        symbol = candle["symbol"]
        data: Dict[str, List[OISnapshot]] = {"CE": [], "PE": []}
        open_main = [
            p
            for p in ctx.position_store.get_open_positions(underlying=symbol, strategy=self.name)
            if getattr(p, "tag", None) == "MAIN" and getattr(p, "net_qty", 0) > 0
        ]
        held = open_main[0] if open_main else None

        self._persist_reference_snapshot(candle, ctx, ENTRY_SNAPSHOT_TIME)
        chain = self._fetch_full_option_chain(candle, ctx)
        if chain is None:
            bench = self._load_benchmark_from_logs(candle, d)
            if bench:
                self._benchmarks_by_day[d] = bench
            return

        if held is not None:
            sid = held.structure_id
            meta = self._position_meta_by_sid.get(sid)
            held_opt = (held.instrument.option_type or "").upper()
            held_opt = "CE" if held_opt in ("CE", "CALL") else "PE"
            held_strike = int(float(held.instrument.strike))
            held_row = self._snapshots_from_chain(
                chain,
                candle,
                held_opt,
                {held_strike},
                apply_premium_filter=False,
            )
            if held_row:
                data[held_opt] = held_row
            opposite = "PE" if held_opt == "CE" else "CE"
            data[opposite] = self._snapshots_from_chain(chain, candle, opposite)
            if meta:
                meta.benchmark_premium = held_row[0].premium if held_row else meta.benchmark_premium
                meta.benchmark_oi = held_row[0].oi if held_row else meta.benchmark_oi
        else:
            data["CE"] = self._snapshots_from_chain(chain, candle, "CE")
            data["PE"] = self._snapshots_from_chain(chain, candle, "PE")

        self._benchmarks_by_day[d] = data

    def _signal_vs_benchmark(
        self, snap: OISnapshot, bench: OISnapshot
    ) -> Tuple[str, float, float, float]:
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
        self._ensure_selected_expiry(candle, ctx)
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
            structure_id=f"{self.name}:{symbol}",
            tags=["MAIN", "MAIN_EXIT"],
            actions=["ENTRY", "EXIT"],
        ):
            return None
        if self._open_main_positions(ctx, symbol):
            return None
        bench = self._ensure_benchmark(candle, ctx, d)
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
            bench = self._ensure_benchmark(candle, ctx, d) or {}
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
        self._update_snapshot_retry_context(candle, ctx)
        t = self._ist_time(candle)
        if t == ENTRY_SNAPSHOT_TIME:
            self._capture_930_benchmark(candle, ctx)
            return None
        if t == ENTRY_EVAL_TIME:
            self._take_reference_snapshots(candle, ctx, ENTRY_EVAL_TIME)
            return self._evaluate_entry_1045(candle, ctx)
        if t == EOD_REVIEW_TIME:
            ok = self._take_reference_snapshots(candle, ctx, EOD_REVIEW_TIME)
            if not ok:
                self._defer_eod_review = True
                self._eod_review_candle = dict(candle)
                _LOGGER.warning(
                    "oi_positional_buy 15:15 snapshot pending; EOD exit review deferred"
                )
        return None

    def should_exit(self, position: Any, candle: dict, ctx: Any = None) -> bool:
        if position.tag != "MAIN":
            return False
        sid = position.structure_id
        if sid in self._pending_exit_sids:
            return False
        exit_candle = candle
        if self._defer_eod_review:
            trade_date = self._trade_date(candle)
            if not self._snapshot_on_disk(trade_date, EOD_REVIEW_TIME):
                return False
            exit_candle = self._eod_review_candle or candle
            self._defer_eod_review = False
            self._eod_review_candle = None
            _LOGGER.info("oi_positional_buy running deferred 15:15 EOD exit review")
        reason = self._reason_to_exit(position, exit_candle, ctx)
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
