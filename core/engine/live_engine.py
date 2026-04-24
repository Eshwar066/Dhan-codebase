"""
LiveEngine: production-grade live/paper engine with reconciliation,
kill switch, closed-candle validation, feed health, EOD export, and structured logging.
Includes: duplicate signal protection, time-of-day guard, memory guard, graceful shutdown,
symbol-level failure isolation, strategy timeout, latency alert levels, candle integrity.
"""

import dataclasses
import logging
import os
import queue
import signal
import time
import datetime as dt
import csv
import threading
import json
from collections import deque
from typing import Any, Dict, List, Optional, Tuple
import pdb

logger = logging.getLogger(__name__)

from run.config import RunMode
from core.engine.base_engine import BaseEngine
from core.data.candle_aggregator import _resolution_to_seconds
from core.engine.live_engine_common import (
    DEFAULT_FEED_STALE_SECONDS,
    LiveEngineHelpersMixin,
)
from core.engine.execution_engine import ExecutionEngine
from core.orderExecution.account_router import AccountRouter

try:
    from logger.engine_logger import REPORTS_DIR
except ImportError:
    REPORTS_DIR = "reports"
class LiveEngine(LiveEngineHelpersMixin, BaseEngine):
    """
    Live/paper engine. Uses realtime_feed (WebSocket/aggregator) candle flow
    in live loop. Supports broker reconciliation,
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
        dhan_order_update_feed: Optional[Any] = None,
        strategies=None,
        account_router: Optional[AccountRouter] = None,
        oms_rate_limit_per_sec: float = 5.0,
        intent_queue_maxsize: int = 1000,
        account_queue_maxsize: int = 500,
        queue_overflow_policy: str = "drop_newest",
        oms_retry_max_attempts: int = 3,
        oms_retry_base_delay_seconds: float = 0.25,
        oms_token_bucket_capacity: int = 5,
        worker_watchdog_interval_seconds: float = 5.0,
        max_active_account_symbol_keys: int = 200,
        account_circuit_breaker_threshold: int = 5,
        feed_stall_seconds: float = 60.0,
    ):
        super().__init__(
            strategy,
            data,
            instrument_store,
            position_manager,
            universe_service=universe_service,
        )
        self.symbols = symbols
        self.strategies = list(strategies or [strategy])
        self._strategy_by_name = {
            str(getattr(s, "name", f"strategy_{idx}")): s
            for idx, s in enumerate(self.strategies)
        }
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
        # Dhan feed lifecycle notification state (transition-based, no spam).
        self._dhan_feed_was_connected: Optional[bool] = None
        self._dhan_feed_last_connect_generation_alerted: int = 0
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
        # Per symbol+timeframe last logged closed bucket (avoid candle log spam in fast loop)
        self._last_logged_candle_bucket: Dict[str, int] = {}
        self._max_ticks_per_cycle = 10000
        self._ws_trade_event_bound = False
        self.dhan_order_update_feed = dhan_order_update_feed
        self.account_router = account_router or AccountRouter()
        self.intent_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue(
            maxsize=max(1, int(intent_queue_maxsize or 1000))
        )
        self._account_symbol_queues: Dict[Tuple[str, str], "queue.Queue[Dict[str, Any]]"] = {}
        self._account_symbol_workers: Dict[Tuple[str, str], threading.Thread] = {}
        self._routing_worker: Optional[threading.Thread] = None
        self._watchdog_worker: Optional[threading.Thread] = None
        self._worker_watchdog_interval_seconds = max(
            1.0, float(worker_watchdog_interval_seconds or 5.0)
        )
        self._routed_intent_ids: set[str] = set()
        self._account_processed_intent_ids: Dict[Tuple[str, str], set[str]] = {}
        self._queue_overflow_policy = str(queue_overflow_policy or "drop_newest").lower()
        self._account_queue_maxsize = max(1, int(account_queue_maxsize or 500))
        self._oms_retry_max_attempts = max(1, int(oms_retry_max_attempts or 3))
        self._oms_retry_base_delay_seconds = max(
            0.05, float(oms_retry_base_delay_seconds or 0.25)
        )
        self._oms_rate_limit_per_sec = max(0.1, float(oms_rate_limit_per_sec or 5.0))
        self._oms_token_bucket_capacity = max(
            1, int(oms_token_bucket_capacity or self._oms_rate_limit_per_sec)
        )
        self._account_token_buckets: Dict[str, Dict[str, float]] = {}
        self._account_bucket_locks: Dict[str, threading.Lock] = {}
        self._executed_intent_ids: set[str] = set()
        self._max_active_account_symbol_keys = max(
            1, int(max_active_account_symbol_keys or 200)
        )
        self._fallback_symbol_key = "__FALLBACK__"
        self._account_failure_counts: Dict[str, int] = {}
        self._paused_accounts: set[str] = set()
        self._account_circuit_breaker_threshold = max(
            1, int(account_circuit_breaker_threshold or 5)
        )
        self._worker_restart_events: Dict[str, deque] = {}
        self._disabled_worker_ids: set[str] = set()
        self._feed_stall_seconds = max(1.0, float(feed_stall_seconds or 60.0))
        self._intent_journal_path = os.path.join(
            "logs", f"{self.engine_id}_intent_pipeline.jsonl"
        )
        self._strategy_task_queues: Dict[str, "queue.Queue[Dict[str, Any]]"] = {}
        self._strategy_workers: Dict[str, threading.Thread] = {}
        self._dhan_order_ws_bound = False
        # OrderNo -> buffered synthetic payloads when intent_id not yet resolvable (race with place_order ack)
        self._dhan_pending_fills: Dict[str, List[Dict[str, Any]]] = {}
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
        self.execution_engine = ExecutionEngine(
            engine_id=self.engine_id,
            intent_queue=self.intent_queue,
            order_router=self.order_router,
            account_router=self.account_router,
            engine_logger=self.engine_logger,
            is_shutdown_requested=lambda: self._shutdown_requested,
            on_latency_critical=lambda: setattr(self, "_entries_paused_latency", True),
            latency_critical_ms=self.latency_critical_ms,
            worker_watchdog_interval_seconds=self._worker_watchdog_interval_seconds,
            queue_overflow_policy=self._queue_overflow_policy,
            account_queue_maxsize=self._account_queue_maxsize,
            oms_retry_max_attempts=self._oms_retry_max_attempts,
            oms_retry_base_delay_seconds=self._oms_retry_base_delay_seconds,
            oms_rate_limit_per_sec=self._oms_rate_limit_per_sec,
            oms_token_bucket_capacity=self._oms_token_bucket_capacity,
            max_active_account_symbol_keys=self._max_active_account_symbol_keys,
            account_circuit_breaker_threshold=self._account_circuit_breaker_threshold,
            intent_journal_path=self._intent_journal_path,
        )

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
            niml = metadata_extras.get("nifty_intraday_magical_line")
            if isinstance(niml, dict) and niml.get("symbol"):
                return str(niml["symbol"])
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
                self.strategy,
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
                self.strategy,
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

    def _normalize_delta_ws_trade(self, raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Normalize Delta user-trade websocket payload to OrderRouter.process_trade shape."""
        if not isinstance(raw, dict):
            return None
        order_id = raw.get("order_id") or raw.get("id")
        client_order_id = raw.get("client_order_id") or raw.get("tag")
        side = str(raw.get("side") or "").upper()
        if side not in ("BUY", "SELL"):
            return None
        try:
            price = float(raw.get("price") or raw.get("average_fill_price") or 0)
            size = float(raw.get("size") or raw.get("qty") or raw.get("filled_size") or 0)
        except (TypeError, ValueError):
            return None
        if price <= 0 or size <= 0:
            return None
        trade_id = raw.get("id") or raw.get("trade_id")
        if trade_id is None:
            # Stable fallback key for idempotency when exchange omits trade id.
            trade_id = f"{order_id}:{client_order_id}:{price}:{size}:{raw.get('created_at') or raw.get('timestamp')}"
        return {
            "trade_id": trade_id,
            "id": trade_id,
            "order_id": str(order_id or ""),
            "intent_id": client_order_id,
            "client_order_id": client_order_id,
            "tag": client_order_id,
            "price": price,
            "size": size,
            "side": side,
            "created_at": raw.get("created_at") or raw.get("timestamp"),
            "execution_source": "WS_USER_TRADES",
        }

    def _sync_delta_ws_trades(self) -> None:
        """Apply websocket user-trades to OMS immediately (faster than periodic fills API sync)."""
        if str(self.venue or "").upper() != "DELTA":
            return
        if not self.realtime_feed or not hasattr(self.realtime_feed, "get_recent_user_trades"):
            return
        try:
            ws_trades = self.realtime_feed.get_recent_user_trades(limit=200) or []
        except Exception:
            return
        if not ws_trades:
            return
        for raw in ws_trades:
            trade = self._normalize_delta_ws_trade(raw)
            if not trade:
                continue
            try:
                if self.order_router.process_trade(trade):
                    self._log_intent_filled(trade)
            except Exception:
                continue

    def on_ws_trade(self, raw_trade: Dict[str, Any]) -> None:
        """Event-driven websocket trade callback: apply fills immediately."""
        trade = self._normalize_delta_ws_trade(raw_trade)
        if not trade:
            return
        try:
            if self.order_router.process_trade(trade):
                self._log_intent_filled(trade)
        except Exception:
            return

    def _normalize_dhan_ws_synthetic_trade(
        self, payload: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Map incremental order-update fill to OrderRouter.process_trade shape.
        Primary intent match: WS Data.CorrelationId (same string as REST correlationId / tag at place).
        Fallback: OrderNo → intent via broker_order_id on IntentStore.
        """
        if not isinstance(payload, dict):
            return None
        order_no = str(payload.get("order_no") or "").strip()
        if not order_no:
            return None
        correlation_id = str(payload.get("correlation_id") or "").strip()
        intent_id = correlation_id or None
        if not intent_id and hasattr(self.order_router, "resolve_intent_id_by_broker_order_id"):
            try:
                intent_id = self.order_router.resolve_intent_id_by_broker_order_id(order_no)
            except Exception:
                intent_id = None
        if not intent_id:
            return None
        try:
            delta = int(payload.get("delta_qty") or 0)
        except (TypeError, ValueError):
            delta = 0
        try:
            price = float(payload.get("slice_price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        side = str(payload.get("side") or "").upper()
        if delta <= 0 or price <= 0 or side not in ("BUY", "SELL"):
            return None
        try:
            cum = int(payload.get("cumulative_tq") or 0)
        except (TypeError, ValueError):
            cum = 0
        lu = str(payload.get("last_updated") or "").strip()
        lu_key = lu.replace(" ", "_").replace(":", "-") if lu else ""
        if lu_key:
            trade_id = f"DHAN_WS:{order_no}:{cum}:{lu_key}"
        else:
            trade_id = f"DHAN_WS:{order_no}:{cum}:{int(time.time() * 1000)}"
        out = {
            "trade_id": trade_id,
            "id": trade_id,
            "order_id": order_no,
            "intent_id": intent_id,
            "client_order_id": intent_id,
            "tag": intent_id,
            "price": price,
            "size": float(delta),
            "side": side,
            "created_at": payload.get("last_updated"),
            "execution_source": "DHAN_WS_ORDER_UPDATE",
            "fill_confidence": "HIGH",
        }
        ws_ts = payload.get("ws_received_at")
        if isinstance(ws_ts, (int, float)) and self.engine_logger:
            try:
                lag_ms = (time.time() - float(ws_ts)) * 1000.0
                if lag_ms >= 500:
                    self.engine_logger.log(
                        "oms",
                        f"Dhan order WS dispatch lag {lag_ms:.0f}ms OrderNo={order_no}",
                    )
            except (TypeError, ValueError):
                pass
        return out

    def _enqueue_dhan_pending_fill(
        self, order_no: str, payload: Dict[str, Any]
    ) -> None:
        if not order_no:
            return
        q = self._dhan_pending_fills.setdefault(order_no, [])
        q.append(payload)
        max_per = 30
        if len(q) > max_per:
            del q[0 : len(q) - max_per]

    def _retry_dhan_pending_fills(self) -> None:
        """Replay fills that arrived before broker_order_id / CorrelationId was visible."""
        if str(self.venue or "").upper() != "DHAN" or not self._dhan_pending_fills:
            return
        for order_no in list(self._dhan_pending_fills.keys()):
            batch = self._dhan_pending_fills.get(order_no) or []
            if not batch:
                del self._dhan_pending_fills[order_no]
                continue
            remaining: List[Dict[str, Any]] = []
            for payload in batch:
                trade = self._normalize_dhan_ws_synthetic_trade(payload)
                if trade:
                    try:
                        if self.order_router.process_trade(trade):
                            self._log_intent_filled(trade)
                    except Exception:
                        remaining.append(payload)
                else:
                    remaining.append(payload)
            if remaining:
                self._dhan_pending_fills[order_no] = remaining[-30:]
            else:
                del self._dhan_pending_fills[order_no]

    def _dhan_closed_row_to_candle(
        self, symbol: str, row: Any, exchange: str, tf: str
    ) -> Dict[str, Any]:
        """
        Build a live-engine candle dict from ``CandleService.get_latest_closed`` row (pandas Series).
        Floors timestamp to TF bucket start and sets ``bucket_ts`` so ``_is_closed_candle`` matches
        ``CandleAggregator`` semantics.
        """
        import pandas as pd

        ts = row["timestamp"]
        ts_pd = pd.Timestamp(ts)
        sec = int(ts_pd.timestamp())
        tf_sec = int(_resolution_to_seconds(tf))
        if tf_sec <= 0:
            tf_sec = 60
        bucket = sec - (sec % tf_sec)
        return {
            "symbol": symbol,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row.get("volume", 0)),
            "timestamp": bucket,
            "bucket_ts": bucket,
            "exchange": exchange,
        }

    def _on_dhan_ws_synthetic_trade(self, payload: Dict[str, Any]) -> None:
        order_no = str(payload.get("order_no") or "").strip()
        trade = self._normalize_dhan_ws_synthetic_trade(payload)
        if trade:
            try:
                if self.order_router.process_trade(trade):
                    self._log_intent_filled(trade)
            except Exception:
                self._enqueue_dhan_pending_fill(order_no, payload)
            return
        if order_no:
            self._enqueue_dhan_pending_fill(order_no, payload)
            if self.engine_logger:
                self.engine_logger.log(
                    "oms",
                    f"Dhan order WS: buffered unmapped fill OrderNo={order_no} (await intent/CorrelationId)",
                )
            else:
                logger.info(
                    "Dhan order WS: buffered unmapped fill OrderNo=%s (await intent/CorrelationId)",
                    order_no,
                )

    def _get_last_closed_from_aggregator(
        self, symbol: str, tf: Any
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        Resolve ``CandleAggregator`` state by symbol. Tick callbacks may register a different
        key casing/alias than ``config.symbols`` (e.g. index name vs ``NIFTY``).
        Returns (candle_or_none, source_tag for diagnostics).
        """
        ca = self.candle_aggregator
        if ca is None:
            return None, "no_aggregator"
        candidates: List[str] = []
        for c in (symbol, str(symbol).strip(), str(symbol).upper(), str(symbol).lower()):
            if c and c not in candidates:
                candidates.append(c)
        for c in candidates:
            out = ca.get_last_closed_candle(c, tf)
            if out is not None:
                return out, f"aggregator:{c}"
        try:
            keys = ca.symbols_with_data()
        except Exception:
            keys = []
        su = str(symbol).upper().strip()
        for k in keys:
            if str(k).upper().strip() == su:
                out = ca.get_last_closed_candle(k, tf)
                if out is not None:
                    return out, f"aggregator_alias:{k}"
        return None, "aggregator:empty"

    def _enqueue_intent(
        self,
        *,
        strategy,
        intent,
        price_map: Dict[str, float],
        idempotency_key: Optional[str] = None,
        strategy_time_ms: Optional[float] = None,
    ) -> None:
        self.execution_engine.enqueue_intent(
            strategy=strategy,
            intent=intent,
            price_map=price_map,
            idempotency_key=idempotency_key,
            strategy_time_ms=strategy_time_ms,
        )

    def _safe_queue_put(
        self, q: "queue.Queue[Dict[str, Any]]", item: Dict[str, Any], queue_name: str, queue_key: Any
    ) -> bool:
        return self.execution_engine.safe_queue_put(
            q=q, item=item, queue_name=queue_name, queue_key=queue_key
        )

    def _worker_id(self, worker_type: str, key: Any) -> str:
        return f"{worker_type}:{key}"

    def _can_restart_worker(self, worker_type: str, key: Any) -> bool:
        wid = self._worker_id(worker_type, key)
        if wid in self._disabled_worker_ids:
            return False
        now = time.time()
        events = self._worker_restart_events.setdefault(wid, deque())
        while events and now - events[0] > 60:
            events.popleft()
        if len(events) >= 5:
            self._disabled_worker_ids.add(wid)
            if self.engine_logger:
                self.engine_logger.log(
                    "critical",
                    f"Worker restart guard tripped worker_id={wid}; disabling worker and alerting",
                )
            return False
        events.append(now)
        return True

    def _append_intent_journal(self, item: Dict[str, Any], status: str) -> None:
        self.execution_engine._append_intent_journal(item, status)

    def _token_bucket_wait(self, account_id: str) -> None:
        self.execution_engine._token_bucket_wait(account_id)

    @staticmethod
    def _is_retryable_intent_error(exc: Exception) -> bool:
        return ExecutionEngine._is_retryable_intent_error(exc)

    def _process_intent_with_retry(self, item: Dict[str, Any]) -> bool:
        return self.execution_engine._process_intent_with_retry(item)

    def _process_account_symbol_queue(self, key: Tuple[str, str]) -> None:
        self.execution_engine._process_account_symbol_queue(key)

    def _strategy_worker_loop(self, strategy_id: str, strategy) -> None:
        q = self._strategy_task_queues[strategy_id]
        while not self._shutdown_requested:
            try:
                task = q.get(timeout=0.5)
            except queue.Empty:
                continue
            response_q = task["response_q"]
            candle = task["candle"]
            try:
                t0 = time.perf_counter()
                ctx = self.build_context_only(candle)
                intent = strategy.on_candle(candle, ctx)
                strategy_time_ms = (time.perf_counter() - t0) * 1000
                response_q.put(
                    {
                        "strategy": strategy,
                        "ctx": ctx,
                        "intent": intent,
                        "strategy_time_ms": strategy_time_ms,
                    }
                )
            except Exception as exc:
                response_q.put({"strategy": strategy, "error": exc})
            finally:
                q.task_done()

    def _ensure_strategy_worker(self, strategy) -> None:
        strategy_id = str(getattr(strategy, "name", "unknown_strategy"))
        wid = self._worker_id("strategy", strategy_id)
        if wid in self._disabled_worker_ids:
            return
        if (
            strategy_id in self._strategy_workers
            and self._strategy_workers[strategy_id].is_alive()
        ):
            return
        if not self._can_restart_worker("strategy", strategy_id):
            return
        q = self._strategy_task_queues.get(strategy_id)
        if q is None:
            q = queue.Queue(maxsize=1)
            self._strategy_task_queues[strategy_id] = q
        t = threading.Thread(
            target=self._strategy_worker_loop,
            args=(strategy_id, strategy),
            daemon=True,
            name=f"strategy_worker_{strategy_id}",
        )
        self._strategy_workers[strategy_id] = t
        t.start()

    def _route_intents_worker(self) -> None:
        self.execution_engine._route_intents_worker()

    def _watchdog_loop(self) -> None:
        self.execution_engine._watchdog_loop()

    def _ensure_workers_healthy(self) -> None:
        self.execution_engine._ensure_workers_healthy()

    def _start_execution_pipeline(self) -> None:
        self.execution_engine.start()
        for strategy in self.strategies:
            self._ensure_strategy_worker(strategy)

    def _evaluate_strategies_parallel(self, candle: Dict[str, Any]) -> List[Dict[str, Any]]:
        response_q: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        expected = 0
        for strategy in self.strategies:
            if not strategy.should_evaluate(candle):
                continue
            self._ensure_strategy_worker(strategy)
            strategy_id = str(getattr(strategy, "name", "unknown_strategy"))
            task = {"candle": dict(candle), "response_q": response_q}
            if self._safe_queue_put(
                self._strategy_task_queues[strategy_id],
                task,
                queue_name="strategy_queue",
                queue_key=strategy_id,
            ):
                expected += 1
        out: List[Dict[str, Any]] = []
        timeout = max(1.0, float(self.strategy_timeout_seconds or 5.0))
        deadline = time.time() + timeout
        while len(out) < expected and time.time() < deadline:
            try:
                item = response_q.get(timeout=0.1)
            except queue.Empty:
                continue
            if item.get("error") is not None:
                logger.exception("Strategy evaluation failed: %s", item["error"])
                continue
            out.append(item)
        return out

    def _log_intent_filled(self, trade: Dict[str, Any]) -> None:
        if not self.engine_logger:
            return
        intent_id = trade.get("intent_id") or trade.get("client_order_id") or ""
        account_id = trade.get("account_id") or "default"
        strategy_id = trade.get("strategy_id")
        if not strategy_id and intent_id:
            try:
                rec = self.order_router.intent_store.get(intent_id)
                if rec:
                    payload = rec.get("payload") or {}
                    strategy_id = rec.get("strategy") or payload.get("strategy_id")
            except Exception:
                strategy_id = None
        self.engine_logger.log(
            "order_filled",
            f"FILLED intent_id={intent_id} strategy_id={trade.get('strategy_id', 'unknown')} account_id={account_id}",
            intent_id=intent_id,
            strategy_id=strategy_id,
            account_id=account_id,
            order_id=trade.get("order_id"),
        )

    def _check_feed_stall_fail_safe(self) -> None:
        if not self.realtime_feed or not self.symbols:
            return
        now = time.time()
        stale_symbols = []
        for sym in self.symbols:
            last_tick = self._last_tick_timestamp.get(sym, 0.0)
            last_candle = self._last_candle_timestamp.get(sym, 0.0)
            last_seen = max(last_tick, last_candle)
            if last_seen <= 0 or (now - last_seen) > self._feed_stall_seconds:
                stale_symbols.append(sym)
        if len(stale_symbols) != len(self.symbols):
            return
        msg = (
            f"Feed stalled for all symbols > {self._feed_stall_seconds}s. "
            f"symbols={stale_symbols}"
        )
        if self.engine_logger:
            self.engine_logger.log("feed_stalled", msg)

    def start(self, exchange, sector, rsi):
        if self.engine_logger:
            self.engine_logger.engine_start("Live engine started")
            for strategy_obj in self.strategies:
                strategy_name = str(getattr(strategy_obj, "name", "unknown_strategy"))
                self.engine_logger.log(
                    "strategy_loaded",
                    message=f"Strategy loaded: {strategy_name}",
                    strategy=strategy_name,
                )
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
        self._log_startup_balance_snapshot()

        self._do_order_state_check()
        if (
            str(self.venue or "").upper() == "DELTA"
            and self.realtime_feed
            and hasattr(self.realtime_feed, "set_user_trade_callback")
            and not self._ws_trade_event_bound
        ):
            try:
                self.realtime_feed.set_user_trade_callback(self.on_ws_trade)
                self._ws_trade_event_bound = True
            except Exception:
                self._ws_trade_event_bound = False
        if (
            str(self.venue or "").upper() == "DHAN"
            and self.dhan_order_update_feed
            and not self._dhan_order_ws_bound
        ):
            try:
                self.dhan_order_update_feed.set_synthetic_trade_callback(
                    self._on_dhan_ws_synthetic_trade
                )
                self.dhan_order_update_feed.start()
                self._dhan_order_ws_bound = True
            except Exception:
                self._dhan_order_ws_bound = False
        tf = getattr(self.strategy, "timeframe", None)
        use_feed = self.realtime_feed and self.realtime_feed.is_connected()
        risk_manager = getattr(self.order_router, "risk", None)
        self._start_execution_pipeline()
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
            self._check_feed_stall_fail_safe()
            self._do_order_state_check()
            self._sync_delta_ws_trades()
            self._retry_dhan_pending_fills()
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
                    candle_source = "none"
                    if use_aggregator:
                        candle, candle_source = self._get_last_closed_from_aggregator(
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
                    # Quote/ticker pseudo-candle (last_trade_time — usually not TF-aligned).
                    if candle is None and use_feed and self.realtime_feed:
                        candle = self.realtime_feed.get_last_candle(symbol, tf)
                        if candle:
                            candle_source = "quote_feed"
                            ts = candle.get("timestamp")
                            if isinstance(ts, (int, float)):
                                self._last_candle_timestamp[symbol] = time.time()

                    #========Dummy candle for after mkt hours test ===========================
                    # if candle is None:
                    #     from zoneinfo import ZoneInfo
                    #     ist = ZoneInfo("Asia/Kolkata")
                    #     bar = dt.datetime.now(ist).replace(
                    #             hour=9, minute=15, second=0, microsecond=0
                    #     )
                    #     bucket = bar.timestamp()
                    #     if self._last_evaluated_candle_ts.get(symbol) == bucket:
                    #         continue
                    #     px = 25000.0
                    #     candle = {
                    #             "timestamp": bar.astimezone(dt.timezone.utc).replace(
                    #                 tzinfo=None
                    #             ),
                    #             "open": px,
                    #             "high": px,
                    #             "low": px,
                    #             "close": px,
                    #             "volume": 1,
                    #             "bucket_ts": bucket,
                    #     }
                    #         # pdb.set_trace()
                    # else:
                    #     print(">>candle is None")
                    #     continue
                    if candle is None:
                        # print(">>candle is None")
                        continue
                    self._normalize_candle_timestamp_utc_naive(candle)
                    candle["symbol"] = symbol
                    candle["exchange"] = exchange

                    if not self._validate_candle_integrity(candle, symbol):
                        continue

                    # This code checks if the candle is fully closed; if not, it logs a warning and skips strategy evaluation to avoid trading on incomplete market data.
                    if not self._is_closed_candle(candle, tf, now=_now):
                        if self.engine_logger and self._should_log_closed_candle_skip(
                            symbol, tf, candle
                        ):
                            diag = self._closed_candle_diagnostics(
                                candle,
                                str(tf),
                                _now,
                                use_aggregator=bool(use_aggregator),
                                candle_source=candle_source,
                            )
                            try:
                                if self.candle_aggregator:
                                    diag["aggregator_symbol_keys"] = (
                                        self.candle_aggregator.symbols_with_data()
                                    )
                            except Exception:
                                pass
                            self.engine_logger.closed_candle_skip(
                                symbol,
                                "Forming or misaligned candle; skip evaluation",
                                diagnostics=diag,
                            )
                        continue

                    eval_bucket = self._candle_bucket_start_unix(candle)
                    eval_key = candle.get("bucket_ts")
                    if eval_key is None:
                        eval_key = eval_bucket
                    if (
                        eval_key is not None
                        and eval_key == self._last_evaluated_candle_ts.get(symbol)
                    ):
                        logger.debug(
                            "Skip %s: already evaluated candle key=%s",
                            symbol,
                            eval_key,
                        )
                        continue

                    if use_aggregator:
                        # check the time of the entry candle at mkt time
                        if self._live_bar_is_stale_or_replay(symbol, candle, tf):
                            continue
                        if candle.get("bucket_ts") is not None:
                            self._has_seen_aggregator_bucket[symbol] = True
                        if eval_bucket is not None:
                            self._max_candle_bucket_unix[symbol] = max(
                                self._max_candle_bucket_unix.get(symbol, 0),
                                eval_bucket,
                            )
                    if eval_key is not None:
                        self._last_evaluated_candle_ts[symbol] = eval_key
                    if self.engine_logger and self._should_log_closed_candle(
                        symbol, tf, candle
                    ):
                        self.engine_logger.candle_created(candle, timeframe=tf)

                    self._enrich_candle_depth(symbol, candle)
                    for eval_result in self._evaluate_strategies_parallel(candle):
                        eval_strategy = eval_result.get("strategy")
                        eval_strategy_name = str(
                            getattr(eval_strategy, "name", "unknown_strategy")
                        )
                        if self.engine_logger:
                            self.engine_logger.log(
                                "strategy_evaluated",
                                message=f"Strategy evaluated: {eval_strategy_name}",
                                strategy=eval_strategy_name,
                                symbol=symbol,
                            )
                        intent = eval_result["intent"]
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
                        self._run_strategy(
                            symbol,
                            candle,
                            eval_result["ctx"],
                            intent,
                            strategy=eval_result["strategy"],
                            strategy_time_ms=eval_result["strategy_time_ms"],
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
                if not candles:
                    time.sleep(1)
                    continue

                for symbol, candle in candles.items():
                    candle["timestamp"] = dt.datetime.now()
                    candle["symbol"] = symbol
                    candle["exchange"] = exchange
                    if not self._validate_candle_integrity(candle, symbol):
                        continue
                    self._enrich_candle_depth(symbol, candle)
                    for eval_result in self._evaluate_strategies_parallel(candle):
                        self._run_strategy(
                            symbol,
                            candle,
                            eval_result["ctx"],
                            eval_result["intent"],
                            strategy=eval_result["strategy"],
                            strategy_time_ms=eval_result["strategy_time_ms"],
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
        if getattr(self, "dhan_order_update_feed", None):
            try:
                self.dhan_order_update_feed.stop()
            except Exception:
                pass
        broker = getattr(self.order_router, "broker", None)
        if broker and hasattr(broker, "close"):
            try:
                broker.close()
            except Exception:
                pass

    def _process_entry_like_intent(
        self,
        single_intent,
        strategy,
        symbol,
        candle,
        strategy_time_ms: Optional[float],
        timeframe: Optional[str],
        risk_manager,
    ) -> None:
        """LIMIT/ENTRY/SL-M and other non-MAIN_EXIT intents (depth-based entry pricing)."""
        self._log_signal(
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
            price_map = {trading_sym: exec_price}
            self._enqueue_intent(
                strategy=strategy,
                intent=single_intent,
                price_map=price_map,
                strategy_time_ms=strategy_time_ms,
            )
            total_ms = strategy_time_ms or 0
            if self.engine_logger and strategy_time_ms is not None:
                self.engine_logger.latency(
                    strategy_time_ms=strategy_time_ms,
                    broker_latency_ms=0.0,
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
        strategy=None,
        strategy_time_ms: Optional[float] = None,
        timeframe: Optional[str] = None,
    ):
        strategy = strategy or self.strategy
        risk_manager = getattr(self.order_router, "risk", None)
        self.evaluate_sim_broker_stops(candle, ctx)
        open_positions = self.position_manager.get_open_positions(
            underlying=symbol, strategy=strategy.name
        )
        for position in open_positions:
            exit_signal = strategy.should_exit(position, candle, ctx)
            if exit_signal:
                exit_intents = (
                    strategy.on_position_exit(position, candle, ctx) or []
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
                                strategy,
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
                        self._log_signal(
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
                        self._enqueue_intent(
                            strategy=strategy,
                            intent=exit_intent,
                            price_map=price_map,
                            idempotency_key=exit_idem_key,
                            strategy_time_ms=strategy_time_ms,
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
                strategy,
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
