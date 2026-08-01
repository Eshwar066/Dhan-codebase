"""
4H liquidity zones for LiquiditySweepStrategy.

Zones are built from **all** completed 4H candles (prior bar high/low + confirmed
4H swing pivots). Levels swept by a later 4H bar are dropped. The active file
stores only unswept levels.

Sweep detection for entries runs on 1m bars: wick through the level and close
back inside.

Persistence (shared backtest + live reference)
- Append-only log: ``logs/LiquiditySweepStrategy/liquidity_zones.jsonl``
- Active snapshot: ``logs/LiquiditySweepStrategy/liquidity_zones_active.json``
  (``highs`` / ``lows`` / ``consumed``; recent candle first; consumed = last 10d sweeps)
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from core.utils import indicator_history as ind_hist

logger = logging.getLogger(__name__)

SWING_LEFT = 2
SWING_RIGHT = 2
# Persisted ``consumed`` entries: only sweeps in the last N days (IST).
CONSUMED_RETENTION_DAYS = 10

DEFAULT_ZONES_DIR = os.path.join(ind_hist.DEFAULT_LOG_ROOT, "LiquiditySweepStrategy")
DEFAULT_ZONES_JSONL = os.path.join(DEFAULT_ZONES_DIR, "liquidity_zones.jsonl")
DEFAULT_ZONES_ACTIVE = os.path.join(DEFAULT_ZONES_DIR, "liquidity_zones_active.json")
ZONES_SCHEMA = 4


@dataclass(frozen=True)
class LiquidityZone:
    price: float
    side: str  # "high" | "low"
    source: str
    bar_key: str
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    timeframe: str = "4h"


@dataclass(frozen=True)
class ConsumedRecord:
    zone: LiquidityZone
    swept_at: str  # IST bar key of the candle that swept it


@dataclass
class _SymbolZones:
    bars: List[dict] = field(default_factory=list)
    high_zones: List[LiquidityZone] = field(default_factory=list)
    low_zones: List[LiquidityZone] = field(default_factory=list)
    consumed: set = field(default_factory=set)
    consumed_detail: Dict[str, ConsumedRecord] = field(default_factory=dict)


def zones_jsonl_path(log_root: Optional[str] = None) -> str:
    if log_root:
        return os.path.join(log_root, "LiquiditySweepStrategy", "liquidity_zones.jsonl")
    return DEFAULT_ZONES_JSONL


def zones_active_path(log_root: Optional[str] = None) -> str:
    if log_root:
        return os.path.join(log_root, "LiquiditySweepStrategy", "liquidity_zones_active.json")
    return DEFAULT_ZONES_ACTIVE


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write_json(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=".liquidity_zones_",
        suffix=".json",
        dir=os.path.dirname(path) or ".",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class FourHourLiquidityBook:
    """Per-symbol book of active 4H liquidity prices with shared disk ledger."""

    def __init__(
        self,
        *,
        persist: bool = True,
        jsonl_path: Optional[str] = None,
        active_path: Optional[str] = None,
    ) -> None:
        self._by_symbol: Dict[str, _SymbolZones] = {}
        self.persist = bool(persist)
        self.jsonl_path = jsonl_path or DEFAULT_ZONES_JSONL
        self.active_path = active_path or DEFAULT_ZONES_ACTIVE
        self._persist_source = "live"

    def set_persist_source(self, source: str) -> None:
        self._persist_source = str(source or "live").strip() or "live"

    def suspend_persist(self):
        """Context manager: temporarily disable disk writes (bulk as-of sync)."""
        book = self

        class _Suspend:
            def __enter__(self_inner):
                self_inner._prev = book.persist
                book.persist = False
                return book

            def __exit__(self_inner, *exc):
                book.persist = self_inner._prev
                return False

        return _Suspend()

    def _state(self, symbol: str) -> _SymbolZones:
        sym = str(symbol or "").strip().upper()
        if sym not in self._by_symbol:
            self._by_symbol[sym] = _SymbolZones()
        return self._by_symbol[sym]

    @staticmethod
    def _bar_key(candle: dict) -> str:
        k = candle.get("candle_timestamp_ist") or candle.get("bucket_ts")
        if k is not None:
            return str(k)
        ts = candle.get("timestamp")
        if ts is None:
            return ""
        try:
            return str(pd.to_datetime(ts, utc=True))
        except (TypeError, ValueError):
            return str(ts)

    @staticmethod
    def _ohlc(candle: dict) -> Optional[Tuple[float, float, float, float]]:
        try:
            o = float(candle["open"])
            h = float(candle["high"])
            l = float(candle["low"])
            c = float(candle["close"])
        except (KeyError, TypeError, ValueError):
            return None
        if min(o, h, l, c) <= 0:
            return None
        return o, h, l, c

    def on_4h_close(self, symbol: str, candle: dict) -> bool:
        """
        Ingest a fully closed 4H bar and rebuild active zones (idempotent by bar key).

        Returns True when a new bar was accepted.
        """
        sym = str(symbol or "").strip().upper()
        ohlc = self._ohlc(candle)
        if not sym or ohlc is None:
            return False
        o, h, l, c = ohlc
        st = self._state(sym)
        key = self._bar_key(candle)
        if key and any(b.get("key") == key for b in st.bars):
            return False
        st.bars.append(
            {
                "key": key,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
            }
        )
        self._rebuild_zones(sym, st)
        # Invalidate levels already swept by this closed 4H bar.
        self._apply_bar_sweeps(sym, candle, st)
        as_of = candle.get("candle_timestamp_ist") or key or None
        self._persist_symbol(sym, as_of=as_of, event="zone_snapshot")
        logger.debug(
            "FourHourLiquidityBook %s zones hi=%s lo=%s consumed=%s (bars=%s) last_4h H=%.2f L=%.2f",
            sym,
            [round(z.price, 2) for z in st.high_zones],
            [round(z.price, 2) for z in st.low_zones],
            len(st.consumed),
            len(st.bars),
            h,
            l,
        )
        return True

    def _mark_consumed_internal(
        self,
        st: _SymbolZones,
        zone: LiquidityZone,
        *,
        swept_at: Optional[str] = None,
    ) -> bool:
        """Record consumed zone and drop from active lists. Returns True if newly consumed."""
        ck = f"{zone.side}:{round(zone.price, 2)}"
        if ck in st.consumed:
            return False
        st.consumed.add(ck)
        st.consumed_detail[ck] = ConsumedRecord(
            zone=zone,
            swept_at=str(swept_at or zone.bar_key or ""),
        )
        if zone.side == "high":
            st.high_zones = [
                z for z in st.high_zones if round(z.price, 2) != round(zone.price, 2)
            ]
        else:
            st.low_zones = [
                z for z in st.low_zones if round(z.price, 2) != round(zone.price, 2)
            ]
        return True

    def _apply_bar_sweeps(self, symbol: str, candle: dict, st: _SymbolZones) -> int:
        """
        Mark active zones swept by ``candle`` OHLC.

        High sweep: high > level and close < level.
        Low sweep: low < level and close > level.

        Zones created by this same bar (matching bar_key) are not consumed by it.
        """
        ohlc = self._ohlc(candle)
        if ohlc is None:
            return 0
        _o, h, l, c = ohlc
        bar_key = self._bar_key(candle)
        n = 0
        for z in list(st.high_zones):
            if bar_key and z.bar_key == bar_key:
                continue
            if self._sweep_high(h, c, z.price):
                if self._mark_consumed_internal(st, z, swept_at=bar_key):
                    n += 1
                    logger.info(
                        "FourHourLiquidityBook %s SWEPT high=%.2f by bar=%s "
                        "(H=%.2f C=%.2f)",
                        symbol,
                        z.price,
                        bar_key,
                        h,
                        c,
                    )
        for z in list(st.low_zones):
            if bar_key and z.bar_key == bar_key:
                continue
            if self._sweep_low(l, c, z.price):
                if self._mark_consumed_internal(st, z, swept_at=bar_key):
                    n += 1
                    logger.info(
                        "FourHourLiquidityBook %s SWEPT low=%.2f by bar=%s "
                        "(L=%.2f C=%.2f)",
                        symbol,
                        z.price,
                        bar_key,
                        l,
                        c,
                    )
        return n

    @staticmethod
    def _zone_from_bar(
        bar: dict, *, price: float, side: str, source: str
    ) -> LiquidityZone:
        return LiquidityZone(
            price=float(price),
            side=side,
            source=source,
            bar_key=str(bar.get("key") or ""),
            open=float(bar.get("open") or 0.0),
            high=float(bar.get("high") or 0.0),
            low=float(bar.get("low") or 0.0),
            close=float(bar.get("close") or 0.0),
            timeframe="4h",
        )

    def _rebuild_zones(self, symbol: str, st: _SymbolZones) -> None:
        highs: List[LiquidityZone] = []
        lows: List[LiquidityZone] = []
        bars = list(st.bars)
        if not bars:
            st.high_zones = []
            st.low_zones = []
            return

        # Prior completed 4H candle high/low (always).
        last = bars[-1]
        highs.append(
            self._zone_from_bar(
                last, price=float(last["high"]), side="high", source="prev_4h"
            )
        )
        lows.append(
            self._zone_from_bar(
                last, price=float(last["low"]), side="low", source="prev_4h"
            )
        )

        # Confirmed fractal swings on the 4H series.
        n = len(bars)
        left, right = SWING_LEFT, SWING_RIGHT
        if n >= left + right + 1:
            for i in range(left, n - right):
                h_win = [bars[j]["high"] for j in range(i - left, i + right + 1)]
                l_win = [bars[j]["low"] for j in range(i - left, i + right + 1)]
                if bars[i]["high"] == max(h_win):
                    highs.append(
                        self._zone_from_bar(
                            bars[i],
                            price=float(bars[i]["high"]),
                            side="high",
                            source="swing_4h",
                        )
                    )
                if bars[i]["low"] == min(l_win):
                    lows.append(
                        self._zone_from_bar(
                            bars[i],
                            price=float(bars[i]["low"]),
                            side="low",
                            source="swing_4h",
                        )
                    )

        def _dedupe(zones: List[LiquidityZone]) -> List[LiquidityZone]:
            seen = set()
            out: List[LiquidityZone] = []
            # Newest first — keep every unswept unique price (no bar-window / side cap).
            for z in reversed(zones):
                rk = round(z.price, 2)
                if rk in seen:
                    continue
                ck = f"{z.side}:{rk}"
                if ck in st.consumed:
                    continue
                seen.add(rk)
                out.append(z)
            return out  # already newest-first

        st.high_zones = self._sort_zones_recent_first(_dedupe(highs))
        st.low_zones = self._sort_zones_recent_first(_dedupe(lows))

    @staticmethod
    def _parse_bar_key_ist(bar_key: str) -> Optional[pd.Timestamp]:
        key = str(bar_key or "").strip()
        if not key:
            return None
        try:
            ts = pd.to_datetime(key)
        except (TypeError, ValueError):
            return None
        if pd.isna(ts):
            return None
        if getattr(ts, "tzinfo", None) is None:
            try:
                return ts.tz_localize(ind_hist.IST)
            except Exception:
                return ts
        try:
            return ts.tz_convert(ind_hist.IST)
        except Exception:
            return ts

    @classmethod
    def _sort_zones_recent_first(cls, zones: List[LiquidityZone]) -> List[LiquidityZone]:
        # bar_key is IST ``YYYY-MM-DD HH:MM`` — lexicographic order == time order.
        return sorted(zones, key=lambda z: str(z.bar_key or ""), reverse=True)

    @classmethod
    def _sort_consumed_recent_first(
        cls, records: List[ConsumedRecord]
    ) -> List[ConsumedRecord]:
        return sorted(
            records,
            key=lambda r: str(r.swept_at or r.zone.bar_key or ""),
            reverse=True,
        )

    def _as_of_ist_for_symbol(self, symbol: str, as_of: Any = None) -> Optional[pd.Timestamp]:
        if as_of is not None:
            t = self._parse_bar_key_ist(str(as_of))
            if t is not None:
                return t
            try:
                ts = pd.to_datetime(as_of, utc=True)
                if not pd.isna(ts):
                    return ts.tz_convert(ind_hist.IST)
            except (TypeError, ValueError):
                pass
        st = self._state(symbol)
        if st.bars:
            return self._parse_bar_key_ist(str(st.bars[-1].get("key") or ""))
        return pd.Timestamp.now(tz=ind_hist.IST)

    def _consumed_records_last_days(
        self, symbol: str, *, as_of: Any = None, days: int = CONSUMED_RETENTION_DAYS
    ) -> List[ConsumedRecord]:
        """Consumed zones whose sweep time is within the last ``days`` (IST)."""
        st = self._state(symbol)
        as_of_ist = self._as_of_ist_for_symbol(symbol, as_of)
        if as_of_ist is None:
            return self._sort_consumed_recent_first(list(st.consumed_detail.values()))
        cutoff = as_of_ist - pd.Timedelta(days=int(days))
        kept: List[ConsumedRecord] = []
        for rec in st.consumed_detail.values():
            swept_ts = self._parse_bar_key_ist(rec.swept_at) or self._parse_bar_key_ist(
                rec.zone.bar_key
            )
            if swept_ts is None or swept_ts >= cutoff:
                kept.append(rec)
        return self._sort_consumed_recent_first(kept)

    def _zone_payload(self, z: LiquidityZone) -> dict:
        return {
            "price": float(z.price),
            "side": z.side,
            "source": z.source,
            "bar_key": z.bar_key,
            "candle": {
                "timeframe": z.timeframe or "4h",
                "candle_timestamp_ist": z.bar_key,
                "open": float(z.open),
                "high": float(z.high),
                "low": float(z.low),
                "close": float(z.close),
            },
        }

    @staticmethod
    def _zone_from_payload(item: dict, *, default_side: str) -> Optional[LiquidityZone]:
        try:
            price = float(item["price"])
        except (KeyError, TypeError, ValueError):
            return None
        candle = item.get("candle") if isinstance(item.get("candle"), dict) else {}
        bar_key = str(item.get("bar_key") or candle.get("candle_timestamp_ist") or "")
        try:
            o = float(candle.get("open", item.get("open", 0.0)) or 0.0)
            h = float(candle.get("high", item.get("high", 0.0)) or 0.0)
            l = float(candle.get("low", item.get("low", 0.0)) or 0.0)
            c = float(candle.get("close", item.get("close", 0.0)) or 0.0)
        except (TypeError, ValueError):
            o = h = l = c = 0.0
        return LiquidityZone(
            price=price,
            side=str(item.get("side") or default_side),
            source=str(item.get("source") or "reference_file"),
            bar_key=bar_key,
            open=o,
            high=h,
            low=l,
            close=c,
            timeframe=str(candle.get("timeframe") or item.get("timeframe") or "4h"),
        )

    def _consumed_payload(self, rec: ConsumedRecord) -> dict:
        payload = self._zone_payload(rec.zone)
        payload["swept_at"] = rec.swept_at
        return payload

    def _symbol_snapshot_dict(self, symbol: str, *, as_of: Any = None) -> dict:
        st = self._state(symbol)
        highs = self._sort_zones_recent_first(list(st.high_zones))
        lows = self._sort_zones_recent_first(list(st.low_zones))
        consumed_recs = self._consumed_records_last_days(symbol, as_of=as_of)
        return {
            "schema": ZONES_SCHEMA,
            "event": "zone_snapshot",
            "symbol": str(symbol).strip().upper(),
            "as_of": as_of,
            "written_at_utc": _utc_now_iso(),
            "source": self._persist_source,
            "highs": [self._zone_payload(z) for z in highs],
            "lows": [self._zone_payload(z) for z in lows],
            "consumed": [self._consumed_payload(r) for r in consumed_recs],
            "swept_count": len(st.consumed),
            "bar_count": len(st.bars),
        }

    def _append_jsonl(self, payload: dict) -> None:
        if not self.persist:
            return
        path = self.jsonl_path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")

    def _rewrite_active_file(self) -> None:
        if not self.persist:
            return
        symbols = {}
        for sym in sorted(self._by_symbol.keys()):
            snap = self._symbol_snapshot_dict(sym)
            symbols[sym] = {
                "highs": snap["highs"],
                "lows": snap["lows"],
                "consumed": snap["consumed"],
                "bar_count": snap["bar_count"],
                "swept_count": snap.get("swept_count", 0),
                "as_of": snap.get("as_of"),
            }
        payload = {
            "schema": ZONES_SCHEMA,
            "updated_at_utc": _utc_now_iso(),
            "source": self._persist_source,
            "consumed_retention_days": CONSUMED_RETENTION_DAYS,
            "symbols": symbols,
        }
        _atomic_write_json(self.active_path, payload)

    def _persist_symbol(self, symbol: str, *, as_of: Any = None, event: str = "zone_snapshot") -> None:
        if not self.persist:
            return
        payload = self._symbol_snapshot_dict(symbol, as_of=as_of)
        payload["event"] = event
        try:
            self._append_jsonl(payload)
            self._rewrite_active_file()
        except Exception as exc:
            logger.warning(
                "FourHourLiquidityBook persist failed symbol=%s path=%s: %s",
                symbol,
                self.jsonl_path,
                exc,
            )

    def flush_persist(self, *, as_of: Any = None) -> None:
        """Write current book state for all symbols (end of backtest / rebuild)."""
        if not self.persist:
            return
        for sym in sorted(self._by_symbol.keys()):
            self._persist_symbol(sym, as_of=as_of, event="zone_snapshot")

    def load_active_reference(self, path: Optional[str] = None) -> int:
        """
        Load active zones from ``liquidity_zones_active.json`` for live reference.

        Returns number of symbols loaded.
        """
        p = path or self.active_path
        if not os.path.isfile(p):
            logger.info("FourHourLiquidityBook no active zone file yet path=%s", p)
            return 0
        try:
            with open(p, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("FourHourLiquidityBook failed to load %s: %s", p, exc)
            return 0

        symbols = raw.get("symbols") if isinstance(raw, dict) else None
        if not isinstance(symbols, dict):
            return 0

        loaded = 0
        for sym, block in symbols.items():
            if not isinstance(block, dict):
                continue
            st = self._state(str(sym))
            highs: List[LiquidityZone] = []
            lows: List[LiquidityZone] = []
            for item in block.get("highs") or []:
                if not isinstance(item, dict):
                    continue
                z = self._zone_from_payload(item, default_side="high")
                if z is not None:
                    highs.append(z)
            for item in block.get("lows") or []:
                if not isinstance(item, dict):
                    continue
                z = self._zone_from_payload(item, default_side="low")
                if z is not None:
                    lows.append(z)

            consumed_keys: set = set()
            consumed_detail: Dict[str, ConsumedRecord] = {}
            for item in block.get("consumed") or []:
                if isinstance(item, dict):
                    z = self._zone_from_payload(
                        item, default_side=str(item.get("side") or "high")
                    )
                    if z is None:
                        continue
                    ck = f"{z.side}:{round(z.price, 2)}"
                    consumed_keys.add(ck)
                    consumed_detail[ck] = ConsumedRecord(
                        zone=z,
                        swept_at=str(item.get("swept_at") or z.bar_key or ""),
                    )
                else:
                    ck = str(item)
                    consumed_keys.add(ck)
            st.consumed = consumed_keys
            st.consumed_detail = consumed_detail
            st.high_zones = self._sort_zones_recent_first(
                [
                    z
                    for z in highs
                    if f"{z.side}:{round(z.price, 2)}" not in st.consumed
                ]
            )
            st.low_zones = self._sort_zones_recent_first(
                [
                    z
                    for z in lows
                    if f"{z.side}:{round(z.price, 2)}" not in st.consumed
                ]
            )
            loaded += 1
        logger.info(
            "FourHourLiquidityBook loaded active reference symbols=%s path=%s",
            loaded,
            p,
        )
        return loaded

    @staticmethod
    def _sweep_high(high: float, close: float, level: float) -> bool:
        return high > level and close < level

    @staticmethod
    def _sweep_low(low: float, close: float, level: float) -> bool:
        return low < level and close > level

    def detect_1m_sweep(
        self,
        symbol: str,
        candle: dict,
        *,
        enable_high: bool = True,
        enable_low: bool = True,
    ) -> Optional[Tuple[str, LiquidityZone]]:
        """
        Return (\"SHORT\"|\"LONG\", zone) when the 1m bar sweeps a 4H liquidity zone.

        ``enable_high`` / ``enable_low`` gate high→SHORT and low→LONG candidates.
        """
        if not enable_high and not enable_low:
            return None
        sym = str(symbol or "").strip().upper()
        ohlc = self._ohlc(candle)
        if not sym or ohlc is None:
            return None
        _o, h, l, c = ohlc
        st = self._state(sym)

        # Prefer nearest swept high (bearish) / low (bullish).
        swept_hi: Optional[LiquidityZone] = None
        if enable_high:
            for z in sorted(st.high_zones, key=lambda x: abs(x.price - c)):
                if self._sweep_high(h, c, z.price):
                    swept_hi = z
                    break
        swept_lo: Optional[LiquidityZone] = None
        if enable_low:
            for z in sorted(st.low_zones, key=lambda x: abs(x.price - c)):
                if self._sweep_low(l, c, z.price):
                    swept_lo = z
                    break

        if swept_hi is not None and swept_lo is not None:
            if abs(swept_hi.price - c) <= abs(swept_lo.price - c):
                return "SHORT", swept_hi
            return "LONG", swept_lo
        if swept_hi is not None:
            return "SHORT", swept_hi
        if swept_lo is not None:
            return "LONG", swept_lo
        return None

    def mark_consumed(
        self, symbol: str, zone: LiquidityZone, *, swept_at: Optional[str] = None
    ) -> None:
        st = self._state(symbol)
        if not self._mark_consumed_internal(st, zone, swept_at=swept_at):
            return
        self._persist_symbol(
            symbol,
            as_of=swept_at or zone.bar_key,
            event="zone_consumed",
        )

    def snapshot(self, symbol: str) -> Dict[str, List[float]]:
        st = self._state(symbol)
        return {
            "highs": [z.price for z in st.high_zones],
            "lows": [z.price for z in st.low_zones],
        }

    def rebuild_from_indicator_history(
        self,
        symbols: List[str],
        *,
        clear_log: bool = True,
        source: str = "backtest_rebuild",
    ) -> Dict[str, int]:
        """
        Walk ``logs/indicators/{SYM}/4h/indicator_history.jsonl`` and rebuild zones.

        Writes the shared JSONL + active JSON used by live.
        """
        self.set_persist_source(source)
        if clear_log and self.persist:
            for p in (self.jsonl_path, self.active_path):
                try:
                    if os.path.isfile(p):
                        os.remove(p)
                except OSError:
                    pass

        self._by_symbol.clear()
        counts: Dict[str, int] = {}
        for raw_sym in symbols:
            sym = str(raw_sym or "").strip().upper()
            if not sym:
                continue
            rows = ind_hist.load_indicator_history_rows(sym, "4h", max_rows=0)
            n = 0
            with self.suspend_persist():
                for row in rows:
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
                    candle = {
                        "symbol": sym,
                        "open": row.get("open"),
                        "high": row.get("high"),
                        "low": row.get("low"),
                        "close": row.get("close"),
                        "timestamp": ts,
                        "candle_timestamp_ist": ist_key,
                        "timeframe": "4h",
                    }
                    if self.on_4h_close(sym, candle):
                        n += 1
            counts[sym] = n
            snap = self.snapshot(sym)
            st = self._state(sym)
            recent = self._consumed_records_last_days(sym)
            swept_hi = [float(r.zone.price) for r in recent if r.zone.side == "high"]
            swept_lo = [float(r.zone.price) for r in recent if r.zone.side == "low"]
            logger.info(
                "FourHourLiquidityBook rebuild %s bars=%s "
                "active_hi=%s active_lo=%s consumed_10d_hi=%s consumed_10d_lo=%s "
                "swept_total=%s",
                sym,
                n,
                [round(x, 2) for x in snap["highs"]],
                [round(x, 2) for x in snap["lows"]],
                [round(x, 2) for x in swept_hi],
                [round(x, 2) for x in swept_lo],
                len(st.consumed),
            )
        self.flush_persist(as_of="rebuild_complete")
        return counts
