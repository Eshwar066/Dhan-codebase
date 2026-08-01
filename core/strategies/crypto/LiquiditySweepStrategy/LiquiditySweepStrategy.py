"""
Liquidity sweep strategy shell — hosts multiple sub-strategies with shared execution.

Sub-strategies
- ``GauthamLiquiditySweep``: 4H liquidity zones swept on 1m + two reversal candles
  (see ``gautham_liquidity_sweep.py``, ``four_hour_liquidity.py``).

Later sub-strategies can be registered in ``_SUBSTRATEGIES`` with their own entry/exit rules.
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import pandas as pd

from core.strategies.base import BaseStrategy
from core.strategies.IndiaMktMixins import IndiaMktMixins
from core.strategies.market_structure_mixin import MarketStructureMixin
from core.strategies.crypto.LiquiditySweepStrategy.four_hour_liquidity import (
    FourHourLiquidityBook,
)
from core.strategies.crypto.LiquiditySweepStrategy.gautham_liquidity_sweep import (
    GauthamEntrySignal,
    GauthamLiquiditySweep,
)
from core.utils.structure import MarketStructureConfig
from core.utils import indicator_history as ind_hist

if TYPE_CHECKING:
    from core.models.strategy_context import StrategyContext

logger = logging.getLogger(__name__)

META_KEY = "liquidity_sweep"
PARTIAL_BOOK_FRAC = 0.50
DEFAULT_ORDER_QTY = 1
_4H_TF_ALIASES = frozenset({"4h", "4", "240"})
_4H_BAR_SECONDS = 4 * 60 * 60
# Entry on 1m; 4H zones from logs/indicators/{SYMBOL}/4h/indicator_history.jsonl
INDICATOR_HISTORY_ENTRY_TF = "1"
INDICATOR_HISTORY_ZONE_TF = "4h"


@dataclass
class _LegMeta:
    symbol: str
    side: str
    entry_price: float
    stop_price: float
    target_price: float
    risk: float
    substrategy: str
    partial_booked: bool = False
    trail_stop: Optional[float] = None
    zone_price: Optional[float] = None
    zone_side: Optional[str] = None
    zone_source: Optional[str] = None
    zone_bar_key: Optional[str] = None
    sweep_bar_key: Optional[str] = None


class LiquiditySweepStrategy(MarketStructureMixin, IndiaMktMixins, BaseStrategy):
    """
    Delta crypto futures — liquidity sweep framework.

    Entry TF ``1`` (1m); liquidity zones from closed ``4h`` bars::

        logs/indicators/{SYMBOL}/1/indicator_history.jsonl   (created once subscribed)
        logs/indicators/{SYMBOL}/4h/indicator_history.jsonl

    Live appends closed bars to those files; 4H zones sync as-of each 1m bar for backtest.
    """

    name = "LiquiditySweepStrategy"
    underlying_symbols = ["BTCUSD"]
    timeframe = INDICATOR_HISTORY_ENTRY_TF
    extra_timeframes = [INDICATOR_HISTORY_ZONE_TF]
    required_context = ["instrument_store"]
    api = "DELTA"
    market_structure_enabled = True
    bracket_leg_tags = ["MAIN_SL", "MAIN_TARGET"]

    enabled_substrategies: List[str] = ["GauthamLiquiditySweep"]
    # high zone sweep → SHORT; low zone sweep → LONG (live + backtest)
    enable_high_entries: bool = True
    enable_low_entries: bool = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._meta_by_structure_id: Dict[str, _LegMeta] = {}
        self._evaluated_bar_keys: set[str] = set()
        self._sl_recorded_structure_ids: set[str] = set()
        # Persist off until live attach — backtest must not rewrite active.json.
        self._zones = FourHourLiquidityBook(persist=False)
        self._zones.set_persist_source("live")
        self._zones_hydrated: set[str] = set()
        self._4h_hist_rows: Dict[str, List[dict]] = {}
        self._4h_applied_count: Dict[str, int] = {}
        # Do NOT seed from liquidity_zones_active.json here.
        # That file is an end-state snapshot; its ``consumed`` set hides levels
        # that were still active mid-window. Zones are rebuilt chronologically
        # via ``_ensure_zones_as_of`` from 4h indicator history (backtest + live).
        self._load_entry_side_flags()
        self._gautham = GauthamLiquiditySweep(
            zones=self._zones,
            enable_high_entries=self.enable_high_entries,
            enable_low_entries=self.enable_low_entries,
        )
        self._substrategies: Dict[str, Any] = {
            "GauthamLiquiditySweep": self._gautham,
        }

    def configure_run_mode(self, run_mode: Any) -> None:
        """Engine factory hook: enable zone disk persist for live/paper only."""
        mode = getattr(run_mode, "value", None) or str(run_mode or "")
        mode_u = str(mode).strip().upper()
        if mode_u in ("LIVE", "PAPER"):
            self._zones.persist = True
            self._zones.set_persist_source("live")
        else:
            self._zones.persist = False
            self._zones.set_persist_source("backtest")

    def _load_entry_side_flags(self) -> None:
        """Optional overrides from strategy.yaml ``params``."""
        yaml_path = Path(__file__).resolve().parent / "strategy.yaml"
        if not yaml_path.is_file():
            return
        try:
            import yaml
        except ImportError:
            return
        try:
            raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            logger.warning(
                "LiquiditySweepStrategy: could not read strategy.yaml params: %s",
                exc,
            )
            return
        params = raw.get("params") or {}
        if "enable_high_entries" in params:
            self.enable_high_entries = bool(params["enable_high_entries"])
        if "enable_low_entries" in params:
            self.enable_low_entries = bool(params["enable_low_entries"])
        logger.info(
            "LiquiditySweepStrategy entry sides high=%s low=%s",
            self.enable_high_entries,
            self.enable_low_entries,
        )

    def _entry_side_allowed(self, side: str) -> bool:
        s = str(side or "").upper()
        if s == "SHORT":
            return bool(self.enable_high_entries)
        if s == "LONG":
            return bool(self.enable_low_entries)
        return False

    def _entry_order_qty(self, inst) -> int:
        engine_lots = getattr(self, "order_qty_lots", None)
        if engine_lots is not None:
            return max(1, int(engine_lots))
        return max(1, int(DEFAULT_ORDER_QTY))

    def market_structure_config(self) -> MarketStructureConfig:
        return MarketStructureConfig(
            swing_left=2,
            swing_right=2,
            include_fvg=False,
            include_order_blocks=False,
            include_bos_choch=False,
            include_rsi_divergence=False,
        )

    def prepare_indicators(self, df: Any) -> Any:
        from core.utils.structure.liquidity import add_liquidity_sweeps

        df = super().prepare_indicators(df)
        return add_liquidity_sweeps(df)

    def persisted_indicator_keys(self) -> List[str]:
        from core.utils.structure.liquidity import LIQUIDITY_COLS

        keys = list(super().persisted_indicator_keys() or [])
        for col in LIQUIDITY_COLS:
            if col not in keys:
                keys.append(col)
        return keys

    def get_warmup_period(self) -> int:
        # ~1 day of 1m bars for structure / swing context
        return max(50, 1440)

    def get_structure_lookback(self) -> int:
        return max(400, self.get_warmup_period() + 50)

    def _strategy_meta(self, meta: _LegMeta) -> dict:
        return {
            META_KEY: {
                "symbol": meta.symbol,
                "side": meta.side,
                "entry_price": meta.entry_price,
                "stop_price": meta.stop_price,
                "target_price": meta.target_price,
                "risk": meta.risk,
                "substrategy": meta.substrategy,
                "partial_booked": meta.partial_booked,
                "trail_stop": meta.trail_stop,
                "zone_price": meta.zone_price,
                "zone_side": meta.zone_side,
                "zone_source": meta.zone_source,
                "zone_bar_key": meta.zone_bar_key,
                "sweep_bar_key": meta.sweep_bar_key,
            }
        }

    def _restore_meta(self, structure_id: str, raw: dict) -> bool:
        if structure_id in self._meta_by_structure_id:
            return True
        try:
            meta = _LegMeta(
                symbol=str(raw["symbol"]),
                side=str(raw["side"]).upper(),
                entry_price=float(raw["entry_price"]),
                stop_price=float(raw["stop_price"]),
                target_price=float(raw["target_price"]),
                risk=float(raw["risk"]),
                substrategy=str(raw.get("substrategy") or "GauthamLiquiditySweep"),
                partial_booked=bool(raw.get("partial_booked", False)),
                trail_stop=(
                    float(raw["trail_stop"])
                    if raw.get("trail_stop") is not None
                    else None
                ),
                zone_price=(
                    float(raw["zone_price"])
                    if raw.get("zone_price") is not None
                    else None
                ),
                zone_side=(
                    str(raw["zone_side"]) if raw.get("zone_side") is not None else None
                ),
                zone_source=(
                    str(raw["zone_source"])
                    if raw.get("zone_source") is not None
                    else None
                ),
                zone_bar_key=(
                    str(raw["zone_bar_key"])
                    if raw.get("zone_bar_key") is not None
                    else None
                ),
                sweep_bar_key=(
                    str(raw["sweep_bar_key"])
                    if raw.get("sweep_bar_key") is not None
                    else None
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
        *,
        fill_price: Any = None,
    ) -> None:
        if structure_id in self._meta_by_structure_id:
            return
        if isinstance(metadata_extras, dict):
            raw = metadata_extras.get(META_KEY)
            if isinstance(raw, dict):
                self._restore_meta(structure_id, raw)
        if structure_id in self._meta_by_structure_id:
            return
        ist = getattr(ctx, "intent_store", None)
        if ist is not None and intent_id and callable(getattr(ist, "get", None)):
            rec = ist.get(intent_id)
            if rec:
                sm = (rec.get("payload") or {}).get("strategy_meta") or {}
                raw = sm.get(META_KEY)
                if isinstance(raw, dict):
                    self._restore_meta(structure_id, raw)

    def _build_structure_id(self, symbol: str, side: str, substrategy: str) -> str:
        return f"{self.name}:{substrategy}:{symbol}:{side}:{uuid.uuid4().hex[:8]}"

    def _normalize_qty(self, total: int) -> tuple[int, int]:
        total = max(1, int(total))
        book = max(1, int(math.floor(total * PARTIAL_BOOK_FRAC)))
        if book >= total:
            book = max(1, total - 1) if total > 1 else total
        trail = total - book
        if trail <= 0 and total > 1:
            book = total // 2 or 1
            trail = total - book
        return book, max(trail, 0)

    @staticmethod
    def _candle_timeframe(candle: dict) -> str:
        return str(candle.get("timeframe") or "").strip()

    @classmethod
    def _is_4h_candle(cls, candle: dict) -> bool:
        return cls._candle_timeframe(candle).lower() in _4H_TF_ALIASES

    @staticmethod
    def _as_utc(ts: Any) -> Optional[pd.Timestamp]:
        if ts is None:
            return None
        try:
            t = pd.to_datetime(ts, utc=True)
        except (TypeError, ValueError):
            return None
        if pd.isna(t):
            return None
        return t

    def _load_4h_history_rows(self, symbol: str) -> List[dict]:
        """Load OHLC from logs/indicators/{SYMBOL}/4h/indicator_history.jsonl."""
        sym = str(symbol or "").strip().upper()
        cached = self._4h_hist_rows.get(sym)
        if cached is not None:
            return cached
        try:
            rows = ind_hist.load_indicator_history_rows(
                sym, INDICATOR_HISTORY_ZONE_TF, max_rows=0
            )
        except Exception as exc:
            logger.warning(
                "LiquiditySweepStrategy 4H history load failed %s path=%s: %s",
                sym,
                ind_hist.indicator_history_path(sym, INDICATOR_HISTORY_ZONE_TF),
                exc,
            )
            rows = []
        self._4h_hist_rows[sym] = rows
        return rows

    def _row_to_4h_candle(self, symbol: str, row: dict) -> dict:
        ts = row.get("timestamp")
        ist_key = None
        if ts is not None:
            try:
                ist_key = (
                    pd.to_datetime(ts, utc=True)
                    .tz_convert(ind_hist.IST)
                    .strftime("%Y-%m-%d %H:%M")
                )
            except (TypeError, ValueError):
                ist_key = None
        return {
            "symbol": symbol,
            "open": row.get("open"),
            "high": row.get("high"),
            "low": row.get("low"),
            "close": row.get("close"),
            "timestamp": ts,
            "candle_timestamp_ist": ist_key,
            "timeframe": INDICATOR_HISTORY_ZONE_TF,
        }

    def _ensure_zones_as_of(self, symbol: str, as_of: Any) -> None:
        """
        Apply closed 4H bars from indicator history up to ``as_of``.

        Used for backtest (engine only replays primary TF) and live cold-start.
        Live closed 4H bars also call ``on_4h_close`` directly (idempotent).
        """
        sym = str(symbol or "").strip().upper()
        as_of_ts = self._as_utc(as_of)
        if not sym or as_of_ts is None:
            return

        rows = self._load_4h_history_rows(sym)
        applied = int(self._4h_applied_count.get(sym, 0))
        with self._zones.suspend_persist():
            while applied < len(rows):
                row = rows[applied]
                open_ts = self._as_utc(row.get("timestamp"))
                if open_ts is None:
                    applied += 1
                    continue
                close_at = open_ts + pd.Timedelta(seconds=_4H_BAR_SECONDS)
                if close_at > as_of_ts:
                    break
                self._zones.on_4h_close(sym, self._row_to_4h_candle(sym, row))
                applied += 1
        self._4h_applied_count[sym] = applied
        # Do not rewrite liquidity_zones_active.json on every 1m/history catch-up.
        # Persist only on real 4H closes / rebuild / mark_consumed.
        if applied > 0:
            self._zones_hydrated.add(sym)

    def should_evaluate(self, candle: dict) -> bool:
        if candle.get("close") is None:
            return False
        bucket = candle.get("bucket_ts")
        if bucket is None:
            return False
        try:
            b = int(bucket)
        except (TypeError, ValueError):
            return False
        sym = str(candle.get("symbol") or "").strip().upper()
        tf = self._candle_timeframe(candle) or self.timeframe
        key = f"{sym}|{tf}|{b}"
        if key in self._evaluated_bar_keys:
            return False
        self._evaluated_bar_keys.add(key)
        return True

    def _collect_entry_signals(
        self, candle: dict, ctx: "StrategyContext"
    ) -> List[GauthamEntrySignal]:
        out: List[GauthamEntrySignal] = []
        for sub_name in self.enabled_substrategies:
            sub = self._substrategies.get(sub_name)
            if sub is None:
                continue
            if sub_name == "GauthamLiquiditySweep":
                sig = sub.evaluate(candle, ctx, strategy_name=self.name)
                if sig is not None:
                    out.append(sig)
        return out

    def on_candle(
        self, candle: dict, ctx: "StrategyContext"
    ) -> Optional[List[Any]]:
        symbol = str(candle.get("symbol") or "").strip().upper()
        if not symbol:
            return None

        # Closed 4H bars only update liquidity zones — never enter on HTF.
        if self._is_4h_candle(candle):
            self._zones.on_4h_close(symbol, candle)
            self._zones_hydrated.add(symbol)
            return None

        # Backtest + live: zones from logs/indicators/{SYM}/4h/indicator_history.jsonl
        self._ensure_zones_as_of(symbol, candle.get("timestamp"))
        if symbol not in self._zones_hydrated:
            path = ind_hist.indicator_history_path(symbol, INDICATOR_HISTORY_ZONE_TF)
            logger.info(
                "LiquiditySweepStrategy waiting for 4H history %s path=%s",
                symbol,
                path,
            )

        signals = self._collect_entry_signals(candle, ctx)
        if not signals:
            return None

        sig = signals[0]
        if not self._entry_side_allowed(sig.side):
            logger.debug(
                "LiquiditySweepStrategy skip %s %s (high=%s low=%s)",
                symbol,
                sig.side,
                self.enable_high_entries,
                self.enable_low_entries,
            )
            return None
        exchange = str(candle.get("exchange") or "DELTA")
        inst = ctx.instrument_store.futures_intent_creation_details(
            symbol, exchange, expiry=None
        )
        if inst is None:
            return None

        for p in ctx.position_store.get_open_positions(
            underlying=symbol, strategy=self.name
        ) or []:
            if p and int(getattr(p, "net_qty", 0) or 0) != 0:
                return None

        structure_id = self._build_structure_id(symbol, sig.side, sig.substrategy)
        order_side = "BUY" if sig.side == "LONG" else "SELL"
        meta = _LegMeta(
            symbol=symbol,
            side=sig.side,
            entry_price=sig.entry_price,
            stop_price=sig.stop_price,
            target_price=sig.target_price,
            risk=sig.risk,
            substrategy=sig.substrategy,
            zone_price=sig.zone_price,
            zone_side=sig.zone_side,
            zone_source=sig.zone_source,
            zone_bar_key=sig.zone_bar_key,
            sweep_bar_key=sig.sweep_bar_key,
        )
        self._meta_by_structure_id[structure_id] = meta

        qty = self._entry_order_qty(inst)
        intent = self.create_order_intent(
            inst=inst,
            side=order_side,
            qty=qty,
            price=sig.entry_price,
            order_type="LIMIT",
            strategy=self.name,
            candle_ts=candle["timestamp"],
            structure_id=structure_id,
            tag="MAIN",
            symbol=symbol,
            action="ENTRY",
            metadata_extras=self._strategy_meta(meta),
        )
        logger.info(
            "LiquiditySweepStrategy ENTRY %s %s [%s] entry=%.2f stop=%.2f target=%.2f "
            "swept_%s=%.2f zone_bar=%s sweep_bar=%s source=%s",
            symbol,
            sig.side,
            sig.substrategy,
            sig.entry_price,
            sig.stop_price,
            sig.target_price,
            sig.zone_side or "level",
            float(sig.zone_price or 0.0),
            sig.zone_bar_key or "-",
            sig.sweep_bar_key or "-",
            sig.zone_source or "-",
        )
        return [intent]

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
        **kwargs: Any,
    ) -> List[Any]:
        if not structure_id or not intent_id:
            return []
        sid = str(structure_id)
        self._ensure_meta_for_fill(
            sid, instrument, ctx, intent_id, metadata_extras, fill_price=price
        )
        meta = self._meta_by_structure_id.get(sid)
        if meta is None:
            return []

        fill_px = float(price if price is not None else meta.entry_price)
        meta.entry_price = fill_px
        if meta.side == "LONG":
            meta.target_price = fill_px + meta.risk
            meta.stop_price = fill_px - meta.risk
        else:
            meta.target_price = fill_px - meta.risk
            meta.stop_price = fill_px + meta.risk

        total_qty = self._normalize_order_qty(instrument, kwargs.get("qty"))
        book_qty, trail_qty = self._normalize_qty(total_qty)
        exit_side = "SELL" if meta.side == "LONG" else "BUY"

        return [
            self.create_order_intent(
                inst=instrument,
                side=exit_side,
                qty=total_qty,
                price=float(meta.stop_price),
                order_type="SL-M",
                strategy=self.name,
                candle_ts=candle_ts,
                structure_id=sid,
                tag="MAIN_SL",
                symbol=meta.symbol,
                action="FORCE_EXIT",
                parent_intent_id=intent_id,
                trigger_price=float(meta.stop_price),
            ),
            self.create_order_intent(
                inst=instrument,
                side=exit_side,
                qty=book_qty,
                price=float(meta.target_price),
                order_type="SL-M",
                strategy=self.name,
                candle_ts=candle_ts,
                structure_id=sid,
                tag="MAIN_TARGET",
                symbol=meta.symbol,
                action="FORCE_EXIT",
                parent_intent_id=intent_id,
                trigger_price=float(meta.target_price),
            ),
        ]

    def _symbol_from_exit_kwargs(self, meta: _LegMeta, kwargs: dict) -> str:
        inst = kwargs.get("instrument")
        if inst is not None:
            sym = getattr(inst, "underlying_symbol", None) or getattr(inst, "symbol", None)
            if sym:
                return str(sym).strip().upper()
        return str(meta.symbol).strip().upper()

    def _record_gautham_sl_hit(
        self,
        structure_id: str,
        symbol: str,
        candle_ts: Any,
        *,
        substrategy: str,
    ) -> None:
        sid = str(structure_id or "")
        if not sid or sid in self._sl_recorded_structure_ids:
            return
        if substrategy != "GauthamLiquiditySweep":
            return
        self._sl_recorded_structure_ids.add(sid)
        self._gautham.on_sl_hit(
            symbol,
            {"symbol": symbol, "timestamp": candle_ts},
        )

    def on_main_exit_filled(self, **kwargs: Any) -> List[Any]:
        tag = str(kwargs.get("tag") or "").upper()
        sid = str(kwargs.get("structure_id") or "")
        meta = self._meta_by_structure_id.get(sid)

        if tag == "MAIN_SL":
            if meta is not None:
                self._record_gautham_sl_hit(
                    sid,
                    meta.symbol,
                    kwargs.get("candle_ts"),
                    substrategy=meta.substrategy,
                )
            else:
                extras = kwargs.get("metadata_extras")
                raw = (
                    extras.get(META_KEY)
                    if isinstance(extras, dict)
                    else None
                )
                if isinstance(raw, dict):
                    self._record_gautham_sl_hit(
                        sid,
                        str(raw.get("symbol") or ""),
                        kwargs.get("candle_ts"),
                        substrategy=str(raw.get("substrategy") or "GauthamLiquiditySweep"),
                    )
            return []

        if tag != "MAIN_TARGET" or not sid or meta is None:
            return []
        meta.partial_booked = True
        meta.trail_stop = meta.entry_price
        logger.info(
            "LiquiditySweepStrategy partial booked sid=%s %s — trail remainder from BE",
            sid,
            meta.symbol,
        )
        return []

    def should_exit(
        self,
        position: Any,
        candle: dict,
        ctx: Optional["StrategyContext"] = None,
    ) -> bool:
        if ctx is None or not position:
            return False
        sid = str(getattr(position, "structure_id", "") or "")
        meta = self._meta_by_structure_id.get(sid)
        if meta is None or not meta.partial_booked:
            return False

        close = float(candle.get("close") or 0)
        if meta.side == "LONG":
            sw = candle.get("last_swing_low")
            if sw is not None and not pd.isna(sw):
                meta.trail_stop = max(
                    float(meta.trail_stop or meta.entry_price),
                    float(sw),
                )
            trail = meta.trail_stop or meta.entry_price
            return close <= trail
        sw = candle.get("last_swing_high")
        if sw is not None and not pd.isna(sw):
            meta.trail_stop = min(
                float(meta.trail_stop or meta.entry_price),
                float(sw),
            )
        trail = meta.trail_stop or meta.entry_price
        return close >= trail

    def on_position_exit(
        self, position: Any, candle: dict, ctx: "StrategyContext"
    ) -> Optional[List[Any]]:
        if position.instrument is None:
            return None
        exit_side = "SELL" if position.net_qty > 0 else "BUY"
        return [
            self.create_order_intent(
                inst=position.instrument,
                side=exit_side,
                qty=abs(int(position.net_qty)),
                price=float(candle["close"]),
                order_type="LIMIT",
                strategy=self.name,
                structure_id=position.structure_id or "",
                tag="MAIN",
                candle_ts=candle["timestamp"],
                symbol=candle.get("symbol"),
                action="EXIT",
            )
        ]

    def on_structure_exit(self, structure_id: str, **kwargs: Any) -> None:
        sid = str(structure_id or "")
        meta = self._meta_by_structure_id.get(sid)
        reason = str(kwargs.get("exit_reason") or "").upper()
        if meta is not None and reason == "SL":
            self._record_gautham_sl_hit(
                sid,
                self._symbol_from_exit_kwargs(meta, kwargs),
                kwargs.get("candle_ts"),
                substrategy=meta.substrategy,
            )
        self._meta_by_structure_id.pop(sid, None)
        super().on_structure_exit(structure_id=structure_id, **kwargs)
