"""
Structured JSON logging per strategy. One rotating file per strategy: logs/{strategy_id}/{strategy_id}.log.
Closed candles: logs/{strategy_id}/{strategy_id}_candles.log — single append-only file (see candle_created).
Engine events rotate daily at midnight UTC. Multi-strategy engines route each event only to its payload ``strategy_id`` file.
No print(); all events logged as one JSON object per line.
For ``candle_closed`` rows, ``timestamp`` and ``bar_timestamp_ist`` use IST wall time as ``YYYY-MM-DD HH:MM`` (no seconds). Other events still use full ISO-8601 with offset in ``timestamp``.
"""

import json
import logging
import os
import threading
import time
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

try:
    from core.data.candle_aggregator import _resolution_to_seconds
except ImportError:
    _resolution_to_seconds = None  # type: ignore

try:
    from core.utils.json_numeric import round_json_floats
except ImportError:
    round_json_floats = None  # type: ignore

IST = ZoneInfo("Asia/Kolkata")
IST_MINUTE_FMT = "%Y-%m-%d %H:%M"

LOGS_DIR = "logs"
REPORTS_DIR = "reports"

# Only strategy-originated events should be hard-required to carry strategy_id.
STRATEGY_EVENTS = {
    "signal_generated",
    "intent_created",
    "intent_routed",
    "order_placed",
    "order_failed",
}

EVENT_CORRELATION_RULES: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "signal_generated": {
        "required": ("engine_id", "strategy_id"),
        "optional": ("intent_id", "account_id"),
    },
    "intent_created": {
        "required": ("engine_id", "strategy_id", "intent_id"),
        "optional": ("account_id",),
    },
    "intent_routed": {
        "required": ("engine_id", "strategy_id", "intent_id", "account_id"),
        "optional": (),
    },
    "order_placed": {
        "required": ("engine_id", "strategy_id", "intent_id"),
        "optional": ("account_id",),
    },
    "order_failed": {
        "required": ("engine_id", "strategy_id", "intent_id"),
        "optional": ("account_id",),
    },
    "order_filled": {
        "required": ("engine_id", "intent_id"),
        "optional": ("strategy_id", "account_id"),
    },
    "latency_breakdown": {
        "required": ("engine_id", "strategy_id", "intent_id", "account_id"),
        "optional": (),
    },
}

EVENT_TYPE_ALIASES = {
    "candle_created": "candle_closed",
    "closed_candle_skip": "candle_closed_skipped",
    "feed_health_warning": "feed_stalled",
    "feed_health_recovered": "feed_recovered",
}

TELEGRAM_ALERT_EVENTS = {
    "engine_start",
    "graceful_shutdown",
    "signal_generated",
    "feed_stalled",
    "feed_recovered",
    "websocket_disconnect",
    "order_placed",
    "order_failed",
    "order_rejected",
    "risk_block",
    "kill_switch",
    "candle_closed",
}

# DELTA: 24/7 1m bars — candle_closed Telegram spam is not useful; file logs remain.
TELEGRAM_ALERT_EVENTS_DELTA_EXCLUDE = frozenset({"candle_closed"})

# Routine heartbeat / per-bar noise — omitted from strategy *.log unless debug_mode.
FILE_LOG_VERBOSE_EVENTS = frozenset(
    {
        "pipeline_state",
        "strategy_evaluated",
        "candle_skipped",
        "candle_closed_skipped",
        "closed_candle_skip_summary",
        "latency",
        "oms",
        "scheduled_eval",
        "scheduled_eval_skipped",
        "tick_gap_detected",
        "candle_building",
        "session_end_candle_flush",
    }
)


def _safe_dir_name(name: Optional[str]) -> str:
    raw = str(name or "GLOBAL").strip() or "GLOBAL"
    return raw.replace("/", "_").replace("\\", "_").replace(" ", "_")


