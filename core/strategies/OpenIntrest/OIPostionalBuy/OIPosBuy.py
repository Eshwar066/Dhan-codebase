"""
OI Positional Buy — rules in readme.md

09:30  benchmark chain
10:45 / 15:15  snapshot + OI review vs 09:30 + entry if flat
Intraday  TP 1.5x via MAIN_TARGET SL-M; SL 40% via MAIN_SL SL-M — armed after MAIN fill (OCO)
"""

from __future__ import annotations

import logging
from datetime import date, time
from types import SimpleNamespace
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

# --- readme thresholds ---
PREMIUM_BAND = (170, 220)
MAX_PREM_RISE_VS_930_PCT = 80  # entry only if premium not up >=80% vs 09:30
TARGET_MULT = 1.5  # 1.5x entry = +50%
STOP_LOSS_FRAC = 0.40
SLOT_TIMES = (ENTRY_EVAL_TIME, EOD_REVIEW_TIME)

# OI vs 09:30 (oi_change%, prem_change%)
BULLISH = frozenset({"LONG_BUILDUP", "SHORT_COVERING"})
BEARISH = frozenset({"SHORT_BUILDUP", "LONG_UNWINDING"})


class OIPositionalBuy(OIOptionChainMixin, IndiaMktMixins, BaseStrategy):
    name = "OIPositionalBuy"
    timeframe = "15"
    required_context = ["option_chain"]
    api = "DHAN"
    expiryType = "MONTHLY"
    dhan_monthly_rollover_after_calendar_day = 15  # after 15th → next month series
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
        self._reentry_near_premium: Dict[str, float] = {}
        self._defer_eod_review = False
        self._eod_review_candle: Optional[dict] = None

    def get_warmup_period(self):
        return 0

    def should_evaluate(self, candle):
        return True

    def _find_strike_snapshot_params(self, candle, ctx, option_type):
        return {}

    def fetch_option_chain(self, candle, ctx, option_type):
        """
        OI positional monthly rule must be calendar-date based, not DHAN index based:
        till rollover day use current month expiry, after rollover use next month expiry.
        """
        if self.api == "DHAN" and str(getattr(self, "expiryType", "")).upper() == "MONTHLY":
            trade_date = self._trade_date(candle)
            ctx.selected_expiry = self._dhan_monthly_target_expiry_date(trade_date)
            spot = candle["close"]
            step = getattr(self, "otm_strike_step", 500)
            count = int(getattr(self, "otm_strike_count", 4))
            otm_strikes = ExpiryResolver.get_otm_strikes(
                self, spot=spot, option_type=option_type, step=step, count=count
            )
            ctx.otm_strikes = otm_strikes
            return otm_strikes
        return super().fetch_option_chain(candle, ctx, option_type)

    # ------------------------------------------------------------------
    # OI pattern vs 09:30 benchmark
    # ------------------------------------------------------------------

    @staticmethod
    def _oi_pattern(snap: OISnapshot, bench: OISnapshot) -> Tuple[str, float, float, float]:
        if bench.oi <= 0 or bench.premium <= 0:
            return "NONE", 0.0, 0.0, 0.0
        oi_pct = ((snap.oi - bench.oi) / bench.oi) * 100.0
        pr_pct = ((snap.premium - bench.premium) / bench.premium) * 100.0
        if pr_pct >= MAX_PREM_RISE_VS_930_PCT:
            return "LATE", oi_pct, pr_pct, -1e9
        if oi_pct > 0 and pr_pct > 0:
            return "LONG_BUILDUP", oi_pct, pr_pct, oi_pct + pr_pct
        if oi_pct < 0 and pr_pct > 0:
            return "SHORT_COVERING", oi_pct, pr_pct, oi_pct + pr_pct
        if oi_pct > 0 and pr_pct < 0:
            return "SHORT_BUILDUP", oi_pct, pr_pct, -1e9
        if oi_pct < 0 and pr_pct < 0:
            return "LONG_UNWINDING", oi_pct, pr_pct, -1e9
        return "NONE", oi_pct, pr_pct, -1e9

    def _held_snap_vs_930(
        self, candle: dict, ctx: Any, meta: PositionMeta
    ) -> Tuple[str, float, float]:
        d = self._trade_date(candle)
        bench = self._ensure_benchmark(candle, ctx, d) or {}
        bmap = {(b.option_type, b.strike): b for b in bench.get(meta.option_type, [])}
        b = bmap.get((meta.option_type, meta.strike))
        if b is None:
            return "NONE", 0.0, 0.0
        px = self._position_premium(candle, ctx, meta)
        row = self._snapshot_for_strike(candle, ctx, meta.option_type, meta.strike)
        oi = float(row.oi) if row else float(b.oi)
        if px is None:
            return "NONE", 0.0, 0.0
        cur = OISnapshot(
            meta.option_type, meta.strike, float(px), oi, pd.Timestamp(candle["timestamp"])
        )
        pat, oi_pct, pr_pct, _ = self._oi_pattern(cur, b)
        return pat, oi_pct, pr_pct

    # ------------------------------------------------------------------
    # 09:30 benchmark
    # ------------------------------------------------------------------

    def _capture_930_benchmark(self, candle: dict, ctx: Any) -> None:
        d = self._trade_date(candle)
        symbol = candle["symbol"]
        self._persist_reference_snapshot(candle, ctx, ENTRY_SNAPSHOT_TIME)
        chain = self._fetch_full_option_chain(candle, ctx)
        if chain is None:
            bench = self._load_benchmark_from_logs(candle, d)
            if bench:
                self._benchmarks_by_day[d] = bench
            return
        data = {
            "CE": self._snapshots_from_chain(chain, candle, "CE"),
            "PE": self._snapshots_from_chain(chain, candle, "PE"),
        }
        self._benchmarks_by_day[d] = data
        _LOGGER.info(
            "oi_pos 09:30 benchmark sym=%s CE=%s PE=%s",
            symbol,
            len(data["CE"]),
            len(data["PE"]),
        )

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

    def _load_benchmark_from_logs(
        self, candle: dict, trade_date: date
    ) -> Optional[Dict[str, List[OISnapshot]]]:
        df = self._read_oi_log_chain_df(trade_date, self._benchmark_log_slot())
        if df is None:
            return None
        bench_candle = self._benchmark_candle_for_date(candle, trade_date)
        data = {
            "CE": self._snapshots_from_df(df, bench_candle, "CE"),
            "PE": self._snapshots_from_df(df, bench_candle, "PE"),
        }
        if not data.get("CE") and not data.get("PE"):
            return None
        return data

    def _ensure_benchmark(
        self, candle: dict, ctx: Any, trade_date: date
    ) -> Optional[Dict[str, List[OISnapshot]]]:
        if trade_date in self._benchmarks_by_day:
            return self._benchmarks_by_day[trade_date]
        bench = self._load_benchmark_from_logs(candle, trade_date)
        if bench:
            self._benchmarks_by_day[trade_date] = bench
        return bench

    # ------------------------------------------------------------------
    # Entry (10:45 / 15:15 when flat)
    # ------------------------------------------------------------------

    def _open_main(self, ctx: Any, symbol: str) -> List[Any]:
        return [
            p
            for p in ctx.position_store.get_open_positions(underlying=symbol, strategy=self.name)
            if getattr(p, "tag", None) == "MAIN" and getattr(p, "net_qty", 0) > 0
        ]

    def _try_entry(
        self, candle: dict, ctx: Any, *, skip_open_check: bool = False
    ) -> Optional[List[Any]]:
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
        if not skip_open_check and self._open_main(ctx, symbol):
            return None
        bench = self._ensure_benchmark(candle, ctx, d)
        if not bench:
            _LOGGER.warning("oi_pos entry skipped: no 09:30 benchmark sym=%s", symbol)
            return None

        picks: List[Tuple[float, float, OISnapshot, OISnapshot]] = []
        for opt in ("CE", "PE"):
            bmap = {(b.option_type, b.strike): b for b in bench.get(opt, [])}
            for s in self._extract_snapshots(candle, ctx, opt):
                b = bmap.get((s.option_type, s.strike))
                if b is None:
                    continue
                pat, oi_pct, pr_pct, score = self._oi_pattern(s, b)
                if pat not in BULLISH:
                    continue
                target_prem = self._reentry_near_premium.get(symbol)
                near_key = abs(s.premium - target_prem) if target_prem is not None else 0.0
                picks.append((near_key, -score, s, b))
                _LOGGER.debug(
                    "oi_pos entry cand %s %s pat=%s oi=%.1f pr=%.1f prem=%.1f",
                    opt,
                    s.strike,
                    pat,
                    oi_pct,
                    pr_pct,
                    s.premium,
                )

        if not picks:
            return None
        picks.sort(key=lambda x: (x[0], x[1]))
        _, _, best, b0 = picks[0]
        self._reentry_near_premium.pop(symbol, None)
        sid = f"{self.name}:{symbol}:{d}:L1:{best.option_type}:{best.strike}"
        intent = self._make_entry_intent(candle, ctx, best, b0, sid)
        if intent:
            _LOGGER.info(
                "oi_pos ENTRY sym=%s %s %s prem=%.1f vs930=%.1f",
                symbol,
                best.option_type,
                best.strike,
                best.premium,
                b0.premium,
            )
        return [intent] if intent else None

    def _make_entry_intent(
        self,
        candle: dict,
        ctx: Any,
        snap: OISnapshot,
        bench: OISnapshot,
        structure_id: str,
    ) -> Optional[Any]:
        self._ensure_selected_expiry(candle, ctx)
        expiry = ctx.selected_expiry
        if expiry is None:
            return None
        if isinstance(expiry, int):
            expiry = ExpiryResolver.dhan_expiry_index_to_date(self._trade_date(candle), expiry)
        trading_symbol = ExpiryResolver.build_option_symbol(
            self, candle["symbol"], expiry, snap.strike, snap.option_type
        )
        inst = ctx.instrument_store.intent_creation_details(
            trading_symbol, ctx.exchange, expiry, snap.option_type, snap.strike
        )
        if inst is None:
            return None
        intent = self.map_instrument_to_intent(
            inst=inst,
            strike_row={"close": snap.premium, "strike": snap.strike},
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

    def _build_main_sl_intent(
        self, entry_ref: Any, trigger_price: float, candle_ts: Any, symbol: str
    ) -> Any:
        """Long option: SELL stop when premium falls to trigger (40% below entry)."""
        return self.create_order_intent(
            inst=entry_ref.instrument,
            side="SELL",
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

    def _build_main_target_intent(
        self, entry_ref: Any, trigger_price: float, candle_ts: Any, symbol: str
    ) -> Any:
        """Long option: SELL when premium rises to target (1.5x entry)."""
        return self.create_order_intent(
            inst=entry_ref.instrument,
            side="SELL",
            qty=entry_ref.qty,
            price=float(trigger_price),
            order_type="SL-M",
            strategy=self.name,
            candle_ts=candle_ts,
            structure_id=entry_ref.structure_id,
            tag="MAIN_TARGET",
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
        price: Any = None,
        metadata_extras: Any = None,
        **kw: Any,
    ) -> List[Any]:
        """After MAIN BUY fill, arm SL-M (40% down) and TARGET SL-M (1.5x entry)."""
        del ctx, metadata_extras
        if not structure_id or not intent_id:
            return []
        meta = self._position_meta_by_sid.get(str(structure_id))
        if meta is None:
            return []
        entry_px = float(price if price is not None else meta.entry_premium)
        sl_trigger = float(entry_px * (1.0 - STOP_LOSS_FRAC))
        target_trigger = float(entry_px * TARGET_MULT)
        ref = SimpleNamespace(
            instrument=instrument,
            structure_id=str(structure_id),
            intent_id=intent_id,
            qty=self._normalize_order_qty(instrument, kw.get("qty")),
        )
        _LOGGER.info(
            "oi_pos bracket armed sid=%s entry=%.2f SL=%.2f TARGET=%.2f",
            structure_id,
            entry_px,
            sl_trigger,
            target_trigger,
        )
        return [
            self._build_main_sl_intent(ref, sl_trigger, candle_ts, meta.symbol),
            self._build_main_target_intent(ref, target_trigger, candle_ts, meta.symbol),
        ]

    # ------------------------------------------------------------------
    # Exits
    # ------------------------------------------------------------------

    def _position_premium(self, candle: dict, ctx: Any, pos_or_meta: Any) -> Optional[float]:
        if isinstance(pos_or_meta, PositionMeta):
            strike, opt, expiry, tsym = (
                pos_or_meta.strike,
                pos_or_meta.option_type,
                None,
                None,
            )
        else:
            inst = pos_or_meta.instrument
            strike, opt, expiry, tsym = (
                inst.strike,
                inst.option_type,
                inst.expiry,
                inst.trading_symbol,
            )
        px = self.get_option_price_at_candle(
            candle, ctx, strike, opt, expiry, trading_symbol=tsym
        )
        if px is None and RUN_MODE == RunMode.BACKTEST:
            try:
                return float(candle["close"])
            except (TypeError, ValueError):
                return None
        return px

    def _reason_to_exit(self, pos: Any, candle: dict, ctx: Any) -> Optional[str]:
        meta = self._position_meta_by_sid.get(pos.structure_id)
        if meta is None:
            return None
        px = self._position_premium(candle, ctx, pos)
        if px is None:
            return None
        # SL / TARGET: resting MAIN_SL + MAIN_TARGET (on_main_entry_filled); OI slot review only here.

        t = self._ist_time(candle)
        if t in SLOT_TIMES:
            pat, oi_pct, pr_pct = self._held_snap_vs_930(candle, ctx, meta)
            _LOGGER.info(
                "oi_pos slot review %s sid=%s pat=%s oi=%.1f pr=%.1f px=%.1f",
                t.strftime("%H:%M"),
                pos.structure_id,
                pat,
                oi_pct,
                pr_pct,
                px,
            )
            if pat in BEARISH:
                return "OI_EXIT"
            if pat in BULLISH:
                return None
            return "OI_EXIT"
        return None

    # ------------------------------------------------------------------
    # Engine hooks
    # ------------------------------------------------------------------

    def on_candle(self, candle: dict, ctx: Any):
        self._update_snapshot_retry_context(candle, ctx)
        t = self._ist_time(candle)

        if t == ENTRY_SNAPSHOT_TIME:
            self._capture_930_benchmark(candle, ctx)
            return None

        if t in SLOT_TIMES:
            self._take_reference_snapshots(candle, ctx, t)
            if t == EOD_REVIEW_TIME and not self._snapshot_on_disk(
                self._trade_date(candle), EOD_REVIEW_TIME
            ):
                self._defer_eod_review = True
                self._eod_review_candle = dict(candle)
                _LOGGER.warning("oi_pos 15:15 snapshot pending; EOD review deferred")
            return self._try_entry(candle, ctx)

        return None

    def should_exit(self, position: Any, candle: dict, ctx: Any = None) -> bool:
        if position.tag != "MAIN" or position.structure_id in self._pending_exit_sids:
            return False
        exit_candle = candle
        if self._defer_eod_review:
            td = self._trade_date(candle)
            if not self._snapshot_on_disk(td, EOD_REVIEW_TIME):
                return False
            exit_candle = self._eod_review_candle or candle
            self._defer_eod_review = False
            self._eod_review_candle = None
            _LOGGER.info("oi_pos deferred 15:15 OI review")
        reason = self._reason_to_exit(position, exit_candle, ctx)
        if reason:
            self._exit_reason_by_sid[position.structure_id] = reason
            return True
        return False

    def on_position_exit(self, position: Any, candle: dict, ctx: Any):
        sid = position.structure_id
        self._pending_exit_sids.add(sid)
        px = self._position_premium(candle, ctx, position)
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
        reason = self._exit_reason_by_sid.get(sid, "")
        symbol = candle["symbol"]

        if reason == "OI_EXIT" and self._ist_time(candle) in SLOT_TIMES:
            re = self._try_entry(candle, ctx)
            if re:
                self._pending_entry_by_exit_sid[sid] = PendingEntry(re[0])

        return [intent]

    def _block_sl_reentry(self, symbol: str, candle_ts: Any) -> None:
        if not symbol or candle_ts is None:
            return
        self._sl_blocked_day_by_symbol[symbol] = self._trade_date(
            {"timestamp": candle_ts, "symbol": symbol}
        )
        _LOGGER.info("oi_pos SL exit sym=%s — no re-entry today", symbol)

    def on_main_exit_filled(self, **kwargs: Any):
        sid = str(kwargs.get("structure_id") or "")
        tag = str(kwargs.get("tag") or "").upper()
        if tag == "MAIN_SL":
            meta = self._position_meta_by_sid.get(sid)
            sym = meta.symbol if meta else str(kwargs.get("symbol") or "")
            self._block_sl_reentry(sym, kwargs.get("candle_ts"))
            self._pending_exit_sids.discard(sid)
            self._exit_reason_by_sid.pop(sid, None)
            self._pending_entry_by_exit_sid.pop(sid, None)
            return []

        if tag == "MAIN_TARGET":
            meta = self._position_meta_by_sid.get(sid)
            sym = meta.symbol if meta else str(kwargs.get("symbol") or "")
            self._pending_exit_sids.discard(sid)
            self._exit_reason_by_sid.pop(sid, None)
            if meta is None:
                return []
            self._reentry_near_premium[sym] = meta.entry_premium
            candle = {"symbol": sym, "timestamp": kwargs.get("candle_ts")}
            ctx_stub = kwargs.get("ctx")
            if ctx_stub is None:
                return []
            re = self._try_entry(candle, ctx_stub, skip_open_check=True)
            if not re:
                return []
            _LOGGER.info(
                "oi_pos TARGET rotate sym=%s near prem=%.1f",
                sym,
                meta.entry_premium,
            )
            return [(re[0], candle)]

        pending = self._pending_entry_by_exit_sid.pop(sid, None)
        return (
            [(pending.entry_intent, {"timestamp": kwargs.get("candle_ts")})]
            if pending
            else []
        )

    def on_forced_exit(self, **kwargs: Any) -> None:
        sid = str(kwargs.get("structure_id") or "")
        if not sid:
            return
        tag = str(kwargs.get("tag") or "").upper()
        reason = str(kwargs.get("exit_reason") or kwargs.get("execution_source") or "").upper()
        if tag in ("MAIN_SL", "MAIN_TARGET") or reason in ("SL", "TARGET"):
            meta = self._position_meta_by_sid.get(sid)
            sym = meta.symbol if meta else str(kwargs.get("symbol") or "")
            if tag == "MAIN_SL" or reason == "SL":
                self._block_sl_reentry(sym, kwargs.get("candle_ts") or kwargs.get("timestamp"))
        self._pending_entry_by_exit_sid.pop(sid, None)
        self._pending_exit_sids.discard(sid)
        self._exit_reason_by_sid.pop(sid, None)

    def on_structure_exit(self, structure_id: str, **kwargs):
        self._pending_exit_sids.discard(structure_id)
        self._exit_reason_by_sid.pop(structure_id, None)
        self._pending_entry_by_exit_sid.pop(structure_id, None)
        self._position_meta_by_sid.pop(structure_id, None)
        super().on_structure_exit(structure_id=structure_id, **kwargs)
