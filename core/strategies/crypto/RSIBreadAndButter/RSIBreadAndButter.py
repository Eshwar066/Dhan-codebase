"""
RSI Bread & Butter — Delta crypto futures (BTC, ETH, …).

Rules
- Signal TF (1m or 5m): RSI(14) regular divergence near 70/30 zones.
- Entry TF: same as signal when signal is 1m; otherwise 1m BOS after 5m signal.
- Exit: 1:1 target — book 60% size; trail remainder on structure (last swing).

python utils/delta/refresh_crypto_indicator_history.py --only 1
python utils/delta/refresh_crypto_indicator_history.py --only 5

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
from core.utils.structure import MarketStructureConfig
from core.utils.structure.rsi_divergence import add_rsi_divergence
from core.utils.structure.swings import add_swing_points
from core.utils import indicator_history as ind_hist

if TYPE_CHECKING:
    from core.models.strategy_context import StrategyContext

logger = logging.getLogger(__name__)

RSI_OVERBOUGHT = 70.0
RSI_OVERSOLD = 30.0
DEFAULT_SIGNAL_TF_MINUTES = 1
PARTIAL_BOOK_FRAC = 0.60
DEFAULT_ORDER_QTY = 4  # fallback when engine ``ORDER_QTY_LOTS`` is unset
SIGNAL_MAX_AGE_BARS = 100  # entry-TF bars to act after signal-TF divergence
MAX_STOP_POINTS = 500.0  # max SL distance from entry (price units)
META_KEY = "rsi_bread_butter"


@dataclass
class _LegMeta:
    symbol: str
    side: str  # LONG | SHORT
    entry_price: float
    stop_price: float
    target_price: float
    risk: float
    partial_booked: bool = False
    trail_stop: Optional[float] = None


class RSIBreadAndButter(MarketStructureMixin, IndiaMktMixins, BaseStrategy):
    """
    Crypto futures mean-reversion + structure continuation (Bread & Butter).
    """

    name = "RSIBreadAndButter"
    underlying_symbols = ["BTCUSD", "ETHUSD"]
    timeframe = "1"
    required_context = ["instrument_store"]
    api = "DELTA"
    market_structure_enabled = True
    bracket_leg_tags = ["MAIN_SL", "MAIN_TARGET"]

    # 1 or 5 — RSI divergence on this TF (see ``entry_timeframe_minutes`` for BOS entry TF).
    signal_timeframe_minutes: int = DEFAULT_SIGNAL_TF_MINUTES

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._meta_by_structure_id: Dict[str, _LegMeta] = {}
        self._active_signal: Dict[str, Dict[str, Any]] = {}
        self._signal_bar_counter: Dict[str, int] = {}
        self._last_eval_bucket: Dict[str, int] = {}
        self._sync_entry_timeframe()

    @staticmethod
    def _timeframe_minutes(tf: Any) -> int:
        raw = str(tf or "").strip().lower()
        if not raw:
            return 1
        if raw.endswith("m"):
            try:
                return max(1, int(raw[:-1]))
            except ValueError:
                return 1
        if raw in ("1h", "60"):
            return 60
        try:
            return max(1, int(raw))
        except ValueError:
            return 1

    def signal_timeframe_minutes_resolved(self) -> int:
        return max(1, int(self.signal_timeframe_minutes))

    def entry_timeframe_minutes(self) -> int:
        """
        Engine / BOS timeframe.

        1m signal → 1m entry (same TF for RSI divergence and BOS).
        Higher signal TF (e.g. 5m) → 1m BOS entry after divergence.
        """
        sig = self.signal_timeframe_minutes_resolved()
        if sig <= 1:
            return 1
        return 1

    def _sync_entry_timeframe(self) -> None:
        self.timeframe = str(self.entry_timeframe_minutes())

    def _entry_order_qty(self, inst) -> int:
        """Lots: engine ``ORDER_QTY_LOTS`` → ``order_qty_lots``; else ``DEFAULT_ORDER_QTY``."""
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
            rsi_period=14,
        )

    def get_warmup_period(self) -> int:
        sig = self.signal_timeframe_minutes_resolved()
        entry = self.entry_timeframe_minutes()
        return max(50, max(sig, entry) * 30)

    def get_structure_lookback(self) -> int:
        return max(300, self.get_warmup_period() + 50)

    def prepare_indicators(self, df: Any) -> Any:
        df = super().prepare_indicators(df)
        return df

    def _strategy_meta(self, meta: _LegMeta) -> dict:
        return {
            META_KEY: {
                "symbol": meta.symbol,
                "side": meta.side,
                "entry_price": meta.entry_price,
                "stop_price": meta.stop_price,
                "target_price": meta.target_price,
                "risk": meta.risk,
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

    @staticmethod
    def _candle_row_timestamp(c: dict) -> Optional[pd.Timestamp]:
        """IST bar open — same key as indicator_history ``candle_timestamp_ist``."""
        ist_key = c.get("candle_timestamp_ist")
        if ist_key:
            aware = ind_hist.parse_bar_timestamp_ist_to_aware(ist_key)
            if aware is not None:
                return pd.Timestamp(aware)
        ts = c.get("timestamp")
        if ts is None:
            return None
        parsed = pd.to_datetime(ts, utc=True, errors="coerce")
        if parsed is not None and not bool(pd.isna(parsed)):
            return parsed.tz_convert(ind_hist.IST)
        aware_ist = ind_hist.row_timestamp_to_ist(ts)
        if aware_ist is not None:
            return pd.Timestamp(aware_ist)
        return None

    @staticmethod
    def _candles_to_df(candles: List[dict]) -> pd.DataFrame:
        rows = []
        for c in candles:
            ts = RSIBreadAndButter._candle_row_timestamp(c)
            if ts is None:
                continue
            rows.append(
                {
                    "timestamp": ts,
                    "candle_timestamp_ist": ind_hist.normalize_ist_bar_key(ts),
                    "open": float(c.get("open", c.get("close", 0)) or 0),
                    "high": float(c.get("high", c.get("close", 0)) or 0),
                    "low": float(c.get("low", c.get("close", 0)) or 0),
                    "close": float(c.get("close", 0) or 0),
                    "volume": float(c.get("volume", 0) or 0),
                }
            )
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
        return df

    def _resample_ohlc(self, df: pd.DataFrame, minutes: int) -> pd.DataFrame:
        if df.empty or minutes <= 1:
            return df
        tmp = df.set_index("timestamp")
        rule = f"{int(minutes)}min"
        out = tmp.resample(rule, label="left", closed="left").agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        out = out.dropna(subset=["close"]).reset_index()
        return out

    def _scan_signal_timeframe(
        self, candles: List[dict]
    ) -> Optional[str]:
        """Return ``LONG`` / ``SHORT`` when signal-TF RSI divergence fires."""
        signal_m = self.signal_timeframe_minutes_resolved()
        entry_m = self.entry_timeframe_minutes()

        # 1m signal on 1m engine candles: use indicators already on buffered candles
        # (from indicator_history overlay / prepare_indicators), not a short-window recompute.
        if signal_m <= entry_m and candles:
            last = candles[-1]
            rsi = float(pd.to_numeric(last.get("rsi"), errors="coerce") or float("nan"))
            bull = bool(int(pd.to_numeric(last.get("rsi_div_bull"), errors="coerce") or 0))
            bear = bool(int(pd.to_numeric(last.get("rsi_div_bear"), errors="coerce") or 0))
            if bull and rsi <= RSI_OVERSOLD + 5:
                return "LONG"
            if bear and rsi >= RSI_OVERBOUGHT - 5:
                return "SHORT"
            return None

        df = self._candles_to_df(candles)
        if len(df) < 20:
            return None
        if signal_m > entry_m:
            df = self._resample_ohlc(df, signal_m)
        if len(df) < 15:
            return None

        cfg = self.market_structure_config()
        df = add_swing_points(
            df, left=cfg.swing_left, right=cfg.swing_right, prefix="swing"
        )
        df = add_rsi_divergence(
            df,
            swing_high_col="swing_high",
            swing_low_col="swing_low",
            swing_high_price_col="swing_high_price",
            swing_low_price_col="swing_low_price",
            rsi_period=cfg.rsi_period,
        )
        row = df.iloc[-1]
        rsi = float(row.get("rsi") or float("nan"))

        if bool(row.get("rsi_div_bull")) and rsi <= RSI_OVERSOLD + 5:
            return "LONG"
        if bool(row.get("rsi_div_bear")) and rsi >= RSI_OVERBOUGHT - 5:
            return "SHORT"
        return None

    def _tick_signal_age(self, symbol: str) -> None:
        self._signal_bar_counter[symbol] = self._signal_bar_counter.get(symbol, 0) + 1

    def _set_active_signal(self, symbol: str, side: str) -> None:
        self._active_signal[symbol] = {
            "side": side,
            "age": 0,
        }
        self._signal_bar_counter[symbol] = 0

    def _active_signal_side(self, symbol: str) -> Optional[str]:
        slot = self._active_signal.get(symbol)
        if not slot:
            return None
        age = int(slot.get("age", 0))
        if age > SIGNAL_MAX_AGE_BARS:
            self._active_signal.pop(symbol, None)
            return None
        slot["age"] = age + 1
        return str(slot.get("side") or "").upper() or None

    def _structure_stop(
        self, candle: dict, side: str, entry: float
    ) -> float:
        if side == "LONG":
            sw = candle.get("last_swing_low")
            if sw is not None and not pd.isna(sw):
                return float(sw)
            return entry * 0.995
        sw = candle.get("last_swing_high")
        if sw is not None and not pd.isna(sw):
            return float(sw)
        return entry * 1.005

    @staticmethod
    def _cap_stop_distance(side: str, entry: float, stop: float) -> float:
        """Tighten structure stop so risk does not exceed MAX_STOP_POINTS."""
        if side == "LONG":
            return max(float(stop), entry - MAX_STOP_POINTS)
        return min(float(stop), entry + MAX_STOP_POINTS)

    def _build_structure_id(self, symbol: str, side: str) -> str:
        return f"{self.name}:{symbol}:{side}:{uuid.uuid4().hex[:8]}"

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
        sym = str(candle.get("symbol") or "").strip().upper()
        bucket = candle.get("bucket_ts")
        if bucket is None:
            return True
        b = int(bucket)
        prev = self._last_eval_bucket.get(sym)
        if prev is not None and b <= prev:
            return False
        self._last_eval_bucket[sym] = b
        return True

    def on_candle(
        self, candle: dict, ctx: "StrategyContext"
    ) -> Optional[List[Any]]:
        symbol = str(candle.get("symbol") or "").strip().upper()
        if not symbol:
            return None

        self._tick_signal_age(symbol)
        n_need = self.get_warmup_period()
        recent = ctx.get_recent_candles(n_need) if ctx else []
        if len(recent) < 30:
            return None

        # === Scan signal timeframe ===
        sig_side = self._scan_signal_timeframe(recent)
        if sig_side:
            self._set_active_signal(symbol, sig_side)

        active = self._active_signal_side(symbol)
        if not active:
            return None

        bos = int(pd.to_numeric(candle.get("bos"), errors="coerce") or 0)
        if active == "LONG" and bos != 1:
            return None
        if active == "SHORT" and bos != -1:
            return None

        exchange = str(candle.get("exchange") or "DELTA")
        inst = ctx.instrument_store.futures_intent_creation_details(
            symbol, exchange, expiry=None
        )
        if inst is None:
            return None

        side = active
        structure_id = self._build_structure_id(symbol, side)
        for p in ctx.position_store.get_open_positions(
            underlying=symbol, strategy=self.name
        ) or []:
            if p and int(getattr(p, "net_qty", 0) or 0) != 0:
                return None

        entry = float(candle["close"])
        stop = self._cap_stop_distance(
            side, entry, self._structure_stop(candle, side, entry)
        )
        risk = abs(entry - stop)
        if risk <= 0:
            return None

        if side == "LONG":
            target = entry + risk
            order_side = "BUY"
        else:
            target = entry - risk
            order_side = "SELL"

        meta = _LegMeta(
            symbol=symbol,
            side=side,
            entry_price=entry,
            stop_price=stop,
            target_price=target,
            risk=risk,
        )
        self._meta_by_structure_id[structure_id] = meta
        self._active_signal.pop(symbol, None)

        qty = self._entry_order_qty(inst)
        intent = self.create_order_intent(
            inst=inst,
            side=order_side,
            qty=qty,
            price=entry,
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
            "RSIBreadAndButter ENTRY %s %s entry=%.2f stop=%.2f target=%.2f",
            symbol,
            side,
            entry,
            stop,
            target,
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

        ref = SimpleNamespace(
            instrument=instrument,
            structure_id=sid,
            intent_id=intent_id,
            qty=total_qty,
        )

        out = [
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
        logger.info(
            "RSIBreadAndButter bracket sid=%s %s entry=%.2f SL=%.2f TARGET=%.2f total_qty=%s book_qty=%s trail_qty=%s",
            sid,
            meta.side,
            fill_px,
            meta.stop_price,
            meta.target_price,
            total_qty,
            book_qty,
            trail_qty,
        )
        return out

    def on_main_exit_filled(self, **kwargs: Any) -> List[Any]:
        sid = str(kwargs.get("structure_id") or "")
        tag = str(kwargs.get("tag") or "").upper()
        if tag != "MAIN_TARGET" or not sid:
            return []
        meta = self._meta_by_structure_id.get(sid)
        if meta is None:
            return []
        meta.partial_booked = True
        meta.trail_stop = meta.entry_price
        logger.info(
            "RSIBreadAndButter partial booked sid=%s %s — trail remainder from BE",
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