class EngineLogger:
    """
    Per-strategy structured logger. Thread-safe. Writes JSON lines to logs/{strategy_id}/{strategy_id}.log.
    """

    def __init__(
        self,
        engine_id: str,
        venue: str,
        strategy: str,
        log_dir: Optional[str] = None,
        telegram_alert: Optional[Callable[[str], None]] = None,
        known_strategies: Optional[Sequence[str]] = None,
        debug_mode: bool = False,
    ):
        self.engine_id = engine_id
        self.venue = venue
        self.strategy = strategy
        self._debug_mode = bool(debug_mode)
        self._telegram_alert = telegram_alert
        self._base_log_root = log_dir or LOGS_DIR
        self._known_strategies: List[str] = []
        seen: set[str] = set()
        for raw in [strategy, *(known_strategies or [])]:
            sid = str(raw or "").strip()
            if sid and sid not in seen:
                seen.add(sid)
                self._known_strategies.append(sid)
        self._known_strategy_ids = set(self._known_strategies)
        self._lock = threading.Lock()
        self._line_formatter = logging.Formatter("%(message)s")
        self._file_handlers: Dict[str, TimedRotatingFileHandler] = {}
        # symbol -> {count, window_start, last_emit, last_ohlc}
        self._integrity_error_stats: Dict[str, Dict[str, Any]] = {}
        self._integrity_error_interval_sec = 300.0

    def _strategy_log_dir(self, strategy_id: str) -> str:
        return os.path.join(self._base_log_root, _safe_dir_name(strategy_id))

    def _event_log_path(self, strategy_id: str) -> str:
        sid = _safe_dir_name(strategy_id)
        return os.path.join(self._strategy_log_dir(sid), f"{sid}.log")

    def _candles_log_path(self, strategy_id: Optional[str] = None) -> str:
        sid = _safe_dir_name(strategy_id or self.strategy)
        return os.path.join(self._strategy_log_dir(sid), f"{sid}_candles.log")

    def notify_operator(self, message: str) -> None:
        """Send an out-of-band operator alert (not limited to TELEGRAM_ALERT_EVENTS)."""
        if not self._telegram_alert or not message:
            return
        try:
            self._telegram_alert(str(message))
        except Exception:
            pass

    def _get_file_handler(self, path: str) -> TimedRotatingFileHandler:
        handler = self._file_handlers.get(path)
        if handler is not None:
            return handler
        os.makedirs(os.path.dirname(path), exist_ok=True)
        handler = TimedRotatingFileHandler(
            filename=path,
            when="midnight",
            interval=1,
            backupCount=14,
            encoding="utf-8",
            utc=True,
        )
        handler.setFormatter(self._line_formatter)
        self._file_handlers[path] = handler
        return handler

    def _emit_line(self, path: str, line: str) -> None:
        handler = self._get_file_handler(path)
        record = logging.LogRecord(
            name="engine_json",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg=line.rstrip("\n"),
            args=(),
            exc_info=None,
        )
        handler.emit(record)

    def _append_line(self, path: str, line: str) -> None:
        """Append one line to a non-rotating log file (used for closed-candle history)."""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line if line.endswith("\n") else line + "\n")

    @staticmethod
    def _is_missing(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        return False

    def _validate_correlation(self, payload: Dict[str, Any]) -> None:
        event_type = str(payload.get("event_type") or "")
        rules = EVENT_CORRELATION_RULES.get(event_type)
        if not rules:
            return
        missing = [
            key
            for key in rules.get("required", ())
            if self._is_missing(payload.get(key))
        ]
        if missing:
            raise ValueError(
                f"Missing required correlation fields for event_type={event_type}: {missing}"
            )

    def _infer_strategy_id(self, kwargs: Dict[str, Any], message: str = "") -> Optional[str]:
        """Resolve target log file strategy when call sites omit ``strategy_id``."""
        sid = kwargs.get("strategy_id") or kwargs.get("strategy")
        if sid and str(sid).strip():
            return str(sid).strip()
        stid = kwargs.get("structure_id")
        if stid:
            prefix = str(stid).split(":")[0]
            if prefix in self._known_strategy_ids:
                return prefix
        sym = str(kwargs.get("symbol") or "").upper()
        if sym.startswith("BANKNIFTY") and "BankNiftyBTST" in self._known_strategy_ids:
            return "BankNiftyBTST"
        if sym.startswith("NIFTY") and "LEAPS_RSI" in self._known_strategy_ids:
            return "LEAPS_RSI"
        msg = str(message or "")
        if "BankNiftyBTST" in msg and "BankNiftyBTST" in self._known_strategy_ids:
            return "BankNiftyBTST"
        if "LEAPS_RSI" in msg and "LEAPS_RSI" in self._known_strategy_ids:
            return "LEAPS_RSI"
        for ks in self._known_strategies:
            if f"strategy={ks}" in msg or f"strategy_id={ks}" in msg:
                return ks
        return None

    def _payload(
        self,
        event_type: str,
        message: str = "",
        strategy_id: Optional[str] = None,
        symbol: Optional[str] = None,
        side: Optional[str] = None,
        qty: Optional[int] = None,
        price: Optional[float] = None,
        order_id: Optional[str] = None,
        intent_id: Optional[str] = None,
        account_id: Optional[str] = None,
        **extra,
    ) -> Dict[str, Any]:
        base = {
            "engine_id": self.engine_id,
            "venue": self.venue,
            "strategy_id": strategy_id or self.strategy,
            "event_type": event_type,
            "timestamp": datetime.now(IST).isoformat(),
        }
        if message:
            base["message"] = message
        if symbol is not None:
            base["symbol"] = symbol
        if side is not None:
            base["side"] = side
        if qty is not None:
            base["qty"] = qty
        if price is not None:
            base["price"] = price
        if order_id is not None:
            base["order_id"] = order_id
        if intent_id is not None:
            base["intent_id"] = intent_id
        if account_id is not None:
            base["account_id"] = account_id
        base.update(extra)
        base["correlation"] = {
            "engine_id": base.get("engine_id"),
            "strategy_id": base.get("strategy_id"),
            "intent_id": base.get("intent_id"),
            "account_id": base.get("account_id"),
        }
        return base

    def log(self, event_type: str, message: str = "", **kwargs) -> None:
        # Backward compatibility: old call-sites may still pass "strategy".
        if "strategy" in kwargs and "strategy_id" not in kwargs:
            kwargs["strategy_id"] = kwargs.pop("strategy")
        inferred = self._infer_strategy_id(kwargs, message)
        if inferred:
            kwargs["strategy_id"] = inferred
        event_type = EVENT_TYPE_ALIASES.get(event_type, event_type)
        if event_type in STRATEGY_EVENTS:
            assert kwargs.get("strategy_id") is not None, (
                f"Missing strategy_id for strategy event_type={event_type}"
            )
        payload = self._payload(event_type, message=message, **kwargs)
        self._validate_correlation(payload)
        if round_json_floats is not None:
            payload = round_json_floats(payload)
        write_file = (
            self._debug_mode or event_type not in FILE_LOG_VERBOSE_EVENTS
        )
        if write_file:
            line = json.dumps(payload, default=str) + "\n"
            target_strategy = (
                str(payload.get("strategy_id") or self.strategy).strip() or self.strategy
            )
            target_path = self._event_log_path(target_strategy)
            with self._lock:
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                self._emit_line(target_path, line)
        self._send_telegram_alert(payload)

    def error(self, event_type: str, message: str = "", **kwargs) -> None:
        """Structured error event wrapper."""
        self.log(event_type, message=message, severity="error", **kwargs)

    def info(self, event_type: str, message: str = "", **kwargs) -> None:
        """Structured info event wrapper."""
        self.log(event_type, message=message, severity="info", **kwargs)

    def _send_telegram_alert(self, payload: Dict[str, Any]) -> None:
        if not self._telegram_alert:
            return
        event_type = str(payload.get("event_type") or "")
        if event_type not in TELEGRAM_ALERT_EVENTS:
            return
        if (
            str(self.venue or "").upper() == "DELTA"
            and event_type in TELEGRAM_ALERT_EVENTS_DELTA_EXCLUDE
        ):
            return
        parts = [
            f"[{self.venue}] {self.engine_id}",
            f"event={event_type}",
        ]
        strategy_id = payload.get("strategy_id")
        if strategy_id:
            parts.append(f"strategy={strategy_id}")
        symbol = payload.get("symbol")
        if symbol:
            parts.append(f"symbol={symbol}")
        order_id = payload.get("order_id")
        if order_id:
            parts.append(f"order_id={order_id}")
        msg = str(payload.get("message") or "").strip()
        if msg:
            parts.append(f"msg={msg}")
        if event_type == "candle_closed":
            tf = payload.get("timeframe")
            if tf is not None:
                parts.append(f"tf={tf}")
            bar_ist = payload.get("bar_timestamp_ist")
            if bar_ist:
                parts.append(f"bar={bar_ist}")
            o, h, l, c = (
                payload.get("open"),
                payload.get("high"),
                payload.get("low"),
                payload.get("close"),
            )
            if any(v is not None for v in (o, h, l, c)):
                parts.append(f"O={o} H={h} L={l} C={c}")
            rsi = payload.get("rsi")
            if rsi is not None:
                parts.append(f"rsi={rsi}")
            prev = payload.get("prev_rsi")
            if prev is not None:
                parts.append(f"prev_rsi={prev}")
        try:
            self._telegram_alert(" | ".join(parts))
        except Exception:
            # Alerting must never interfere with engine/logging path.
            pass

    @staticmethod
    def _coerce_to_unix_seconds(ts: Any) -> Optional[float]:
        """Normalize candle timestamp to UNIX seconds for arithmetic."""
        if ts is None:
            return None
        try:
            if isinstance(ts, datetime):
                dt_ = ts
                if dt_.tzinfo is None:
                    dt_ = dt_.replace(tzinfo=timezone.utc)
                return float(dt_.timestamp())
            if isinstance(ts, (int, float)):
                sec = float(ts)
                if sec >= 1e15:
                    sec /= 1e6
                elif sec >= 1e12:
                    sec /= 1000.0
                return sec
            s = str(ts).strip()
            if not s:
                return None
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            parsed = datetime.fromisoformat(s)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return float(parsed.timestamp())
        except Exception:
            return None

    @staticmethod
    def _bar_close_unix_from_bucket(
        bucket_unix: float,
        tf_sec: int,
        exchange: Optional[str],
    ) -> float:
        """
        Bar close instant (UNIX): bucket start + timeframe length.
        NSE cash INDEX 1H: final truncated segment is 15:15–15:30 IST (not a full hour);
        naive bucket+3600 would land at 16:15 — clamp to session close 15:30.
        """
        close_u = float(bucket_unix) + float(tf_sec)
        ex = str(exchange or "").upper()
        if tf_sec != 3600 or ex not in ("INDEX", "NSE_INDEX", "NSE"):
            return close_u
        try:
            buck_dt = datetime.fromtimestamp(float(bucket_unix), tz=IST)
            if buck_dt.hour == 15 and buck_dt.minute == 15:
                close_dt = buck_dt.replace(hour=15, minute=30, second=0, microsecond=0)
                return float(close_dt.timestamp())
        except Exception:
            pass
        return close_u

    @staticmethod
    def _bar_timestamp_to_ist_iso(ts: Any) -> Optional[str]:
        """
        Bar instant as ISO in Asia/Kolkata (IST). Used for open/close UNIX conversion.
        Naive datetimes are interpreted as UTC (same convention as LiveEngine candle timestamps).
        """
        if ts is None:
            return None
        try:
            if isinstance(ts, datetime):
                dt_ = ts
                if dt_.tzinfo is None:
                    dt_ = dt_.replace(tzinfo=timezone.utc)
                return dt_.astimezone(IST).isoformat()
            if isinstance(ts, (int, float)):
                sec = float(ts)
                if sec >= 1e15:
                    sec /= 1e6
                elif sec >= 1e12:
                    sec /= 1000.0
                return (
                    datetime.fromtimestamp(sec, tz=timezone.utc)
                    .astimezone(IST)
                    .isoformat()
                )
            s = str(ts).strip()
            if not s:
                return None
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            parsed = datetime.fromisoformat(s)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(IST).isoformat()
        except Exception:
            return None

    @staticmethod
    def _to_ist_minute_str(dt_ist: datetime) -> str:
        """IST wall time as ``YYYY-MM-DD HH:MM`` (no seconds, no offset)."""
        return dt_ist.astimezone(IST).replace(second=0, microsecond=0).strftime(IST_MINUTE_FMT)

    @staticmethod
    def _bar_timestamp_to_ist_minute(ts: Any) -> Optional[str]:
        """Bar open instant in IST, minute resolution (matches RSI history log style)."""
        raw = EngineLogger._bar_timestamp_to_ist_iso(ts)
        if not raw:
            return None
        try:
            s = raw.strip()
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            parsed = datetime.fromisoformat(s)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return EngineLogger._to_ist_minute_str(parsed)
        except Exception:
            return None

    def candle_created(
        self,
        candle: Dict[str, Any],
        timeframe: Optional[str] = None,
        source: str = "live",
    ) -> None:
        """Append one JSON line per closed candle to logs/{strategy_id}/{strategy_id}_candles.log."""
        ts = candle.get("timestamp")
        tf_sec = None
        if _resolution_to_seconds is not None and timeframe is not None:
            try:
                tf_sec = int(_resolution_to_seconds(str(timeframe)))
            except Exception:
                tf_sec = None

        # bar_timestamp_ist = bar *open* (start of interval).
        bar_ts_ist: Optional[str] = None
        bt = candle.get("bucket_ts")
        if bt is not None:
            try:
                bar_ts_ist = self._bar_timestamp_to_ist_minute(float(bt))
            except Exception:
                bar_ts_ist = None
        if bar_ts_ist is None:
            bar_ts_ist = self._bar_timestamp_to_ist_minute(ts)

        payload = self._payload(
            "candle_closed",
            message="Closed candle",
            symbol=candle.get("symbol"),
            timeframe=timeframe,
            source=source,
            bar_timestamp_ist=bar_ts_ist,
            open=candle.get("open"),
            high=candle.get("high"),
            low=candle.get("low"),
            close=candle.get("close"),
            volume=candle.get("volume"),
            bucket_ts=candle.get("bucket_ts"),
            rsi=candle.get("rsi"),
            prev_rsi=candle.get("prev_rsi"),
            # tf_sec=tf_sec,
            # exchange=candle.get("exchange"),
        )
        payload["timestamp"] = self._to_ist_minute_str(datetime.now(IST))
        if round_json_floats is not None:
            payload = round_json_floats(payload)
        line = json.dumps(payload, default=str) + "\n"
        candles_path = self._candles_log_path(self.strategy)
        with self._lock:
            self._append_line(candles_path, line)
        self._send_telegram_alert(payload)

    def order_placed(
        self,
        symbol: str,
        side: str,
        qty: int,
        price: Optional[float],
        order_id: Optional[str],
        intent_id: Optional[str] = None,
        strategy_id: Optional[str] = None,
        account_id: Optional[str] = None,
    ) -> None:
        self.log(
            "order_placed",
            message="Order placed",
            symbol=symbol,
            side=side,
            qty=qty,
            price=price,
            order_id=order_id,
            intent_id=intent_id,
            strategy_id=strategy_id,
            account_id=account_id,
        )

    def order_filled(
        self,
        symbol: str,
        side: str,
        qty: int,
        price: float,
        order_id: Optional[str],
        intent_id: Optional[str] = None,
        strategy_id: Optional[str] = None,
        account_id: Optional[str] = None,
    ) -> None:
        self.log(
            "order_filled",
            message="Order filled",
            symbol=symbol,
            side=side,
            qty=qty,
            price=price,
            order_id=order_id,
            intent_id=intent_id,
            strategy_id=strategy_id,
            account_id=account_id,
        )

    def exit_triggered(self, symbol: str, side: str, qty: int, reason: str = "") -> None:
        self.log("exit_triggered", message=reason or "Exit triggered", symbol=symbol, side=side, qty=qty)

    def risk_block(self, reason: str, symbol: Optional[str] = None) -> None:
        self.log("risk_block", message=reason, symbol=symbol)

    def reconciliation(
        self,
        message: str,
        details: Optional[Dict] = None,
        strategy_id: Optional[str] = None,
    ) -> None:
        payload = dict(details or {})
        if strategy_id:
            self.log(
                "reconciliation",
                message=message,
                strategy_id=strategy_id,
                **payload,
            )
            return
        # Multi-strategy engines: do not dump engine-wide reconcile/seed noise into
        # the primary strategy file (e.g. LEAPS_RSI absorbing BankNiftyBTST OMS).
        if len(self._known_strategies) > 1:
            self.log(
                "reconciliation",
                message=message,
                strategy_id=self.engine_id,
                **payload,
            )
            return
        self.log("reconciliation", message=message, **payload)

    def websocket_disconnect(self, message: str = "WebSocket disconnected") -> None:
        self.log("websocket_disconnect", message=message)

    def kill_switch(self, reason: str) -> None:
        self.log("kill_switch", message=reason)

    def latency(
        self,
        strategy_time_ms: Optional[float] = None,
        broker_latency_ms: Optional[float] = None,
        total_latency_ms: Optional[float] = None,
        **extra,
    ) -> None:
        self.log("latency", message="Latency metrics", strategy_time_ms=strategy_time_ms, broker_latency_ms=broker_latency_ms, total_latency_ms=total_latency_ms, **extra)

    def feed_health_warning(self, message: str, symbol: Optional[str] = None) -> None:
        self.log("feed_stalled", message=message, symbol=symbol)

    def feed_health_recovered(self, message: str, symbol: Optional[str] = None) -> None:
        self.log("feed_recovered", message=message, symbol=symbol)

    def closed_candle_skip(self, symbol: str, reason: str, **extra: Any) -> None:
        """Log skip reason; pass ``diagnostics=`` or other fields for feed/timestamp debugging."""
        self.log("candle_closed_skipped", message=reason, symbol=symbol, **extra)

    def candle_skipped(self, symbol: str, reason: str, **extra: Any) -> None:
        """Compatibility event for pipeline skip observability."""
        self.log("candle_skipped", message=reason, symbol=symbol, **extra)

    def eod_export(self, path: str, message: str = "EOD export written") -> None:
        self.log("eod_export", message=message, export_path=path)

    def engine_start(self, message: str = "Live engine started") -> None:
        self.log("engine_start", message=message)

    # ---------- Production safeguards ----------
    def order_state_mismatch(self, message: str, details: Optional[Dict] = None, **kwargs) -> None:
        self.log("order_state_mismatch", message=message, **(details or {}), **kwargs)

    def duplicate_signal_blocked(self, symbol: Optional[str] = None, signal_hash: Optional[str] = None) -> None:
        self.log("duplicate_signal_blocked", message="Duplicate signal skipped", symbol=symbol, signal_hash=signal_hash)

    def broker_circuit_breaker_triggered(self, reason: str) -> None:
        self.log("broker_circuit_breaker_triggered", message=reason)

    def max_positions_blocked(self, current_count: Optional[int] = None, max_allowed: Optional[int] = None) -> None:
        self.log("max_positions_blocked", message="Max open positions reached", current_count=current_count, max_allowed=max_allowed)

    def time_window_blocked(self, message: str = "Outside allowed trading hours") -> None:
        self.log("time_window_blocked", message=message)

    def high_slippage_warning(self, symbol: Optional[str] = None, expected_price: Optional[float] = None, fill_price: Optional[float] = None, slippage_pct: Optional[float] = None) -> None:
        self.log("high_slippage_warning", message="Slippage above threshold", symbol=symbol, expected_price=expected_price, fill_price=fill_price, slippage_pct=slippage_pct)

    def memory_pressure_warning(self, message: str, usage_percent: Optional[float] = None) -> None:
        self.log("memory_pressure_warning", message=message, usage_percent=usage_percent)

    def graceful_shutdown(self, message: str = "Graceful shutdown", snapshot_path: Optional[str] = None) -> None:
        self.log("graceful_shutdown", message=message, snapshot_path=snapshot_path)

    def candle_integrity_error(
        self,
        message: str,
        symbol: Optional[str] = None,
        details: Optional[Dict] = None,
        *,
        force: bool = False,
    ) -> None:
        """Log OHLC integrity failure; rate-limited to one summary per symbol per 5 minutes."""
        sym_key = str(symbol or "unknown").strip().upper() or "unknown"
        now = time.time()
        extra = dict(details or {})
        with self._lock:
            st = self._integrity_error_stats.get(sym_key)
            if st is None:
                st = {
                    "count": 0,
                    "window_start": now,
                    "last_emit": 0.0,
                    "last_ohlc": {},
                }
                self._integrity_error_stats[sym_key] = st
            st["count"] = int(st.get("count", 0)) + 1
            st["last_ohlc"] = {
                k: extra.get(k)
                for k in ("open", "high", "low", "close")
                if extra.get(k) is not None
            }
            if not force:
                interval = float(self._integrity_error_interval_sec)
                if now - float(st.get("last_emit", 0.0)) < interval:
                    return
                window_sec = max(1, int(now - float(st.get("window_start", now))))
                count = int(st.get("count", 1))
                msg = (
                    f"{message} ({count} rejects in last {window_sec}s)"
                    if count > 1
                    else message
                )
                emit_extra = {**st.get("last_ohlc", {}), "reject_count": count}
                st["count"] = 0
                st["window_start"] = now
                st["last_emit"] = now
            else:
                msg = message
                emit_extra = extra
        self.log(
            "candle_integrity_error",
            message=msg,
            symbol=symbol,
            **emit_extra,
        )

    def symbol_paused(self, symbol: str, reason: str) -> None:
        self.log("symbol_paused", message=reason, symbol=symbol)

    def strategy_timeout(self, symbol: Optional[str] = None, elapsed_ms: Optional[float] = None, threshold_ms: Optional[float] = None) -> None:
        self.log("strategy_timeout", message="Strategy evaluation exceeded threshold", symbol=symbol, elapsed_ms=elapsed_ms, threshold_ms=threshold_ms)

    def latency_critical_pause(self, message: str = "Latency critical for N cycles; entries paused") -> None:
        self.log("latency_critical_pause", message=message)

    def latency_pause_cleared(self, message: str = "Latency recovered; entries resumed") -> None:
        self.log("latency_pause_cleared", message=message)
