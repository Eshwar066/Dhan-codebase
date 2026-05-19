from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd

from core.strategies.IndiaMktMixins import IST, IndiaMktMixins
from core.strategies.base import BaseStrategy
from core.utils.expiry_resolver import ExpiryResolver
from core.utils.option_chain_snapshot_log import log_option_chain_snapshot
from run.config import RUN_MODE, RunMode


ENTRY_SNAPSHOT_TIME = time(9, 30)
ENTRY_EVAL_TIME = time(10, 45)
EOD_REVIEW_TIME = time(15, 15)
REFERENCE_SNAPSHOT_TIMES = frozenset(
    {ENTRY_SNAPSHOT_TIME, ENTRY_EVAL_TIME, EOD_REVIEW_TIME}
)

PREMIUM_MIN = 170
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
    # DHAN expiry_code 0 = current month, 1 = next month when trade_date.day > this day.
    dhan_monthly_rollover_after_calendar_day = 16
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
        self._oi_snapshot_logged_slots: set[str] = set()
        self._full_chain_cache: Any = None
        self._full_chain_cache_key: Optional[tuple] = None

    def get_warmup_period(self):
        return 0

    def should_evaluate(self, candle):
        return True

    def _candle_timestamp_utc(self, candle: dict) -> pd.Timestamp:
        bt = candle.get("bucket_ts")
        if bt is not None:
            return pd.Timestamp(int(bt), unit="s", tz="UTC")
        ts = pd.Timestamp(candle["timestamp"])
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts.tz_convert("UTC")

    def _bar_tf_minutes(self) -> int:
        try:
            return max(1, int(str(self.timeframe).strip()))
        except (TypeError, ValueError):
            return 15

    def _ist_time(self, candle: dict) -> time:
        """IST time at bar *close* (bucket open + timeframe minutes)."""
        close_ist = self._candle_timestamp_utc(candle).tz_convert(IST) + pd.Timedelta(
            minutes=self._bar_tf_minutes()
        )
        return close_ist.time().replace(second=0, microsecond=0)

    def _trade_date(self, candle: dict) -> date:
        return self._candle_timestamp_utc(candle).tz_convert(IST).date()

    def _candle_ts_ist(self, candle: dict) -> pd.Timestamp:
        return self._candle_timestamp_utc(candle).tz_convert(IST)

    def _candle_close_ts_ist(self, candle: dict) -> pd.Timestamp:
        return self._candle_ts_ist(candle) + pd.Timedelta(minutes=self._bar_tf_minutes())

    def _find_strike_snapshot_params(
        self, candle: dict, ctx: Any, option_type: str
    ) -> Dict[str, Any]:
        """One CSV snapshot per slot (DHAN chain has CE + PE columns in a single response)."""
        _ = option_type
        if self._ist_time(candle) not in REFERENCE_SNAPSHOT_TIMES:
            return {}
        ts_ist = self._candle_close_ts_ist(candle)
        snapshot_date = ts_ist.strftime("%Y-%m-%d")
        snapshot_time = ts_ist.strftime("%H-%M")
        slot_key = "|".join(
            [
                str(getattr(ctx, "symbol", "") or ""),
                snapshot_date,
                snapshot_time,
            ]
        )
        if slot_key in self._oi_snapshot_logged_slots:
            return {}
        self._oi_snapshot_logged_slots.add(slot_key)
        return {
            "snapshot": True,
            "snapshot_date": snapshot_date,
            "snapshot_time": snapshot_time,
            "snapshot_target": "oi_positional_buy",
        }

    def _full_chain_cache_lookup(self, candle: dict) -> Optional[Any]:
        key = (str(candle.get("symbol") or ""), candle.get("bucket_ts"), self._trade_date(candle))
        if self._full_chain_cache_key == key and self._full_chain_cache is not None:
            return self._full_chain_cache
        return None

    def _ist_log_slot_for_candle(self, candle: dict) -> Optional[str]:
        t = self._ist_time(candle)
        if t in REFERENCE_SNAPSHOT_TIMES:
            return f"{t.hour:02d}-{t.minute:02d}"
        return None

    def _chain_from_oi_logs(
        self, candle: dict, ctx: Any, trade_date: date
    ) -> Optional[Any]:
        slot = self._ist_log_slot_for_candle(candle)
        if slot is None:
            return None
        df = self._read_oi_log_chain_df(trade_date, slot)
        if df is None:
            return None
        return {
            "symbol": candle.get("symbol"),
            "exchange": getattr(ctx, "exchange", None) or "INDEX",
            "chain": df,
            "atm_strike": None,
            "expiry": self._read_oi_log_chain_expiry(trade_date, slot),
        }

    def _fetch_full_option_chain(
        self, candle: dict, ctx: Any, *, log_snapshot: bool = False
    ) -> Any:
        """
        Single option-chain request (DHAN returns CE + PE in one DataFrame).
        Cached per symbol/bucket/trade-day for reuse within the same candle evaluation.
        """
        cached = self._full_chain_cache_lookup(candle)
        if cached is not None:
            return cached

        trade_date = self._trade_date(candle)
        log_chain = self._chain_from_oi_logs(candle, ctx, trade_date)
        if log_chain is not None:
            self._ensure_selected_expiry(candle, ctx, log_chain)
            self._full_chain_cache = log_chain
            self._full_chain_cache_key = (
                str(candle.get("symbol") or ""),
                candle.get("bucket_ts"),
                trade_date,
            )
            if log_snapshot:
                snap = self._find_strike_snapshot_params(candle, ctx, "")
                if snap:
                    try:
                        log_option_chain_snapshot(
                            log_chain,
                            ctx=ctx,
                            strategy_name=self.name,
                            api=self.api,
                            params={**snap, "snapshot_target": "oi_positional_buy"},
                        )
                    except Exception:
                        pass
            return log_chain

        strikes = self.fetch_option_chain(candle, ctx, "CE")
        if not strikes:
            return None

        params: Dict[str, Any] = {
            "exchange": ctx.exchange,
            "interval": self.timeframe,
            "expiry_code": ctx.selected_expiry,
            "instrument": "OPTIDX",
            "expiry_flag": "MONTH",
        }
        if self.api != "DHAN":
            strike_param = [str(int(float(s))) for s in strikes]
            params.update(
                {
                    "strike": strike_param,
                    "option_type": "CE",
                    "exchangeSegment": "NSE_FNO",
                    "securityId": "13",
                }
            )

        if log_snapshot:
            snap = self._find_strike_snapshot_params(candle, ctx, "")
            if snap:
                params.update(snap)

        chain = ctx.option_chain_service.get_chain(api=self.api, ctx=ctx, params=params)
        if log_snapshot and bool(params.get("snapshot", False)):
            try:
                log_option_chain_snapshot(
                    chain,
                    ctx=ctx,
                    strategy_name=self.name,
                    api=self.api,
                    params=params,
                )
            except Exception:
                pass

        if chain is not None:
            self._full_chain_cache = chain
            self._full_chain_cache_key = (
                str(candle.get("symbol") or ""),
                candle.get("bucket_ts"),
                self._trade_date(candle),
            )
        return chain

    def _take_reference_snapshots(self, candle: dict, ctx: Any) -> None:
        """Persist one combined CE+PE option-chain reference snapshot."""
        self._fetch_full_option_chain(candle, ctx, log_snapshot=True)

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
        _ = option_type
        chain = self._fetch_full_option_chain(candle, ctx, log_snapshot=False)
        return self._chain_df_from_response(chain, candle)

    def _chain_df_from_response(
        self, chain: Any, candle: dict
    ) -> Optional[pd.DataFrame]:
        df = chain.get("chain") if isinstance(chain, dict) else chain
        if not isinstance(df, pd.DataFrame) or df.empty:
            return None
        if "datetime" in df.columns:
            wall = pd.to_datetime(df["datetime"]).dt.strftime("%Y-%m-%d %H:%M")
            ts_ist = self._candle_ts_ist(candle)
            wall_c = ts_ist.strftime("%Y-%m-%d %H:%M")
            filt = df[wall == wall_c]
            if not filt.empty:
                df = filt
        return df

    def _snapshots_from_df(
        self,
        df: pd.DataFrame,
        candle: dict,
        option_type: str,
        strikes_filter: Optional[set[int]] = None,
        apply_premium_filter: bool = True,
    ) -> List[OISnapshot]:
        strike_col = self._option_chain_strike_column(df)
        prem_col = self._option_chain_premium_column(df, option_type)
        oi_col = self._oi_column(df, option_type)
        if not strike_col or not prem_col or not oi_col:
            return []
        out: List[OISnapshot] = []
        ts = self._candle_timestamp_utc(candle)
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

    def _snapshots_from_chain(
        self,
        chain: Any,
        candle: dict,
        option_type: str,
        strikes_filter: Optional[set[int]] = None,
        apply_premium_filter: bool = True,
    ) -> List[OISnapshot]:
        df = self._chain_df_from_response(chain, candle)
        if df is None:
            return []
        return self._snapshots_from_df(
            df, candle, option_type, strikes_filter, apply_premium_filter
        )

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
        return self._snapshots_from_df(
            df, candle, option_type, strikes_filter, apply_premium_filter
        )

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

    def _oi_logs_day_dir(self, trade_date: date) -> Path:
        root = Path(__file__).resolve().parents[4]
        return root / "logs" / "OIPositionalBuy" / trade_date.isoformat()

    def _benchmark_log_slot(self) -> str:
        """CSV filename token for 09:30 bar close (matches snapshot_time in logs)."""
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

    def _oi_log_csv_path(self, trade_date: date, slot: str) -> Optional[Path]:
        day_dir = self._oi_logs_day_dir(trade_date)
        if not day_dir.is_dir():
            return None
        token = slot.strip().replace(":", "-")
        candidates = [
            day_dir / f"{token}.csv",
            day_dir / f"{token.replace('-', '')}.csv",
        ]
        path = next((p for p in candidates if p.is_file()), None)
        if path is None:
            matches = sorted(day_dir.glob(f"*{token}*.csv"))
            path = matches[0] if matches else None
        return path if path is not None and path.is_file() else None

    def _read_oi_log_chain_expiry(self, trade_date: date, slot: str) -> Optional[Any]:
        path = self._oi_log_csv_path(trade_date, slot)
        if path is None:
            return None
        try:
            meta = pd.read_csv(path, usecols=lambda c: str(c) == "_chain_expiry")
        except (OSError, ValueError, pd.errors.EmptyDataError):
            return None
        if meta.empty or "_chain_expiry" not in meta.columns:
            return None
        val = meta["_chain_expiry"].iloc[0]
        return None if pd.isna(val) else val

    def _read_oi_log_chain_df(self, trade_date: date, slot: str) -> Optional[pd.DataFrame]:
        path = self._oi_log_csv_path(trade_date, slot)
        if path is None:
            return None
        try:
            df = pd.read_csv(path)
        except (OSError, ValueError, pd.errors.EmptyDataError):
            return None
        if df.empty:
            return None
        drop_cols = [c for c in df.columns if str(c).startswith("_")]
        if drop_cols:
            df = df.drop(columns=drop_cols, errors="ignore")
        if "Strike Price" in df.columns:
            df = df.drop_duplicates(subset=["Strike Price"], keep="last")
        return df if not df.empty else None

    def _dhan_monthly_expiry_index(self, trade_date: date) -> int:
        """Day 1–16 → current month (0); day 17+ → next month (1)."""
        rollover = getattr(self, "dhan_monthly_rollover_after_calendar_day", 16)
        return ExpiryResolver._derive_monthly_series(
            trade_date, calendar_rollover_day=rollover
        )

    def _ensure_selected_expiry(self, candle: dict, ctx: Any, chain: Any = None) -> None:
        if getattr(ctx, "selected_expiry", None) is not None:
            return
        trade_date = self._trade_date(candle)
        cal_exp = chain.get("expiry") if isinstance(chain, dict) else None
        if cal_exp is None:
            slot = self._ist_log_slot_for_candle(candle)
            if slot:
                cal_exp = self._read_oi_log_chain_expiry(trade_date, slot)
        if cal_exp is not None:
            ctx.selected_expiry = pd.Timestamp(cal_exp).date()
            return
        ctx.selected_expiry = self._dhan_monthly_expiry_index(trade_date)
        self.fetch_option_chain(candle, ctx, "CE")

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
        """09:30: reference snapshots (CSV) + in-memory benchmark for 10:45 entry logic."""
        d = self._trade_date(candle)
        symbol = candle["symbol"]
        data: Dict[str, List[OISnapshot]] = {"CE": [], "PE": []}
        open_main = [
            p
            for p in ctx.position_store.get_open_positions(underlying=symbol, strategy=self.name)
            if getattr(p, "tag", None) == "MAIN" and getattr(p, "net_qty", 0) > 0
        ]
        held = open_main[0] if open_main else None

        chain = self._fetch_full_option_chain(candle, ctx, log_snapshot=True)
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
        import pdb
        pdb.set_trace
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
        t = self._ist_time(candle)
        if t == ENTRY_SNAPSHOT_TIME:
            self._capture_930_benchmark(candle, ctx)
            return None
        if t == ENTRY_EVAL_TIME:
            self._take_reference_snapshots(candle, ctx)
            return self._evaluate_entry_1045(candle, ctx)
        if t == EOD_REVIEW_TIME:
            self._take_reference_snapshots(candle, ctx)
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
