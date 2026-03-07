"""
Shared helpers and mixin for LiveEngine: pricing, depth, validation, candle checks.
Import LiveEngineHelpersMixin and use as: class LiveEngine(LiveEngineHelpersMixin, BaseEngine).
"""

import datetime as dt
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_FEED_STALE_SECONDS = 60


# ---------- Time helpers ----------


def _parse_time(s: str) -> Tuple[int, int]:
    """Parse 'HH:MM' to (hour, minute)."""
    parts = s.strip().split(":")
    h = int(parts[0]) if parts else 0
    m = int(parts[1]) if len(parts) > 1 else 0
    return h, m


def _within_trading_hours_utc(
    now: dt.datetime, windows: List[Tuple[str, str]]
) -> bool:
    """True if now (UTC) falls within any (start, end) window. Times in 'HH:MM' UTC."""
    if not windows:
        return True
    hour, minute = now.hour, now.minute
    now_mins = hour * 60 + minute
    for start, end in windows:
        sh, sm = _parse_time(start)
        eh, em = _parse_time(end)
        start_mins = sh * 60 + sm
        end_mins = eh * 60 + em
        if start_mins <= end_mins:
            if start_mins <= now_mins <= end_mins:
                return True
        else:
            if now_mins >= start_mins or now_mins <= end_mins:
                return True
    return False


