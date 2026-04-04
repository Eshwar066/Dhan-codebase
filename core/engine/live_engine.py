"""
LiveEngine: production-grade live/paper engine with reconciliation,
kill switch, closed-candle validation, feed health, EOD export, and structured logging.
Includes: duplicate signal protection, time-of-day guard, memory guard, graceful shutdown,
symbol-level failure isolation, strategy timeout, latency alert levels, candle integrity.
"""

import csv
import dataclasses
import logging
import os
import signal
import time
import psutil
import datetime as dt
from typing import Any, Dict, List, Optional, Tuple
import pdb

logger = logging.getLogger(__name__)

from run.config import RunMode
from core.engine.base_engine import BaseEngine
from core.engine.live_engine_common import (
    DEFAULT_FEED_STALE_SECONDS,
    LiveEngineHelpersMixin,
)
from core.data.candle_aggregator import _resolution_to_seconds

try:
    from logs.engine_logger import REPORTS_DIR
except ImportError:
    REPORTS_DIR = "reports"


class LiveEngine(LiveEngineHelpersMixin, BaseEngine):
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
        latency_critical_ms: float = 2000,
        latency_critical_cycles: int = 3,
        symbol_error_threshold: int = 5,
        tick_queue: Optional[Any] = None,
        candle_aggregator: Optional[Any] = None,
        universe_service: Optional[Any] = None,
        run_mode: Optional[RunMode] = None,
        open_positions_logger: Optional[Any] = None,
    ):
        super().__init__(
            strategy,
            data,
            instrument_store,
            position_manager,
            universe_service=universe_service,
        )
        self.symbols = symbols
        self.candle_service = candle_service
        self.order_router = order_router
        self.position_manager = position_manager
        self.position_manager.on_structure_exit = getattr(
            strategy, "on_structure_exit", None
        )
        self.position_manager.on_forced_exit = getattr(strategy, "on_forced_exit", None)
        self.position_manager.on_main_entry_fill = self._on_pm_main_entry_fill
        self.position_manager.on_main_exit_fill = self._on_pm_main_exit_fill
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
        # Order state check (Fix 2: Default to 1m if not set)
        self.order_state_check_interval_min = order_state_check_interval_min or 1
        self._last_order_state_check_time: float = 0
        self._entries_paused_order_mismatch = False
        # Stale exit order refresh: re-quote at near bid/ask every 1 min until fill
        self._exit_refresh_interval_seconds = 60
        self._last_exit_refresh_time: float = 0
        self.run_mode = run_mode
        self._open_positions_logger = open_positions_logger
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
        self._shutdown_signal: Optional[int] = None
        # Candle aggregator: last evaluated closed-candle timestamp per symbol (avoid re-eval same bar)
        self._last_evaluated_candle_ts: Dict[str, Any] = {}
        self._max_ticks_per_cycle = 10000
        # Tick size cache (populated at startup to avoid lookup latency in hot path)
        self._tick_cache: Dict[str, float] = {}
        if self.instrument_store and hasattr(self.instrument_store, "get_tick_size"):
            for sym in self.symbols:
                tick = self.instrument_store.get_tick_size(sym)
                self._tick_cache[sym] = float(tick) if tick is not None else 0.01

        # Largest accepted bar bucket start (unix) per symbol; blocks REST replay / time regression
        self._max_candle_bucket_unix: Dict[str, int] = {}
        # After at least one tick-built bar (bucket_ts set), drop REST rows without bucket_ts
        self._has_seen_aggregator_bucket: Dict[str, bool] = {}

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
            return int(ts.timestamp())
        if isinstance(ts, (int, float)):
            t = float(ts)
            if t > 1e12:
                return int(t / 1e6)
            return int(t)
        return None

    def _live_bar_is_stale_or_replay(
        self, symbol: str, candle: Dict[str, Any], tf: str
    ) -> bool:
        """
        When ticks + CandleAggregator are active, reject:
        - REST fallback rows without bucket_ts after we have seen real buckets
        - bar bucket time going backwards (duplicate old bar after restart)
        - \"last closed\" rows far behind wall clock (stale historical replay)
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

    def build_context(self, candle, recent_candles=None):
        intent_store = getattr(self.order_router, "intent_store", None)
        return super().build_context(
            candle, recent_candles=recent_candles, intent_store=intent_store
        )

    def _underlying_from_strategy_meta(self, metadata_extras: Any) -> Optional[str]:
        if isinstance(metadata_extras, dict):
            od = metadata_extras.get("one_day_magical_line") or metadata_extras.get(
                "one_day_ml1"
            )
            if isinstance(od, dict) and od.get("symbol"):
                return str(od["symbol"])
        return None

    def _on_pm_main_entry_fill(self, **kwargs: Any) -> None:
        strategy = kwargs.get("strategy")
        if strategy != self.strategy.name:
            return
        fn = getattr(self.strategy, "on_main_entry_filled", None)
        if not callable(fn):
            return
        meta_ex = kwargs.get("metadata_extras")
        sym = self._underlying_from_strategy_meta(meta_ex)
        if not sym and self.symbols:
            sym = self.symbols[0]
        if not sym:
            return
        ts = kwargs.get("candle_ts")
        if ts is None:
            ts = dt.datetime.utcnow()
        spot = self.get_price_map(sym)
        if spot is None:
            spot = 0.0
        candle = {
            "symbol": sym,
            "timestamp": ts,
            "close": float(spot),
            "exchange": None,
        }
        ctx = self.build_context_only(candle)
        intents = fn(ctx=ctx, **kwargs) or []
        risk_manager = getattr(self.order_router, "risk", None)
        for intent in intents:
            self._process_entry_like_intent(
                intent,
                sym,
                candle,
                None,
                None,
                risk_manager,
            )

    def _on_pm_main_exit_fill(self, **kwargs: Any) -> None:
        strategy = kwargs.get("strategy")
        if strategy != self.strategy.name:
            return
        fn = getattr(self.strategy, "on_main_exit_filled", None)
        if not callable(fn):
            return
        pairs = fn(**kwargs) or []
        risk_manager = getattr(self.order_router, "risk", None)
        for intent, candle in pairs:
            sym = candle.get("symbol")
            if not sym and self.symbols:
                sym = self.symbols[0]
            if not sym:
                continue
            self._process_entry_like_intent(
                intent,
                sym,
                candle,
                None,
                None,
                risk_manager,
            )

    def _graceful_shutdown_handler(self, signum: int, frame: Any) -> None:
        """Per-engine: set flag so main loop exits; snapshot and flush in loop or on exit."""
        self._shutdown_requested = True
        self._shutdown_signal = int(signum)
        if self.engine_logger:
            self.engine_logger.graceful_shutdown(f"Signal {signum} received")

    def reconcile_positions_on_start(self) -> bool:
        """
        Fetch broker positions, sync PositionManager to broker truth, log any mismatch.
        Must run before live loop starts.
        Returns True on success, False on error.
        """

        broker = getattr(self.order_router, "broker", None)
        if not broker or not hasattr(broker, "get_positions_for_recon"):
            if self.engine_logger:
                self.engine_logger.reconciliation(
                    "No broker or get_positions_for_recon; skip reconcile"
                )
            return True
        try:
            broker_positions = broker.get_positions_for_recon()
        except Exception as e:
            if self.engine_logger:
                self.engine_logger.reconciliation(
                    f"Failed to fetch broker positions: {e}"
                )
            return False
        local_snapshot = self.position_manager.snapshot()
        resolved_broker_positions = {}
        diff = []

        for b_sym, bp in broker_positions.items():
            # Resolve broker symbol (id or short_name) to engine symbol
            engine_sym = b_sym
            if self.instrument_store:
                inst = self.instrument_store.intent_creation_details(
                    b_sym, self.venue, None, None, None
                )
                if inst:
                    engine_sym = inst.trading_symbol

            resolved_broker_positions[engine_sym] = bp

            local = local_snapshot.get(engine_sym, {})
            lq = local.get("qty", 0)
            bq = int(bp.get("qty", 0))
            if (
                lq != bq
                or abs(local.get("avg_price", 0) - float(bp.get("avg_price", 0))) > 0.01
            ):
                diff.append(
                    {
                        "symbol": engine_sym,
                        "local_qty": lq,
                        "broker_qty": bq,
                        "broker_avg": bp.get("avg_price"),
                    }
                )

        for sym in set(local_snapshot.keys()) - set(resolved_broker_positions.keys()):
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

        strategy_name = getattr(self.strategy, "name", None)
        intent_store = getattr(self.order_router, "intent_store", None)
        if intent_store and hasattr(
            self.position_manager, "rebuild_position_metadata_from_intent_store"
        ):
            self.position_manager.rebuild_position_metadata_from_intent_store(
                intent_store
            )
            if hasattr(
                self.position_manager, "rebuild_structure_slices_from_intent_store"
            ):
                self.position_manager.rebuild_structure_slices_from_intent_store(
                    intent_store
                )
        self.position_manager.reconcile_with_broker(
            resolved_broker_positions, strategy=strategy_name
        )
        if self._open_positions_logger is not None and self.run_mode == RunMode.LIVE:
            self._open_positions_logger.record_broker_reconcile_snapshot(
                self.position_manager
            )
        self._ensure_broker_sl_after_reconcile()
        return True

    def _ensure_broker_sl_after_reconcile(self) -> None:
        """If MAIN is open but MAIN_SL was never armed (reconcile / fill race), place SL once."""
        if self.run_mode != RunMode.LIVE:
            return
        strategy_name = getattr(self.strategy, "name", None)
        if not strategy_name:
            return
        intent_store = getattr(self.order_router, "intent_store", None)
        if not intent_store:
            return
        restore = getattr(self.strategy, "_restore_odml_meta_from_position", None)
        for sym, pos in list(self.position_manager.positions.items()):
            if int(pos.net_qty or 0) == 0:
                continue
            if getattr(pos, "strategy", None) != strategy_name:
                continue
            if str(getattr(pos, "tag", "") or "").upper() != "MAIN":
                continue
            struct_id = getattr(pos, "structure_id", None)
            if not struct_id:
                continue
            if intent_store.has_pending_intent(
                strategy_name,
                struct_id,
                tags=["MAIN_SL"],
                actions=["FORCE_EXIT"],
            ):
                continue
            if callable(restore):
                try:
                    restore(pos, self.position_manager)
                except Exception:
                    pass
            meta_bucket = self.position_manager.get_position_metadata(sym) or {}
            self._on_pm_main_entry_fill(
                instrument=pos.instrument,
                side="SELL" if pos.net_qty < 0 else "BUY",
                qty=abs(int(pos.net_qty)),
                price=float(pos.avg_price or 0),
                strategy=strategy_name,
                structure_id=struct_id,
                tag="MAIN",
                action="ENTRY",
                candle_ts=None,
                intent_id=getattr(pos, "intent_id", None)
                or meta_bucket.get("intent_id"),
                metadata_extras=meta_bucket.get("strategy_meta"),
            )

    def _do_order_state_check(self) -> None:
        # PAPER: skip broker order comparison (SimulatedBroker has no real orders; avoids false mismatches).
        # LIVE: fetch broker orders, compare with OMS, resolve mismatches.
        if self.run_mode == RunMode.PAPER:
            return
        if self.order_state_check_interval_min <= 0:
            return
        now = time.time()
        if (
            now - self._last_order_state_check_time
            < self.order_state_check_interval_min * 60
        ):
            return
        self._last_order_state_check_time = now
        ok, _ = self.order_router.verify_open_orders_with_broker()
        if not ok:
            self._entries_paused_order_mismatch = True
            self.reconcile_positions_on_start()
        else:
            self._entries_paused_order_mismatch = False

    def _check_memory(self) -> None:
        if self.memory_threshold_percent is None or self.memory_threshold_percent <= 0:
            return
        try:
            proc = psutil.Process()
            usage = proc.memory_percent()
            # print(">>usage", usage)
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

    # this not getting logged properly
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
                    if now - self._tick_debug_last_log >= 600:
                        msg = f"Tick health: {self._tick_debug_count} ticks in last 5s"
                        if self.engine_logger:
                            self.engine_logger.log("tick_health", msg)
                        else:
                            logger.info(msg)
                        self._tick_debug_count = 0
                        self._tick_debug_last_log = now
            except Exception as e:
                logger.debug("Invalid tick or aggregator error: %s", e)

    def start(self, exchange, sector, rsi):
        if self.engine_logger:
            self.engine_logger.engine_start("Live engine started")
        else:
            logger.info("Live engine started")

        try:
            signal.signal(signal.SIGINT, self._graceful_shutdown_handler)
        except (AttributeError, ValueError):
            pass
        try:
            signal.signal(signal.SIGTERM, self._graceful_shutdown_handler)
        except (AttributeError, ValueError):
            pass

        if not self.reconcile_positions_on_start():
            self.engine_logger.log("critical", "Startup reconciliation failed")
            return

        _rm = getattr(self.run_mode, "value", None) or str(self.run_mode or "")
        self._telegram_plain(
            f"Engine started: {self.engine_id} | venue={self.venue} | mode={_rm}"
        )

        self._do_order_state_check()
        tf = getattr(self.strategy, "timeframe", None)
        use_feed = self.realtime_feed and self.realtime_feed.is_connected()
        risk_manager = getattr(self.order_router, "risk", None)
        loop_count = 0
        while not self._shutdown_requested:
            # pdb.set_trace()
            loop_count += 1
            _now = dt.datetime.utcnow()
            if risk_manager and risk_manager.is_engine_blocked():
                if self.engine_logger:
                    self.engine_logger.log(
                        "risk_block", "Engine blocked by kill switch; skipping entries"
                    )
                time.sleep(1)
                continue

            # move to  Memory → every 5s , Feed health → every 1s ,Order state → every N minutes
            self._check_memory()
            self.check_feed_health()
            self._do_order_state_check()
            self._do_exit_order_refresh()

            # Export eod report funtion
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
                            logger.debug(
                                "Skip %s: same candle bucket_ts=%s (waiting for new bar)",
                                symbol,
                                candle.get("bucket_ts"),
                            )
                            continue
                    if candle is None and use_feed and not use_aggregator:
                        candle = self.realtime_feed.get_last_candle(symbol, tf)
                        if candle:
                            ts = candle.get("timestamp")
                            if isinstance(ts, (int, float)):
                                self._last_candle_timestamp[symbol] = time.time()
                    #  check this flow by commenting ws feed
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
                    if self.engine_logger:
                        self.engine_logger.candle_created(candle, timeframe=tf)

                    if not self._validate_candle_integrity(candle, symbol):
                        continue

                    # This code checks if the candle is fully closed; if not, it logs a warning and skips strategy evaluation to avoid trading on incomplete market data.
                    if not self._is_closed_candle(candle, tf, now=_now):
                        if self.engine_logger:
                            self.engine_logger.closed_candle_skip(
                                symbol, "Forming or misaligned candle; skip evaluation"
                            )
                        continue

                    if use_aggregator:
                        if self._live_bar_is_stale_or_replay(symbol, candle, tf):
                            continue
                        bt_ok = candle.get("bucket_ts")
                        if bt_ok is not None:
                            self._last_evaluated_candle_ts[symbol] = bt_ok
                            self._has_seen_aggregator_bucket[symbol] = True
                        bs_ok = self._candle_bucket_start_unix(candle)
                        if bs_ok is not None:
                            self._max_candle_bucket_unix[symbol] = max(
                                self._max_candle_bucket_unix.get(symbol, 0),
                                bs_ok,
                            )

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
                    intent_has_entry = self._intent_has_entry(intent)
                    if (
                        intent
                        and intent_has_entry
                        and (
                            self._entries_paused_order_mismatch
                            or self._entries_paused_memory
                            or self._entries_paused_latency
                        )
                    ):
                        continue

                    self._enrich_candle_depth(symbol, candle)

                    self._run_strategy(
                        symbol,
                        candle,
                        ctx,
                        intent,
                        strategy_time_ms=strategy_time_ms,
                        timeframe=tf,
                    )
            # To be checked properly else condition--> Pending
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
                    self._enrich_candle_depth(symbol, candle)
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
        _rm = getattr(self.run_mode, "value", None) or str(self.run_mode or "")
        _why = (
            f"signal {self._shutdown_signal}"
            if self._shutdown_signal is not None
            else "shutdown"
        )
        self._telegram_plain(
            f"Engine stopped: {self.engine_id} | venue={self.venue} | mode={_rm} | {_why}"
        )

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
            self.engine_logger.graceful_shutdown(
                "================================================"
            )
        broker = getattr(self.order_router, "broker", None)
        if broker and hasattr(broker, "close"):
            try:
                broker.close()
            except Exception:
                pass

    def _process_entry_like_intent(
        self,
        single_intent,
        symbol,
        candle,
        strategy_time_ms: Optional[float],
        timeframe: Optional[str],
        risk_manager,
    ) -> None:
        """LIMIT/ENTRY/SL-M and other non-MAIN_EXIT intents (depth-based entry pricing)."""
        self._log_and_telegram_signal(
            single_intent,
            symbol,
            action=getattr(single_intent, "action", "ENTRY"),
        )

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
                self.engine_logger.time_window_blocked("Outside allowed trading hours")
            return
        signal_kind = str(getattr(single_intent, "action", "ENTRY") or "ENTRY").lower()
        signal_hash = self._signal_hash(
            symbol, timeframe or "", candle.get("timestamp"), signal_kind
        )

        # Dublicate signal blocker ==> tested ✅
        if self._last_signal_hash_per_symbol.get(symbol) == signal_hash:
            if self.engine_logger:
                self.engine_logger.duplicate_signal_blocked(
                    symbol=symbol, signal_hash=str(signal_hash)
                )
            return

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

        side = getattr(single_intent, "side", "").upper()
        is_buy = side == "BUY"

        trading_sym = getattr(
            getattr(single_intent, "instrument", None), "trading_symbol", symbol
        )

        if trading_sym:
            exec_price = self._entry_price_from_depth(trading_sym, is_buy)

            if exec_price is None:
                exec_price = getattr(single_intent, "price", None)

            if exec_price is None:
                exec_price = candle.get("close")

        else:
            exec_price = (
                self._entry_price_from_depth(symbol, is_buy)
                or getattr(single_intent, "price", None)
                or candle.get("close")
            )
        if exec_price is not None:
            trading_sym = getattr(
                getattr(single_intent, "instrument", None), "trading_symbol", symbol
            )
            self._validate_lot_size(single_intent, trading_sym)
            self._last_signal_hash_per_symbol[symbol] = signal_hash
            t0 = time.perf_counter()
            price_map = {trading_sym: exec_price}
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
            print(">>exit_signal", exit_signal)
            if exit_signal:
                exit_intents = (
                    self.strategy.on_position_exit(position, candle, ctx) or []
                )
                is_sell = position.net_qty > 0
                required_exit_side = "SELL" if is_sell else "BUY"
                if exit_intents:
                    if self.engine_logger:
                        self.engine_logger.exit_triggered(
                            symbol,
                            required_exit_side,
                            abs(position.net_qty),
                            "Strategy exit",
                        )
                    for raw_intent in exit_intents:
                        # e.g. OneDayMagicalLine reversal: MAIN_EXIT only here; ENTRY after exit fill
                        is_main_exit = (
                            str(getattr(raw_intent, "action", "") or "").upper()
                            == "EXIT"
                            and str(getattr(raw_intent, "tag", "") or "").upper()
                            == "MAIN_EXIT"
                        )
                        if not is_main_exit:
                            self._process_entry_like_intent(
                                raw_intent,
                                symbol,
                                candle,
                                strategy_time_ms,
                                timeframe,
                                risk_manager,
                            )
                            continue
                        exit_intent = raw_intent
                        # Position direction validation: exit side must match position (prevents accidental reversal)
                        if getattr(exit_intent, "side", None) != required_exit_side:
                            exit_intent = dataclasses.replace(
                                exit_intent, side=required_exit_side
                            )
                        self._log_and_telegram_signal(
                            exit_intent,
                            symbol,
                            action="EXIT",
                            qty_fallback=abs(position.net_qty),
                        )
                        # Exit price from depth by intent's instrument and position direction (correct bid/ask for this contract)
                        trading_sym = getattr(
                            exit_intent.instrument, "trading_symbol", symbol
                        )
                        exit_price = (
                            self._exit_price_from_depth(trading_sym, is_sell)
                            or self.get_price_map(trading_sym)
                            or self.get_price_map(symbol)
                        )
                        if exit_price is None:
                            continue
                        self._validate_lot_size(exit_intent, trading_sym)
                        price_map = {trading_sym: exit_price}
                        # Fix 3: Ensure exit intents have idempotency keys for deduplication (pass in; intent is frozen)
                        exit_idem_key = getattr(
                            exit_intent, "idempotency_key", None
                        ) or self._signal_hash(
                            symbol, timeframe or "", candle.get("timestamp"), "exit"
                        )
                        self.order_router.process_intent(
                            exit_intent, price_map, idempotency_key=exit_idem_key
                        )

        entry_intents = (
            [intent]
            if intent is not None and not isinstance(intent, list)
            else (intent or [])
        )
        # pdb.set_trace()
        for single_intent in entry_intents:
            self._process_entry_like_intent(
                single_intent,
                symbol,
                candle,
                strategy_time_ms,
                timeframe,
                risk_manager,
            )

    def update_risk_metrics(self, symbol, ltp):
        pos = self.position_manager.positions.get(symbol)
        if not pos or pos.net_qty == 0:
            return
        diff = ltp - pos.entry_price
        if pos.net_qty < 0:
            diff *= -1
        pos.mfe = max(pos.mfe, diff)
        pos.mae = min(pos.mae, diff)
