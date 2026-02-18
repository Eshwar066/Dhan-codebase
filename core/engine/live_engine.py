"""
LiveEngine: production-grade live/paper engine with reconciliation,
kill switch, closed-candle validation, feed health, EOD export, and structured logging.
Includes: duplicate signal protection, time-of-day guard, memory guard, graceful shutdown,
symbol-level failure isolation, strategy timeout, latency alert levels, candle integrity.
"""

import csv
import os
import signal
import time
import datetime as dt
from typing import Any, Dict, List, Optional, Tuple

from core.engine.base_engine import BaseEngine

try:
    from logs.engine_logger import REPORTS_DIR
except ImportError:
    REPORTS_DIR = "reports"

DEFAULT_FEED_STALE_SECONDS = 60


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


class LiveEngine(BaseEngine):
    """
    Live/paper engine. Optional realtime_feed (WebSocket); falls back to
    candle_service / data.get_latest_candles. Supports broker reconciliation,
    risk kill switch, closed-candle validation, feed health, EOD export.
    Plus: duplicate signal protection, time-of-day guard, memory guard, graceful shutdown,
    symbol-level pause, strategy timeout, latency levels, candle integrity.
    """

    def __init__(
        self,
        strategy,
        data,
        candle_service,
        symbols,
        order_router,
        instrument_store,
        position_manager,
        realtime_feed=None,
        engine_id: Optional[str] = None,
        venue: Optional[str] = None,
        engine_logger: Optional[Any] = None,
        feed_stale_seconds: float = DEFAULT_FEED_STALE_SECONDS,
        allowed_trading_hours: Optional[List[Tuple[str, str]]] = None,
        order_state_check_interval_min: int = 0,
        memory_threshold_percent: Optional[float] = None,
        strategy_timeout_seconds: Optional[float] = None,
        latency_critical_ms: float = 150.0,
        latency_critical_cycles: int = 3,
        symbol_error_threshold: int = 5,
        tick_queue: Optional[Any] = None,
        candle_aggregator: Optional[Any] = None,
    ):
        super().__init__(strategy, data, instrument_store, position_manager)
        self.symbols = symbols
        self.candle_service = candle_service
        self.order_router = order_router
        self.position_manager = position_manager
        self.realtime_feed = realtime_feed
        self.tick_queue = tick_queue
        self.candle_aggregator = candle_aggregator
        self.engine_id = engine_id or "live"
        self.venue = venue or ""
        self.engine_logger = engine_logger
        self.feed_stale_seconds = feed_stale_seconds
        self._last_tick_timestamp: Dict[str, float] = {}
        self._last_candle_timestamp: Dict[str, float] = {}
        self._last_eod_date: Optional[str] = None
        self._entries_paused_feed_stale = False
        # Duplicate signal protection
        self._last_signal_hash_per_symbol: Dict[str, int] = {}
        # Time-of-day guard
        self.allowed_trading_hours = allowed_trading_hours or []
        # Order state check
        self.order_state_check_interval_min = order_state_check_interval_min
        self._last_order_state_check_time: float = 0
        self._entries_paused_order_mismatch = False
        # Memory guard
        self.memory_threshold_percent = memory_threshold_percent
        self._entries_paused_memory = False
        # Strategy timeout
        self.strategy_timeout_seconds = strategy_timeout_seconds
        # Latency critical pause
        self.latency_critical_ms = latency_critical_ms
        self.latency_critical_cycles = latency_critical_cycles
        self._latency_critical_count = 0
        self._entries_paused_latency = False
        # Symbol-level failure isolation
        self.symbol_error_threshold = symbol_error_threshold
        self._symbol_state: Dict[str, Dict[str, Any]] = {}
        for sym in self.symbols:
            self._symbol_state[sym] = {
                "paused": False,
                "feed_stale": False,
                "error_count": 0,
            }
        # Graceful shutdown
        self._shutdown_requested = False
        # Candle aggregator: last evaluated closed-candle timestamp per symbol (avoid re-eval same bar)
        self._last_evaluated_candle_ts: Dict[str, Any] = {}
        self._max_ticks_per_cycle = 10000

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
                    if now - self._tick_debug_last_log >= 5:
                        print(f"[TICK HEALTH] {self._tick_debug_count} ticks in last 5s")
                        self._tick_debug_count = 0
                        self._tick_debug_last_log = now
            except Exception:
                pass

    def _signal_hash(
        self, symbol: str, timeframe: str, candle_ts: Any, signal_type: str
    ) -> int:
        """Hash for duplicate signal detection. Override candle_ts for bar identity."""
        ts = getattr(candle_ts, "timestamp", None) or (
            candle_ts if isinstance(candle_ts, (int, float)) else str(candle_ts)
        )
        return hash((symbol, str(timeframe), str(ts), str(signal_type)))

    def _within_trading_hours(self) -> bool:
        if not self.allowed_trading_hours:
            return True
        now = dt.datetime.utcnow()
        return _within_trading_hours_utc(now, self.allowed_trading_hours)

    def _check_memory(self) -> None:
        if self.memory_threshold_percent is None or self.memory_threshold_percent <= 0:
            return
        try:
            import psutil
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
        except Exception:
            pass

    def _validate_candle_integrity(
        self, candle: Dict, symbol: Optional[str] = None
    ) -> bool:
        """
        Validate OHLC consistency: high >= max(open,close), low <= min(open,close).
        If aggregating tick volumes: volume would equal sum(ticks); we only check OHLC here.
        Returns True if valid; on failure logs candle_integrity_error and returns False.
        """
        o = candle.get("open")
        h = candle.get("high")
        l = candle.get("low")
        c = candle.get("close")
        print(candle)
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

    def _graceful_shutdown_handler(self, signum: int, frame: Any) -> None:
        """Per-engine: set flag so main loop exits; snapshot and flush in loop or on exit."""
        self._shutdown_requested = True
        if self.engine_logger:
            self.engine_logger.graceful_shutdown(f"Signal {signum} received")

    def reconcile_positions_on_start(self) -> None:
        """
        Fetch broker positions, sync PositionManager to broker truth, log any mismatch.
        Must run before live loop starts.
        """
        broker = getattr(self.order_router, "broker", None)
        if not broker or not hasattr(broker, "get_positions_for_recon"):
            if self.engine_logger:
                self.engine_logger.reconciliation(
                    "No broker or get_positions_for_recon; skip reconcile"
                )
            return
        try:
            broker_positions = broker.get_positions_for_recon()
        except Exception as e:
            if self.engine_logger:
                self.engine_logger.reconciliation(
                    f"Failed to fetch broker positions: {e}"
                )
            return
        local_snapshot = self.position_manager.snapshot()
        diff = []
        for sym, bp in broker_positions.items():
            local = local_snapshot.get(sym, {})
            lq = local.get("qty", 0)
            bq = int(bp.get("qty", 0))
            if (
                lq != bq
                or abs(local.get("avg_price", 0) - float(bp.get("avg_price", 0))) > 0.01
            ):
                diff.append(
                    {
                        "symbol": sym,
                        "local_qty": lq,
                        "broker_qty": bq,
                        "broker_avg": bp.get("avg_price"),
                    }
                )
        for sym in set(local_snapshot.keys()) - set(broker_positions.keys()):
            if local_snapshot[sym].get("qty", 0) != 0:
                diff.append(
                    {
                        "symbol": sym,
                        "local_qty": local_snapshot[sym].get("qty"),
                        "broker_qty": 0,
                    }
                )
        if diff and self.engine_logger:
            self.engine_logger.reconciliation(
                "Position mismatch; syncing PM to broker", details={"diff": diff}
            )
        self.position_manager.reconcile_with_broker(broker_positions)

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

    def check_feed_health(self) -> None:
        """Warn if no tick/candle received for feed_stale_seconds; optionally pause entries."""
        if not self.realtime_feed or not self.realtime_feed.is_connected():
            return
        now = time.time()
        any_stale = False
        for symbol in self.symbols:
            last_tick = self._last_tick_timestamp.get(symbol, 0)
            last_candle = self._last_candle_timestamp.get(symbol, 0)
            stale = (now - max(last_tick, last_candle)) > self.feed_stale_seconds
            if stale and (last_tick or last_candle):
                any_stale = True
                if self.engine_logger:
                    self.engine_logger.feed_health_warning(
                        f"No data for {symbol} in {self.feed_stale_seconds}s",
                        symbol=symbol,
                    )
        self._entries_paused_feed_stale = any_stale

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

    def _do_order_state_check(self) -> None:
        if self.order_state_check_interval_min <= 0:
            return
        now = time.time()
        if (
            now - self._last_order_state_check_time
            < self.order_state_check_interval_min * 60
        ):
            return
        self._last_order_state_check_time = now
        ok, _ = self.order_router.verify_open_orders_with_broker(self.position_manager)
        if not ok:
            self._entries_paused_order_mismatch = True
            self.reconcile_positions_on_start()

    def start(self, exchange, sector, rsi):
        if self.engine_logger:
            self.engine_logger.engine_start("Live engine started")
        else:
            print("Live engine started")

        try:
            signal.signal(signal.SIGINT, self._graceful_shutdown_handler)
        except (AttributeError, ValueError):
            pass
        try:
            signal.signal(signal.SIGTERM, self._graceful_shutdown_handler)
        except (AttributeError, ValueError):
            pass

        self.reconcile_positions_on_start()
        self._do_order_state_check()
        tf = getattr(self.strategy, "timeframe", None)
        use_feed = self.realtime_feed and self.realtime_feed.is_connected()
        risk_manager = getattr(self.order_router, "risk", None)
        loop_count = 0
        while not self._shutdown_requested:
            loop_count += 1
            _now = dt.datetime.utcnow()
            if risk_manager and risk_manager.is_engine_blocked():
                if self.engine_logger:
                    self.engine_logger.log(
                        "risk_block", "Engine blocked by kill switch; skipping entries"
                    )
                time.sleep(1)
                continue

            self._check_memory()
            self.check_feed_health()
            self._do_order_state_check()
            if loop_count % 60 == 0:
                today = dt.datetime.utcnow().strftime("%Y%m%d")
                if self._last_eod_date and self._last_eod_date != today:
                    self._export_eod(self._last_eod_date)
                self._last_eod_date = today

            if tf:
                use_aggregator = (
                    use_feed
                    and self.tick_queue is not None
                    and self.candle_aggregator is not None
                )
                if use_aggregator:
                    self._drain_tick_queue()

                for symbol in self.symbols:
                    candle = None
                    if use_aggregator:
                        candle = self.candle_aggregator.get_last_closed_candle(
                            symbol, tf
                        )
                        if candle:
                            self._last_candle_timestamp[symbol] = time.time()
                        if candle and candle.get(
                            "bucket_ts"
                        ) == self._last_evaluated_candle_ts.get(symbol):
                            continue
                    if candle is None and use_feed and not use_aggregator:
                        candle = self.realtime_feed.get_last_candle(symbol, tf)
                        if candle:
                            ts = candle.get("timestamp")
                            if isinstance(ts, (int, float)):
                                self._last_candle_timestamp[symbol] = time.time()
                    if candle is None and self.candle_service:
                        candle = self.candle_service.get_latest_closed(
                            symbol, tf, exchange, sector, rsi
                        )
                    if candle is None:
                        continue

                    if isinstance(candle.get("timestamp"), (int, float)):
                        ts = candle["timestamp"]
                        if ts > 1e12:
                            candle["timestamp"] = dt.datetime.utcfromtimestamp(ts / 1e6)
                        else:
                            candle["timestamp"] = dt.datetime.utcfromtimestamp(ts)
                    candle["symbol"] = symbol
                    candle["exchange"] = exchange

                    if not self._validate_candle_integrity(candle, symbol):
                        continue
                    if not self._is_closed_candle(candle, tf, now=_now):
                        if self.engine_logger:
                            self.engine_logger.closed_candle_skip(
                                symbol, "Forming or misaligned candle; skip evaluation"
                            )
                        continue

                    if use_aggregator:
                        self._last_evaluated_candle_ts[symbol] = candle.get("bucket_ts")

                    if not self.strategy.should_evaluate(candle):
                        continue

                    t0 = time.perf_counter()
                    try:
                        ctx, intent = self.build_context(candle)
                    except Exception as e:
                        self._symbol_state[symbol]["error_count"] = (
                            self._symbol_state[symbol].get("error_count", 0) + 1
                        )
                        if (
                            self._symbol_state[symbol]["error_count"]
                            >= self.symbol_error_threshold
                        ):
                            self._symbol_state[symbol]["paused"] = True
                            if self.engine_logger:
                                self.engine_logger.symbol_paused(
                                    symbol, f"Repeated errors: {e}"
                                )
                        continue
                    strategy_time_ms = (time.perf_counter() - t0) * 1000
                    if intent and self._entries_paused_feed_stale:
                        continue
                    if intent and (
                        self._entries_paused_order_mismatch
                        or self._entries_paused_memory
                        or self._entries_paused_latency
                    ):
                        continue
                    self._run_strategy(
                        symbol,
                        candle,
                        ctx,
                        intent,
                        strategy_time_ms=strategy_time_ms,
                        timeframe=tf,
                    )
            else:
                candles = None
                if use_feed:
                    candles = {}
                    for symbol in self.symbols:
                        ticker = self.realtime_feed.get_last_ticker(symbol)
                        if ticker:
                            self._last_tick_timestamp[symbol] = time.time()
                            candles[symbol] = {
                                "open": ticker.get("close"),
                                "high": ticker.get("high") or ticker.get("close"),
                                "low": ticker.get("low") or ticker.get("close"),
                                "close": ticker.get("close"),
                                "volume": ticker.get("volume", 0),
                                "symbol": symbol,
                            }
                if not candles and self.data:
                    candles = self.data.get_latest_candles(self.symbols)

                if not candles:
                    time.sleep(1)
                    continue

                for symbol, candle in candles.items():
                    candle["timestamp"] = dt.datetime.now()
                    candle["symbol"] = symbol
                    candle["exchange"] = exchange
                    if not self._validate_candle_integrity(candle, symbol):
                        continue
                    t0 = time.perf_counter()
                    try:
                        ctx, intent = self.build_context(candle)
                    except Exception as e:
                        self._symbol_state[symbol]["error_count"] = (
                            self._symbol_state[symbol].get("error_count", 0) + 1
                        )
                        if (
                            self._symbol_state[symbol]["error_count"]
                            >= self.symbol_error_threshold
                        ):
                            self._symbol_state[symbol]["paused"] = True
                            if self.engine_logger:
                                self.engine_logger.symbol_paused(
                                    symbol, f"Repeated errors: {e}"
                                )
                        continue
                    strategy_time_ms = (time.perf_counter() - t0) * 1000
                    self._run_strategy(
                        symbol,
                        candle,
                        ctx,
                        intent,
                        strategy_time_ms=strategy_time_ms,
                        timeframe=None,
                    )

            use_feed = self.realtime_feed and self.realtime_feed.is_connected()
            if self.tick_queue is not None and self.candle_aggregator is not None:
                time.sleep(0.1)
            else:
                time.sleep(1)

        # Graceful shutdown: save position snapshot, flush logger, close broker
        snapshot_path = None
        try:
            os.makedirs(REPORTS_DIR, exist_ok=True)
            snapshot_path = os.path.join(
                REPORTS_DIR,
                f"{self.engine_id}_shutdown_{dt.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv",
            )
            with open(snapshot_path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(
                    f, fieldnames=["symbol", "qty", "avg_price", "realized_pnl"]
                )
                w.writeheader()
                for sym, pos in self.position_manager.positions.items():
                    if pos.net_qty != 0:
                        w.writerow(
                            {
                                "symbol": sym,
                                "qty": pos.net_qty,
                                "avg_price": pos.avg_price,
                                "realized_pnl": pos.realized_pnl,
                            }
                        )
        except Exception:
            pass
        if self.engine_logger:
            self.engine_logger.graceful_shutdown(
                "Graceful shutdown", snapshot_path=snapshot_path
            )
        broker = getattr(self.order_router, "broker", None)
        if broker and hasattr(broker, "close"):
            try:
                broker.close()
            except Exception:
                pass

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

    def _run_strategy(
        self,
        symbol,
        candle,
        ctx,
        intent,
        strategy_time_ms: Optional[float] = None,
        timeframe: Optional[str] = None,
    ):
        risk_manager = getattr(self.order_router, "risk", None)
        open_positions = self.position_manager.get_open_positions(
            underlying=symbol, strategy=self.strategy.name
        )

        for position in open_positions:
            exit_signal = self.strategy.should_exit(position, candle, ctx)
            if exit_signal:
                exit_intents = self.strategy.on_position_exit(position, candle, ctx) or []
                price_map = self.get_price_map(symbol)
                if price_map is not None and exit_intents:
                    if self.engine_logger:
                        self.engine_logger.exit_triggered(
                            symbol,
                            "SELL" if position.net_qty > 0 else "BUY",
                            abs(position.net_qty),
                            "Strategy exit",
                        )
                    for exit_intent in exit_intents:
                        self.order_router.process_intent(exit_intent, price_map)

        entry_intents = [intent] if intent is not None and not isinstance(intent, list) else (intent or [])
        for single_intent in entry_intents:
            if risk_manager and risk_manager.is_engine_blocked():
                return
            if symbol not in self._symbol_state:
                self._symbol_state[symbol] = {
                    "paused": False,
                    "feed_stale": False,
                    "error_count": 0,
                }
            if self._symbol_state[symbol].get("paused"):
                return
            if not self._within_trading_hours():
                if self.engine_logger:
                    self.engine_logger.time_window_blocked(
                        "Outside allowed trading hours"
                    )
                return
            signal_hash = self._signal_hash(
                symbol, timeframe or "", candle.get("timestamp"), "entry"
            )
            if self._last_signal_hash_per_symbol.get(symbol) == signal_hash:
                if self.engine_logger:
                    self.engine_logger.duplicate_signal_blocked(
                        symbol=symbol, signal_hash=str(signal_hash)
                    )
                continue
            if (
                self.strategy_timeout_seconds
                and strategy_time_ms is not None
                and strategy_time_ms > self.strategy_timeout_seconds * 1000
            ):
                if self.engine_logger:
                    self.engine_logger.strategy_timeout(
                        symbol=symbol,
                        elapsed_ms=strategy_time_ms,
                        threshold_ms=self.strategy_timeout_seconds * 1000.0,
                    )
                return
            price_map = candle.get("close")
            if price_map is not None:
                self._last_signal_hash_per_symbol[symbol] = signal_hash
                t0 = time.perf_counter()
                self.order_router.process_intent(single_intent, price_map)
                broker_latency_ms = (time.perf_counter() - t0) * 1000
                total_ms = (strategy_time_ms or 0) + broker_latency_ms
                if self.engine_logger and strategy_time_ms is not None:
                    self.engine_logger.latency(
                        strategy_time_ms=strategy_time_ms,
                        broker_latency_ms=broker_latency_ms,
                        total_latency_ms=total_ms,
                    )
                if total_ms > self.latency_critical_ms:
                    self._latency_critical_count += 1
                    if self._latency_critical_count >= self.latency_critical_cycles:
                        self._entries_paused_latency = True
                        if self.engine_logger:
                            self.engine_logger.latency_critical_pause(
                                "Latency critical for N cycles; entries paused"
                            )
                else:
                    self._latency_critical_count = 0

    def update_risk_metrics(self, symbol, ltp):
        pos = self.position_manager.positions.get(symbol)
        if not pos or pos.net_qty == 0:
            return
        diff = ltp - pos.entry_price
        if pos.net_qty < 0:
            diff *= -1
        pos.mfe = max(pos.mfe, diff)
        pos.mae = min(pos.mae, diff)