class LiveEngineHelpersMixin:
    """
    Mixin for LiveEngine: pricing from depth, tick/lot validation, spread check,
    candle integrity, signal hash, trading hours. Requires self.realtime_feed,
    self.data, self.instrument_store, self.venue, self.engine_logger,
    self.allowed_trading_hours, self._tick_cache.
    """

    # ---------- Market data helpers ----------

    def _get_bid_ask(self, symbol: str) -> Tuple[Optional[float], Optional[float]]:
        """Return (best_bid, best_ask) for symbol from feed; (None, None) if unavailable."""
        if self.realtime_feed and hasattr(self.realtime_feed, "get_best_bid"):
            try:
                bid = self.realtime_feed.get_best_bid(symbol)
                ask = self.realtime_feed.get_best_ask(symbol)
                return (bid, ask)
            except Exception:
                pass
        return (None, None)

    def _get_tick_size(self, symbol: str) -> float:
        """Return tick size for symbol from cache (populated at startup); fill cache on first miss."""
        if symbol in self._tick_cache:
            return self._tick_cache[symbol]
        tick = None
        if self.instrument_store and hasattr(self.instrument_store, "get_tick_size"):
            try:
                tick = self.instrument_store.get_tick_size(symbol)
            except Exception:
                pass
        self._tick_cache[symbol] = float(tick) if tick is not None else 0.01
        return self._tick_cache[symbol]

    def get_price_map(self, symbol):
        if self.realtime_feed and self.realtime_feed.is_connected():
            ticker = self.realtime_feed.get_last_ticker(symbol)
            if ticker and ticker.get("close") is not None:
                return ticker["close"]
        if self.data:
            candles = self.data.get_latest_candles([symbol])
            if (
                candles
                and symbol in candles
                and candles[symbol].get("close") is not None
            ):
                return candles[symbol]["close"]
        return None

    # ---------- Execution helpers ----------

    def _entry_price_from_depth(self, symbol: str, is_buy: bool):
        bid, ask = self._get_bid_ask(symbol)
        if not self._is_spread_acceptable(bid, ask):
            return None
        tick = self._get_tick_size(symbol)

        if is_buy and ask is not None:
            return ask + tick
        if not is_buy and bid is not None:
            return bid - tick

        return None

    def _exit_price_from_depth(self, symbol: str, is_sell: bool):
        bid, ask = self._get_bid_ask(symbol)
        if not self._is_spread_acceptable(bid, ask):
            return None
        tick = self._get_tick_size(symbol)

        if is_sell and bid is not None:
            return bid - tick

        if not is_sell and ask is not None:
            return ask + tick

        return None

    def _is_spread_acceptable(
        self,
        bid: Optional[float],
        ask: Optional[float],
        max_spread_pct: float = 0.1,
    ) -> bool:
        """True if both bid/ask exist and spread <= max_spread_pct * bid. Blocks wide spreads (e.g. options)."""
        if bid is None or ask is None or bid <= 0:
            return False
        spread = ask - bid
        return spread <= bid * max_spread_pct

    def _validate_lot_size(self, intent: Any, trading_sym: str) -> None:
        """Raise ValueError if intent.qty is not a multiple of instrument lot size."""
        lot = 1
        if self.instrument_store and hasattr(self.instrument_store, "get_lot_size"):
            try:
                lot = self.instrument_store.get_lot_size(trading_sym)
            except Exception:
                pass
        if lot is None:
            lot = getattr(getattr(intent, "instrument", None), "lot_size", 1) or 1
        qty = getattr(intent, "qty", 0)
        if lot and qty % lot != 0:
            raise ValueError(
                f"Invalid lot size: qty {qty} not multiple of lot {lot} for {trading_sym}"
            )

    # ---------- Strategy helpers ----------

    def _signal_hash(
        self, symbol: str, timeframe: str, candle_ts: Any, signal_type: str
    ) -> int:
        """Hash for duplicate signal detection. Override candle_ts for bar identity."""
        ts = getattr(candle_ts, "timestamp", None) or (
            candle_ts if isinstance(candle_ts, (int, float)) else str(candle_ts)
        )
        return hash((symbol, str(timeframe), str(ts), str(signal_type)))

    def _intent_has_entry(self, intent) -> bool:
        """True if intent is an ENTRY or (when intent is a list) any item has action ENTRY."""
        if intent is None:
            return False
        if isinstance(intent, list):
            return any(getattr(i, "action", None) == "ENTRY" for i in intent)
        return getattr(intent, "action", None) == "ENTRY"

    def _validate_candle_integrity(
        self, candle: Dict, symbol: Optional[str] = None
    ) -> bool:
        """
        Validate OHLC consistency: high >= max(open,close), low <= min(open,close).
        Returns True if valid; on failure logs candle_integrity_error and returns False.
        """
        o = candle.get("open")
        h = candle.get("high")
        l = candle.get("low")
        c = candle.get("close")
        if o is None or h is None or l is None or c is None:
            return True
        try:
            o, h, l, c = float(o), float(h), float(l), float(c)
        except (TypeError, ValueError):
            return True
        if h < max(o, c) or l > min(o, c):
            if self.engine_logger:
                self.engine_logger.candle_integrity_error(
                    "OHLC inconsistent: high < max(o,c) or low > min(o,c)",
                    symbol=symbol,
                    details={"open": o, "high": h, "low": l, "close": c},
                )
            return False
        return True

    def _is_closed_candle(
        self, candle: Dict, timeframe: str, now: Optional[dt.datetime] = None
    ) -> bool:
        """
        True if candle timestamp is on timeframe boundary and not in the future.
        Reject forming candles (timestamp > expected close time).
        """
        ts = candle.get("timestamp")
        if ts is None:
            return False
        if isinstance(ts, (int, float)):
            if ts > 1e12:
                ts_dt = dt.datetime.utcfromtimestamp(ts / 1e6)
            else:
                ts_dt = dt.datetime.utcfromtimestamp(ts)
        else:
            ts_dt = (
                ts
                if isinstance(ts, dt.datetime)
                else dt.datetime.fromisoformat(str(ts))
            )
        now = now or dt.datetime.utcnow()
        if ts_dt.tzinfo:
            now = now.replace(tzinfo=ts_dt.tzinfo) if not now.tzinfo else now
        if ts_dt > now:
            return False
        tf_min = self._tf_to_minutes(timeframe)
        if tf_min <= 0:
            return True
        epoch = dt.datetime(1970, 1, 1, tzinfo=ts_dt.tzinfo if ts_dt.tzinfo else None)
        mins = int((ts_dt - epoch).total_seconds() / 60)
        return (mins % tf_min) == 0

    def _tf_to_minutes(self, tf: str) -> int:
        tf = str(tf).lower()
        if tf.endswith("h"):
            return int(tf[:-1]) * 60
        try:
            return int(tf)
        except ValueError:
            return 60

    def _within_trading_hours(self) -> bool:
        if not self.allowed_trading_hours:
            return True
        now = dt.datetime.utcnow()
        return _within_trading_hours_utc(now, self.allowed_trading_hours)

    # ---------- Candle enrichment ----------

    def _enrich_candle_depth(self, symbol: str, candle: Dict[str, Any]) -> None:
        """For Delta: set candle['best_bid'] and candle['best_ask'] from L2."""
        if (
            self.venue != "DELTA"
            or not self.realtime_feed
            or not hasattr(self.realtime_feed, "get_best_bid")
        ):
            return
        try:
            bid = self.realtime_feed.get_best_bid(symbol)
            ask = self.realtime_feed.get_best_ask(symbol)
            if bid is not None:
                candle["best_bid"] = bid
            if ask is not None:
                candle["best_ask"] = ask
        except Exception:
            pass
