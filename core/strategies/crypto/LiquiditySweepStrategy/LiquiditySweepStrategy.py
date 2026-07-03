"""
Liquidity sweep strategy shell — hosts multiple sub-strategies with shared execution.

Sub-strategies
- ``GauthamLiquiditySweep``: PDH/PDL sweep + two reversal candles on 1m (see ``gautham_liquidity_sweep.py``).

Later sub-strategies can be registered in ``_SUBSTRATEGIES`` with their own entry/exit rules.
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import pandas as pd

from core.strategies.base import BaseStrategy
from core.strategies.IndiaMktMixins import IndiaMktMixins
from core.strategies.market_structure_mixin import MarketStructureMixin
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


class LiquiditySweepStrategy(MarketStructureMixin, IndiaMktMixins, BaseStrategy):
    """
    Delta crypto futures — liquidity sweep framework (1m entry, daily PDH/PDL levels).
    """

    name = "LiquiditySweepStrategy"
    underlying_symbols = ["BTCUSD", "ETHUSD"]
    timeframe = "1"
    required_context = ["instrument_store"]
    api = "DELTA"
    market_structure_enabled = True
    bracket_leg_tags = ["MAIN_SL", "MAIN_TARGET"]

    enabled_substrategies: List[str] = ["GauthamLiquiditySweep"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._meta_by_structure_id: Dict[str, _LegMeta] = {}
        self._evaluated_bar_keys: set[str] = set()
        self._gautham = GauthamLiquiditySweep()
        self._substrategies: Dict[str, Any] = {
            "GauthamLiquiditySweep": self._gautham,
        }

    def _entry_order_qty(self, inst) -> int:
        engine_lots = getattr(self, "order_qty_lots", None)
        if engine_lots is not None:
            return max(1, int(engine_lots))
        return max(1, int(DEFAULT_ORDER_QTY))

    def market_structure_config(self) -> MarketStructureConfig:
        ex = getattr(self, "_structure_session_exchange", None) or "DELTA"
        return MarketStructureConfig(
            swing_left=2,
            swing_right=2,
            include_fvg=False,
            include_order_blocks=False,
            include_bos_choch=False,
            include_rsi_divergence=False,
            include_liquidity_sweeps=True,
            liquidity_session_exchange=ex,
        )

    def get_warmup_period(self) -> int:
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
        key = f"{sym}|{b}"
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

        signals = self._collect_entry_signals(candle, ctx)
        if not signals:
            return None

        sig = signals[0]
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
            "LiquiditySweepStrategy ENTRY %s %s [%s] entry=%.2f stop=%.2f target=%.2f",
            symbol,
            sig.side,
            sig.substrategy,
            sig.entry_price,
            sig.stop_price,
            sig.target_price,
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

    def on_main_exit_filled(self, **kwargs: Any) -> List[Any]:
        tag = str(kwargs.get("tag") or "").upper()
        sid = str(kwargs.get("structure_id") or "")
        meta = self._meta_by_structure_id.get(sid)

        if tag == "MAIN_SL" and meta is not None:
            candle_stub = {
                "symbol": meta.symbol,
                "timestamp": kwargs.get("candle_ts"),
            }
            if meta.substrategy == "GauthamLiquiditySweep":
                self._gautham.on_sl_hit(meta.symbol, candle_stub)
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
        self._meta_by_structure_id.pop(str(structure_id), None)
        super().on_structure_exit(structure_id=structure_id, **kwargs)
