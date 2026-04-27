"""
Shared helpers and mixin for LiveEngine: pricing, depth, validation, candle checks.
Import LiveEngineHelpersMixin and use as: class LiveEngine(LiveEngineHelpersMixin, BaseEngine).
"""

import calendar
import csv
import datetime as dt
import logging
import os
import time
from datetime import timezone
from typing import Any, Dict, List, Optional, Tuple

import psutil

from core.data.candle_aggregator import _resolution_to_seconds

DEFAULT_FEED_STALE_SECONDS = 60
logger = logging.getLogger(__name__)

try:
    from logger.engine_logger import REPORTS_DIR
except ImportError:
    REPORTS_DIR = "reports"


# ---------- Time helpers ----------


def _parse_time(s: str) -> Tuple[int, int]:
    """Parse 'HH:MM' to (hour, minute)."""
    parts = s.strip().split(":")
    h = int(parts[0]) if parts else 0
    m = int(parts[1]) if len(parts) > 1 else 0
    return h, m


def _within_trading_hours_utc(now: dt.datetime, windows: List[Tuple[str, str]]) -> bool:
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
                print(">>exit ticker price ", ticker["close"])
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

        print(">>entry ask, bid", symbol, ask, bid)
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
        print(">exxit bid and ask", symbol, bid, ask)
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

    # ---------- Signal logging (entry and exit) ----------

    def _log_signal(
        self,
        intent: Any,
        symbol: str,
        action: str = "ENTRY",
        qty_fallback: Optional[int] = None,
    ) -> None:
        """
        Log a strategy-generated signal (entry or exit) as structured JSON.
        """
        _sym = (
            getattr(getattr(intent, "instrument", None), "trading_symbol", None)
            or symbol
        )
        _side = getattr(intent, "side", "").upper()
        _qty = getattr(intent, "qty", 0) or qty_fallback or 0
        _intent_id = getattr(intent, "intent_id", "")
        _price = getattr(intent, "price", None)
        _id_short = (
            f"{_intent_id[:16]}..."
            if _intent_id and len(_intent_id) > 16
            else _intent_id
        )
        _msg = (
            f"Signal: {action} {_sym} {_side} qty={_qty}"
            + (f" price={_price}" if _price is not None else "")
            + f" intent_id={_id_short}"
        )
        if getattr(self, "engine_logger", None):
            self.engine_logger.log(
                "signal_generated",
                _msg,
                symbol=_sym,
                side=_side,
                qty=_qty,
                intent_id=_intent_id,
                action=action,
                price=_price,
                strategy_id=getattr(intent, "strategy_id", None)
                or getattr(intent, "strategy", None),
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

    @staticmethod
    def _numeric_ts_to_utc_seconds(ts: float) -> float:
        """
        Normalize broker timestamps: unix seconds (~1e9), millis (~1e12), or micros (~1e15+).
        """
        t = float(ts)
        if t >= 1e15:
            return t / 1e6  # microseconds → seconds
        if t >= 1e12:
            return t / 1000.0  # milliseconds → seconds (common for WS / REST)
        return t

    @staticmethod
    def _coerce_scalar_to_float(raw: Any) -> Optional[float]:
        """Best-effort: Python int/float/numpy scalars → float; else None."""
        if raw is None:
            return None
        if isinstance(raw, bool):
            return None
        if isinstance(raw, (int, float)):
            return float(raw)
        try:
            if hasattr(raw, "item") and callable(raw.item):
                return float(raw.item())
        except Exception:
            pass
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def _dhan_repair_naive_as_ist_wallclock(self, naive: dt.datetime) -> dt.datetime:
        """
        Dhan WS ``last_trade_time`` / naive datetimes are often **IST wall components** but flow
        through code paths that compare against ``utcnow()`` as if they were UTC — producing a
        ~+19800s false \"forming\" bar. If naive is ~4.25–7.25h **ahead** of UTC now, interpret
        components as Asia/Kolkata and convert to naive UTC.
        """
        if str(getattr(self, "venue", "") or "").upper() != "DHAN":
            return naive
        nowu = dt.datetime.utcnow()
        dsec = (naive - nowu).total_seconds()
        if 4.25 * 3600 <= dsec <= 7.25 * 3600:
            try:
                from zoneinfo import ZoneInfo

                ist = ZoneInfo("Asia/Kolkata")
                return naive.replace(tzinfo=ist).astimezone(timezone.utc).replace(tzinfo=None)
            except Exception:
                return naive - dt.timedelta(seconds=19800)
        return naive

    def _candle_timestamp_to_utc_naive(self, ts: Any) -> Optional[dt.datetime]:
        """Parse any candle timestamp to naive UTC datetime for consistent comparisons."""
        if ts is None:
            return None
        num = LiveEngineHelpersMixin._coerce_scalar_to_float(ts)
        if num is not None:
            sec = self._numeric_ts_to_utc_seconds(num)
            naive = dt.datetime.fromtimestamp(sec, tz=dt.timezone.utc).replace(tzinfo=None)
            return self._dhan_repair_naive_as_ist_wallclock(naive)
        if isinstance(ts, dt.datetime):
            if ts.tzinfo is not None:
                return ts.astimezone(timezone.utc).replace(tzinfo=None)
            return self._dhan_repair_naive_as_ist_wallclock(ts)
        s = str(ts).strip()
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            parsed = dt.datetime.fromisoformat(s)
        except ValueError:
            return None
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return self._dhan_repair_naive_as_ist_wallclock(parsed)

    def _normalize_candle_timestamp_utc_naive(self, candle: Dict[str, Any]) -> None:
        """Rewrite candle['timestamp'] to normalized naive UTC (DHAN IST fix included)."""
        raw = candle.get("timestamp")
        out = self._candle_timestamp_to_utc_naive(raw)
        if out is not None:
            candle["timestamp"] = out

    def _now_utc_naive(self, now: Optional[dt.datetime]) -> dt.datetime:
        """Wall-clock 'now' as naive UTC (same basis as utcfromtimestamp outputs)."""
        if now is None:
            return dt.datetime.utcnow()
        if now.tzinfo is not None:
            return now.astimezone(timezone.utc).replace(tzinfo=None)
        return now

    def _is_closed_candle(
        self, candle: Dict, timeframe: str, now: Optional[dt.datetime] = None
    ) -> bool:
        """
        True if candle timestamp is on timeframe boundary and not in the future.

        - **Aggregator path**: ``bucket_ts`` is an integer unix *start* aligned to TF seconds;
          if present and divisible by the strategy TF (same seconds as ``CandleAggregator``),
          treat as aligned (canonical closed bar).
        - **Alignment**: unix second offset modulo ``tf_sec`` where ``tf_sec`` comes from
          ``_resolution_to_seconds`` (same map as ``TIMEFRAME_SECONDS`` / aggregator). This
          matches ``"15"``, ``"15m"``, ``"60"``, ``"1h"``, etc., unlike naive ``int(tf)``.
        """
        ts_raw = candle.get("timestamp")
        ts_utc = self._candle_timestamp_to_utc_naive(ts_raw)
        if ts_utc is None:
            return False
        now_utc = self._now_utc_naive(now)
        if ts_utc > now_utc:
            return False

        tf_sec = int(_resolution_to_seconds(timeframe))
        if tf_sec <= 0:
            tf_sec = 60

        bt = candle.get("bucket_ts")
        if bt is not None:
            try:
                int(float(bt))
                # bucket_ts originates from CandleAggregator/engine bucketing and can be
                # session-anchored (e.g. NSE/BSE 1h at 09:15), so do not require epoch modulus.
                return True
            except (TypeError, ValueError):
                pass

        epoch = dt.datetime(1970, 1, 1)
        unix_s = int((ts_utc - epoch).total_seconds())
        return (unix_s % tf_sec) == 0

    def _closed_candle_diagnostics(
        self,
        candle: Dict,
        timeframe: str,
        now: Optional[dt.datetime],
        *,
        use_aggregator: bool,
        candle_source: str,
    ) -> Dict[str, Any]:
        """
        Structured fields for logs when ``_is_closed_candle`` fails (feed snapshot + math).
        """
        ts_raw = candle.get("timestamp")
        ts_utc = self._candle_timestamp_to_utc_naive(ts_raw)
        tf_sec = int(_resolution_to_seconds(timeframe))
        if tf_sec <= 0:
            tf_sec = 60
        out: Dict[str, Any] = {
            "use_aggregator": use_aggregator,
            "candle_source": candle_source,
            "timeframe": str(timeframe),
            "tf_sec": tf_sec,
            "ts_raw": repr(ts_raw)[:300],
            "bucket_ts": candle.get("bucket_ts"),
            "ohlc": {
                "o": candle.get("open"),
                "h": candle.get("high"),
                "l": candle.get("low"),
                "c": candle.get("close"),
                "v": candle.get("volume"),
            },
        }
        if ts_utc is None:
            out["skip_reason"] = "missing_ts"
            return out
        now_utc = self._now_utc_naive(now)
        out["ts_utc_naive"] = ts_utc.isoformat()
        out["now_utc_naive"] = now_utc.isoformat()
        out["forming"] = bool(ts_utc > now_utc)
        try:
            out["delta_ts_minus_now_sec"] = (ts_utc - now_utc).total_seconds()
        except Exception:
            pass
        bt = candle.get("bucket_ts")
        if bt is not None:
            try:
                b = int(float(bt))
                out["bucket_mod_tf"] = b % tf_sec
            except (TypeError, ValueError):
                out["bucket_mod_tf"] = None
        epoch = dt.datetime(1970, 1, 1)
        unix_s = int((ts_utc - epoch).total_seconds())
        out["unix_s_mod_tf"] = unix_s % tf_sec
        if ts_utc > now_utc:
            out["skip_reason"] = "forming"
        elif bt is not None:
            try:
                int(float(bt))
                out["skip_reason"] = "unexpected_should_pass"
            except (TypeError, ValueError):
                out["skip_reason"] = "misaligned"
        else:
            out["skip_reason"] = (
                "misaligned" if (unix_s % tf_sec) != 0 else "unexpected_should_pass"
            )
        return out

    def _tf_to_minutes(self, tf: str) -> int:
        """Minutes per bar; consistent with ``CandleAggregator`` / ``_resolution_to_seconds``."""
        sec = int(_resolution_to_seconds(tf))
        return max(1, sec // 60)

    def _within_trading_hours(self) -> bool:
        if not self.allowed_trading_hours:
            return True
        now = dt.datetime.utcnow()
        return _within_trading_hours_utc(now, self.allowed_trading_hours)

    def _is_market_open_for_feed_health(self) -> bool:
        """
        When False, skip feed staleness checks (no ticks overnight is expected).
        If allowed_trading_hours is set, use that; else DHAN→NSE index session, DELTA→DELTA calendar.
        """
        if self.allowed_trading_hours:
            return self._within_trading_hours()
        v = str(getattr(self, "venue", None) or "").upper()
        try:
            from core.utils.session.session_manager import SessionManager

            if v == "DHAN":
                return SessionManager.is_market_open("INDEX")
            if v == "DELTA":
                return SessionManager.is_market_open("DELTA")
        except Exception:
            return True
        return True

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

    # ---------- Candle / feed utility helpers ----------

    @staticmethod
    def _candle_bucket_start_unix(candle: Dict[str, Any]) -> Optional[int]:
        bt = candle.get("bucket_ts")
        if bt is not None:
            try:
                return int(bt)
            except (TypeError, ValueError):
                pass
        ts = candle.get("timestamp")
        if isinstance(ts, dt.datetime):
            u = ts
            if u.tzinfo is not None:
                u = u.astimezone(timezone.utc).replace(tzinfo=None)
            # Naive components are treated as UTC wall (same basis as utcfromtimestamp).
            return int(calendar.timegm(u.timetuple()))
        if isinstance(ts, (int, float)):
            sec = LiveEngineHelpersMixin._numeric_ts_to_utc_seconds(float(ts))
            return int(sec)
        num = LiveEngineHelpersMixin._coerce_scalar_to_float(ts)
        if num is not None:
            sec = LiveEngineHelpersMixin._numeric_ts_to_utc_seconds(num)
            return int(sec)
        return None

    def _live_bar_is_stale_or_replay(
        self, symbol: str, candle: Dict[str, Any], tf: str
    ) -> bool:
        """
        When ticks + CandleAggregator are active, reject:
        - REST fallback rows without bucket_ts after we have seen real buckets
        - bar bucket time going backwards (duplicate old bar after restart)
        - "last closed" rows far behind wall clock (stale historical replay)
        """
        max_seen = self._max_candle_bucket_unix.get(symbol)
        bt = candle.get("bucket_ts")
        bs = self._candle_bucket_start_unix(candle)

        if bt is None and self._has_seen_aggregator_bucket.get(symbol):
            logger.debug(
                "Skip %s: missing bucket_ts after live aggregated bars (REST replay)",
                symbol,
            )
            return True

        if bs is None:
            return False

        if max_seen is not None and bs < max_seen:
            logger.debug(
                "Skip %s: non-monotonic bucket %s < max_seen %s",
                symbol,
                bs,
                max_seen,
            )
            return True

        tf_sec = max(60, int(_resolution_to_seconds(tf)))
        age_sec = time.time() - float(bs)
        stale_sec = max(15 * 60, 5 * tf_sec)
        if age_sec > stale_sec:
            logger.debug(
                "Skip %s: stale bar wall_age=%.0fs > %s (bucket=%s)",
                symbol,
                age_sec,
                stale_sec,
                bs,
            )
            return True

        return False

    def _should_log_closed_candle(
        self, symbol: str, tf: Optional[str], candle: Dict[str, Any]
    ) -> bool:
        """
        Log one candle per (symbol, timeframe, bucket).
        Prevents writing the same closed candle every engine loop cycle.
        """
        bucket = self._candle_bucket_start_unix(candle)
        if bucket is None:
            return False
        tf_key = str(tf or "NA")
        key = f"{symbol}|{tf_key}"
        prev = self._last_logged_candle_bucket.get(key)
        if prev == bucket:
            return False
        self._last_logged_candle_bucket[key] = bucket
        return True

    def _should_log_closed_candle_skip(
        self,
        symbol: str,
        tf: Optional[str],
        candle: Dict[str, Any],
        *,
        skip_reason: Optional[str] = None,
    ) -> bool:
        """
        Rate-limit ``closed_candle_skip`` JSON logs. Without this, a non-aligned or forming
        bar in a tight engine loop can emit hundreds of identical lines per second.
        """
        bucket = self._candle_bucket_start_unix(candle)
        reason = str(skip_reason or "unknown")
        bucket_key = str(bucket) if bucket is not None else "none"
        # Stable key prevents per-second timestamp churn when bucket_ts is missing.
        key = f"{symbol}|{tf or 'NA'}|{reason}|{bucket_key}"
        now = time.time()
        d = getattr(self, "_last_closed_candle_skip_ts", None)
        if d is None:
            d = {}
            self._last_closed_candle_skip_ts = d
        last = d.get(key, 0.0)
        if now - last < 120.0:
            return False
        d[key] = now
        return True

    def _check_memory(self) -> None:
        if self.memory_threshold_percent is None or self.memory_threshold_percent <= 0:
            return
        try:
            proc = psutil.Process()
            usage = proc.memory_percent()
            if usage >= self.memory_threshold_percent:
                self._entries_paused_memory = True
                if self.engine_logger:
                    self.engine_logger.memory_pressure_warning(
                        f"Memory usage {usage:.1f}% >= {self.memory_threshold_percent}%",
                        usage_percent=usage,
                    )
            else:
                self._entries_paused_memory = False
        except Exception as e:
            logger.debug("Memory check failed: %s", e)

    def _notify_dhan_feed_connection_state(self) -> None:
        """Send Telegram updates for Dhan feed connect/disconnect transitions."""
        if str(self.venue or "").upper() != "DHAN":
            return
        if not self.realtime_feed or not hasattr(self.realtime_feed, "is_connected"):
            return
        try:
            connected = bool(self.realtime_feed.is_connected())
        except Exception:
            return

        gen = int(getattr(self.realtime_feed, "connect_generation", 0) or 0)

        if connected:
            became_connected = self._dhan_feed_was_connected is not True
            new_generation = (
                gen > 0 and gen > self._dhan_feed_last_connect_generation_alerted
            )
            if became_connected or new_generation:
                msg = (
                    f"✅ Dhan feed connected and started | engine={self.engine_id} | "
                    f"symbols={len(self.symbols)} | generation={gen}"
                )
                if self.engine_logger:
                    self.engine_logger.feed_health_recovered(msg)
                if gen > 0:
                    self._dhan_feed_last_connect_generation_alerted = gen
        else:
            if self._dhan_feed_was_connected is True:
                msg = (
                    f"⚠️ Dhan feed disconnected/stopped | engine={self.engine_id} "
                    f"| last_generation={gen or self._dhan_feed_last_connect_generation_alerted}"
                )
                if self.engine_logger:
                    self.engine_logger.websocket_disconnect(msg)

        self._dhan_feed_was_connected = connected

    def check_feed_health(self) -> None:
        """Warn if no tick/candle received for feed_stale_seconds; optionally pause entries."""
        # Dhan feed lifecycle alerts (connected/disconnected/reconnected).
        self._notify_dhan_feed_connection_state()
        if not self._is_market_open_for_feed_health():
            self._entries_paused_feed_stale = False
            for symbol in self.symbols:
                if symbol in self._symbol_state:
                    self._symbol_state[symbol]["feed_stale"] = False
            return
        if not self.realtime_feed or not self.realtime_feed.is_connected():
            return
        now = time.time()
        any_stale = False
        for symbol in self.symbols:
            last_tick = self._last_tick_timestamp.get(symbol, 0)
            last_candle = self._last_candle_timestamp.get(symbol, 0)
            stale = (now - max(last_tick, last_candle)) > self.feed_stale_seconds
            if symbol not in self._symbol_state:
                self._symbol_state[symbol] = {
                    "paused": False,
                    "feed_stale": False,
                    "error_count": 0,
                }
            was_stale = bool(self._symbol_state[symbol].get("feed_stale"))
            has_data = bool(last_tick or last_candle)
            if stale and has_data:
                any_stale = True
                if (not was_stale) and self.engine_logger:
                    self.engine_logger.feed_health_warning(
                        f"No data for {symbol} in {self.feed_stale_seconds}s",
                        symbol=symbol,
                    )
                self._symbol_state[symbol]["feed_stale"] = True
            else:
                if was_stale and has_data:
                    if self.engine_logger:
                        self.engine_logger.feed_health_recovered(
                            f"Data recovered for {symbol}",
                            symbol=symbol,
                        )
                self._symbol_state[symbol]["feed_stale"] = False
        self._entries_paused_feed_stale = any_stale

    def _do_exit_order_refresh(self) -> None:
        """Every 1 min, re-quote open exit orders at near bid/ask until they fill."""
        now = time.time()
        if now - self._last_exit_refresh_time < self._exit_refresh_interval_seconds:
            return
        self._last_exit_refresh_time = now
        self.order_router.refresh_stale_exit_orders(
            get_bid_ask=self._get_bid_ask,
            stale_seconds=float(self._exit_refresh_interval_seconds),
        )

    def _log_startup_balance_snapshot(self) -> None:
        """One-time startup balance check/log for observability before live loop."""
        broker = getattr(self.order_router, "broker", None)
        if not broker or not hasattr(broker, "get_balance_snapshot"):
            return
        try:
            snapshot = broker.get_balance_snapshot()
        except Exception as e:
            if self.engine_logger:
                self.engine_logger.log("risk_block", f"Startup balance check failed: {e}")
            else:
                logger.warning("Startup balance check failed: %s", e)
            return
        if not snapshot:
            return
        sel = snapshot.get("selected_available")
        usd = snapshot.get("usd_available")
        inr = snapshot.get("inr_available")
        parts = [f"selected={sel}"]
        if usd is not None:
            parts.append(f"usd={usd}")
        parts.append(f"inr={inr}")
        msg = "Startup balance snapshot: " + " ".join(parts)
        if self.engine_logger:
            self.engine_logger.log("oms", msg)
        else:
            logger.info(msg)

    def _export_eod(self, date_str: str) -> None:
        """Export open positions, realized pnl to reports/{engine_id}_{date}.csv."""
        reports_dir = REPORTS_DIR
        os.makedirs(reports_dir, exist_ok=True)
        path = os.path.join(reports_dir, f"{self.engine_id}_{date_str}.csv")
        rows = []
        for sym, pos in self.position_manager.positions.items():
            if pos.net_qty == 0:
                continue
            rows.append(
                {
                    "symbol": sym,
                    "qty": pos.net_qty,
                    "avg_price": pos.avg_price,
                    "realized_pnl": pos.realized_pnl,
                    "unrealized_pnl": "",
                }
            )
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "symbol",
                    "qty",
                    "avg_price",
                    "realized_pnl",
                    "unrealized_pnl",
                ],
            )
            w.writeheader()
            w.writerows(rows)
        if self.engine_logger:
            self.engine_logger.eod_export(path)

    def _drain_tick_queue(self) -> None:
        """Drain tick queue into candle_aggregator (single state owner). Non-blocking; cap per cycle."""
        if not self.tick_queue or not self.candle_aggregator:
            return
        if not hasattr(self, "_tick_debug_count"):
            self._tick_debug_count = 0
            self._tick_debug_last_log = time.time()
        for _ in range(self._max_ticks_per_cycle):
            try:
                tick = self.tick_queue.get_nowait()
            except Exception:
                break
            try:
                s = tick.get("symbol")
                p = tick.get("price")
                v = tick.get("volume", 0)
                ts = tick.get("timestamp")
                if s is not None and p is not None and ts is not None:
                    self.candle_aggregator.on_tick(s, p, v, ts)
                    self._last_tick_timestamp[s] = time.time()
                    self._tick_debug_count += 1
                    now = time.time()
                    if now - self._tick_debug_last_log >= 1800:
                        msg = f"Tick health: {self._tick_debug_count} ticks in last 5s"
                        if self.engine_logger:
                            self.engine_logger.log("tick_health", msg)
                        else:
                            logger.info(msg)
                        self._tick_debug_count = 0
                        self._tick_debug_last_log = now
            except Exception as e:
                logger.debug("Invalid tick or aggregator error: %s", e)
