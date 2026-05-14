import json
import os
import queue
import threading
import time
from collections import deque
from typing import Any, Callable, Dict, Optional, Tuple

try:
    from core.utils.json_numeric import round_json_floats
except ImportError:
    round_json_floats = None  # type: ignore


class ExecutionEngine:
    """
    OMS execution pipeline extracted from LiveEngine:
    intent enqueue -> account routing -> per-account-symbol worker execution.
    """

    def __init__(
        self,
        *,
        engine_id: str,
        intent_queue: "queue.Queue[Dict[str, Any]]",
        order_router: Any,
        account_router: Any,
        engine_logger: Optional[Any],
        is_shutdown_requested: Callable[[], bool],
        on_latency_critical: Optional[Callable[[], None]],
        latency_critical_ms: float,
        worker_watchdog_interval_seconds: float,
        queue_overflow_policy: str,
        account_queue_maxsize: int,
        oms_retry_max_attempts: int,
        oms_retry_base_delay_seconds: float,
        oms_rate_limit_per_sec: float,
        oms_token_bucket_capacity: int,
        max_active_account_symbol_keys: int,
        account_circuit_breaker_threshold: int,
        intent_journal_path: str,
    ):
        self.engine_id = engine_id
        self.intent_queue = intent_queue
        self.order_router = order_router
        self.account_router = account_router
        self.engine_logger = engine_logger
        self._is_shutdown_requested = is_shutdown_requested
        self._on_latency_critical = on_latency_critical
        self._latency_critical_ms = float(latency_critical_ms)
        self._worker_watchdog_interval_seconds = float(worker_watchdog_interval_seconds)
        self._queue_overflow_policy = str(queue_overflow_policy or "drop_newest").lower()
        self._account_queue_maxsize = int(account_queue_maxsize)
        self._oms_retry_max_attempts = int(oms_retry_max_attempts)
        self._oms_retry_base_delay_seconds = float(oms_retry_base_delay_seconds)
        self._oms_rate_limit_per_sec = float(oms_rate_limit_per_sec)
        self._oms_token_bucket_capacity = int(oms_token_bucket_capacity)
        self._max_active_account_symbol_keys = int(max_active_account_symbol_keys)
        self._account_circuit_breaker_threshold = int(account_circuit_breaker_threshold)
        self._intent_journal_path = intent_journal_path

        self._account_symbol_queues: Dict[Tuple[str, str], "queue.Queue[Dict[str, Any]]"] = {}
        self._account_symbol_workers: Dict[Tuple[str, str], threading.Thread] = {}
        self._routing_worker: Optional[threading.Thread] = None
        self._watchdog_worker: Optional[threading.Thread] = None
        self._routed_intent_ids: set[str] = set()
        self._account_processed_intent_ids: Dict[Tuple[str, str], set[str]] = {}
        self._account_token_buckets: Dict[str, Dict[str, float]] = {}
        self._account_bucket_locks: Dict[str, threading.Lock] = {}
        self._executed_intent_ids: set[str] = set()
        self._fallback_symbol_key = "__FALLBACK__"
        self._account_failure_counts: Dict[str, int] = {}
        self._paused_accounts: set[str] = set()
        self._worker_restart_events: Dict[str, deque] = {}
        self._disabled_worker_ids: set[str] = set()

    def enqueue_intent(
        self,
        *,
        strategy: Any,
        intent: Any,
        price_map: Dict[str, float],
        idempotency_key: Optional[str] = None,
        strategy_time_ms: Optional[float] = None,
    ) -> None:
        payload = {
            "intent": intent,
            "strategy": strategy,
            "strategy_id": getattr(strategy, "name", "unknown_strategy"),
            "intent_id": getattr(intent, "intent_id", ""),
            "created_at": time.time(),
            "price_map": dict(price_map or {}),
            "idempotency_key": idempotency_key,
            "strategy_time_ms": float(strategy_time_ms or 0.0),
            "symbol": getattr(intent, "symbol", None)
            or getattr(getattr(intent, "instrument", None), "trading_symbol", None)
            or "",
        }
        if not self.safe_queue_put(
            self.intent_queue,
            payload,
            queue_name="intent_queue",
            queue_key="global",
        ):
            return
        if self.engine_logger:
            self.engine_logger.log(
                "intent_created",
                f"CREATED intent_id={payload['intent_id']} strategy_id={payload['strategy_id']}",
                intent_id=payload["intent_id"],
                strategy_id=payload["strategy_id"],
                symbol=payload.get("symbol"),
            )

    def safe_queue_put(
        self, q: "queue.Queue[Dict[str, Any]]", item: Dict[str, Any], queue_name: str, queue_key: Any
    ) -> bool:
        try:
            q.put_nowait(item)
            return True
        except queue.Full:
            policy = self._queue_overflow_policy
            if policy == "drop_oldest":
                try:
                    q.get_nowait()
                    q.task_done()
                    q.put_nowait(item)
                    if self.engine_logger:
                        self.engine_logger.log(
                            "intent",
                            f"{queue_name} overflow key={queue_key}; dropped oldest, accepted intent_id={item.get('intent_id')}",
                        )
                    return True
                except (queue.Empty, queue.Full):
                    pass
            if self.engine_logger:
                self.engine_logger.log(
                    "intent",
                    f"{queue_name} overflow key={queue_key}; dropped newest intent_id={item.get('intent_id')}",
                )
            if queue_name == "strategy_queue":
                # Strategy queue log retained for continuity.
                pass
            return False

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
        try:
            os.makedirs(os.path.dirname(self._intent_journal_path), exist_ok=True)
            line = {
                "ts": time.time(),
                "engine_id": self.engine_id,
                "intent_id": item.get("intent_id"),
                "account_id": item.get("account_id"),
                "symbol": item.get("symbol"),
                "status": status,
                "execution_attempt_id": item.get("execution_attempt_id"),
            }
            jl = round_json_floats(line) if round_json_floats else line
            with open(self._intent_journal_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(jl, default=str) + "\n")
        except Exception:
            pass

    def _token_bucket_wait(self, account_id: str) -> None:
        lock = self._account_bucket_locks.setdefault(account_id, threading.Lock())
        while not self._is_shutdown_requested():
            with lock:
                state = self._account_token_buckets.setdefault(
                    account_id,
                    {
                        "tokens": float(self._oms_token_bucket_capacity),
                        "last_refill": time.time(),
                    },
                )
                now = time.time()
                elapsed = max(0.0, now - float(state["last_refill"]))
                refill = elapsed * self._oms_rate_limit_per_sec
                state["tokens"] = min(
                    float(self._oms_token_bucket_capacity),
                    float(state["tokens"]) + refill,
                )
                state["last_refill"] = now
                if state["tokens"] >= 1.0:
                    state["tokens"] -= 1.0
                    return
            time.sleep(0.01)

    @staticmethod
    def _is_retryable_intent_error(exc: Exception) -> bool:
        msg = str(exc or "").lower()
        retry_markers = (
            "timeout",
            "temporarily",
            "connection reset",
            "connection aborted",
            "connection error",
            "503",
            "502",
            "504",
            "rate limit",
        )
        return any(token in msg for token in retry_markers)

    def _process_intent_with_retry(self, item: Dict[str, Any]) -> bool:
        attempts = self._oms_retry_max_attempts
        base_delay = self._oms_retry_base_delay_seconds
        for attempt in range(attempts):
            try:
                item["execution_attempt_id"] = f"{item.get('intent_id')}-{attempt + 1}"
                result = self.order_router.process_intent(
                    item["intent"],
                    item.get("price_map") or {},
                    idempotency_key=item.get("idempotency_key"),
                    raise_on_retryable_failure=True,
                )
                broker_sent_ts = (result or {}).get("broker_sent_ts") or time.time()
                item["broker_sent_ts"] = broker_sent_ts
                return bool((result or {}).get("ok", True))
            except Exception as exc:
                retryable = self._is_retryable_intent_error(exc)
                if not retryable or attempt >= attempts - 1:
                    if self.engine_logger:
                        self.engine_logger.log(
                            "order_failed",
                            f"ORDER_FAILED intent_id={item.get('intent_id')} retryable={retryable} attempt={attempt + 1}/{attempts} error={exc}",
                            intent_id=item.get("intent_id"),
                            strategy_id=item.get("strategy_id"),
                            account_id=item.get("account_id"),
                            symbol=item.get("symbol"),
                        )
                    return False
                backoff = base_delay * (2 ** attempt)
                time.sleep(backoff)
        return False

    def _process_account_symbol_queue(self, key: Tuple[str, str]) -> None:
        account_id, _symbol = key
        q = self._account_symbol_queues[key]
        while not self._is_shutdown_requested():
            try:
                item = q.get(timeout=0.5)
            except queue.Empty:
                continue
            intent_id = item.get("intent_id")
            if intent_id in self._executed_intent_ids:
                q.task_done()
                continue
            if account_id in self._paused_accounts:
                q.task_done()
                continue
            processed = self._account_processed_intent_ids.setdefault(key, set())
            if intent_id in processed:
                q.task_done()
                continue
            item["oms_start_ts"] = time.time()
            self._token_bucket_wait(account_id)
            try:
                ok = self._process_intent_with_retry(item)
                if ok:
                    processed.add(intent_id)
                    self._executed_intent_ids.add(intent_id)
                    self._account_failure_counts[account_id] = 0
                    self._append_intent_journal(item, status="SENT")
                    created_at = float(item.get("created_at") or time.time())
                    routed_ts = float(item.get("routed_ts") or created_at)
                    oms_start_ts = float(item.get("oms_start_ts") or routed_ts)
                    broker_sent_ts = float(item.get("broker_sent_ts") or time.time())
                    total_latency_ms = (
                        broker_sent_ts - created_at
                    ) * 1000.0
                    queue_delay_ms = max(0.0, (routed_ts - created_at) * 1000.0)
                    routing_ms = max(0.0, (oms_start_ts - routed_ts) * 1000.0)
                    oms_wait_ms = max(0.0, (broker_sent_ts - oms_start_ts) * 1000.0)
                    strategy_ms = float(item.get("strategy_time_ms") or 0.0)
                    if self.engine_logger:
                        self.engine_logger.latency(
                            strategy_time_ms=strategy_ms,
                            broker_latency_ms=oms_wait_ms,
                            total_latency_ms=total_latency_ms,
                        )
                        self.engine_logger.log(
                            "latency_breakdown",
                            "Execution latency breakdown",
                            intent_id=intent_id,
                            strategy_id=item.get("strategy_id"),
                            account_id=account_id,
                            symbol=item.get("symbol"),
                            execution_attempt_id=item.get("execution_attempt_id"),
                            latency={
                                "strategy_ms": strategy_ms,
                                "queue_delay_ms": queue_delay_ms,
                                "routing_ms": routing_ms,
                                "oms_wait_ms": oms_wait_ms,
                                "broker_ms": oms_wait_ms,
                                "total_ms": total_latency_ms,
                            },
                        )
                    if self.engine_logger:
                        self.engine_logger.log(
                            "order_placed",
                            f"ORDER_PLACED intent_id={intent_id} strategy_id={item.get('strategy_id')} account_id={account_id} execution_attempt_id={item.get('execution_attempt_id')}",
                            intent_id=intent_id,
                            strategy_id=item.get("strategy_id"),
                            account_id=account_id,
                            symbol=item.get("symbol"),
                            execution_attempt_id=item.get("execution_attempt_id"),
                            latency_critical=bool(total_latency_ms > self._latency_critical_ms),
                        )
                    if (
                        total_latency_ms > self._latency_critical_ms
                        and self._on_latency_critical is not None
                    ):
                        self._on_latency_critical()
                else:
                    self._account_failure_counts[account_id] = (
                        self._account_failure_counts.get(account_id, 0) + 1
                    )
                    if (
                        self._account_failure_counts[account_id]
                        >= self._account_circuit_breaker_threshold
                    ):
                        self._paused_accounts.add(account_id)
                        if self.engine_logger:
                            self.engine_logger.log(
                                "critical",
                                f"Account circuit breaker tripped account_id={account_id}",
                            )
            except Exception:
                time.sleep(0.5)
            finally:
                q.task_done()

    def _route_intents_worker(self) -> None:
        while not self._is_shutdown_requested():
            try:
                item = self.intent_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            intent_id = item.get("intent_id")
            if intent_id in self._routed_intent_ids:
                self.intent_queue.task_done()
                continue
            accounts = self.account_router.route(item.get("intent"))
            for account_id in accounts:
                symbol = str(item.get("symbol") or "")
                key = (account_id, symbol)
                if (
                    key not in self._account_symbol_queues
                    and len(self._account_symbol_queues) >= self._max_active_account_symbol_keys
                ):
                    key = (account_id, self._fallback_symbol_key)
                aq = self._account_symbol_queues.get(key)
                if aq is None:
                    aq = queue.Queue(maxsize=self._account_queue_maxsize)
                    self._account_symbol_queues[key] = aq
                if (
                    key not in self._account_symbol_workers
                    or not self._account_symbol_workers[key].is_alive()
                ):
                    if not self._can_restart_worker("oms", key):
                        continue
                    t = threading.Thread(
                        target=self._process_account_symbol_queue,
                        args=(key,),
                        daemon=True,
                        name=f"oms_worker_{account_id}_{symbol}",
                    )
                    self._account_symbol_workers[key] = t
                    t.start()
                routed = dict(item)
                routed["account_id"] = account_id
                routed["routed_ts"] = time.time()
                if self.safe_queue_put(
                    aq,
                    routed,
                    queue_name="account_symbol_queue",
                    queue_key=key,
                ) and self.engine_logger:
                    self.engine_logger.log(
                        "intent_routed",
                        f"ROUTED intent_id={intent_id} strategy_id={item.get('strategy_id')} account_id={account_id}",
                        intent_id=intent_id,
                        strategy_id=item.get("strategy_id"),
                        account_id=account_id,
                        symbol=item.get("symbol"),
                    )
            self._routed_intent_ids.add(intent_id)
            self.intent_queue.task_done()

    def _watchdog_loop(self) -> None:
        while not self._is_shutdown_requested():
            try:
                self._ensure_workers_healthy()
            except Exception:
                pass
            time.sleep(self._worker_watchdog_interval_seconds)

    def _ensure_workers_healthy(self) -> None:
        if not self._routing_worker or not self._routing_worker.is_alive():
            self.start()
        for key in list(self._account_symbol_queues.keys()):
            worker = self._account_symbol_workers.get(key)
            if worker is None or not worker.is_alive():
                if not self._can_restart_worker("oms", key):
                    continue
                t = threading.Thread(
                    target=self._process_account_symbol_queue,
                    args=(key,),
                    daemon=True,
                    name=f"oms_worker_{key[0]}_{key[1]}",
                )
                self._account_symbol_workers[key] = t
                t.start()

    def start(self) -> None:
        if self._routing_worker and self._routing_worker.is_alive():
            return
        self._routing_worker = threading.Thread(
            target=self._route_intents_worker,
            daemon=True,
            name="intent_router_worker",
        )
        self._routing_worker.start()
        if not self._watchdog_worker or not self._watchdog_worker.is_alive():
            self._watchdog_worker = threading.Thread(
                target=self._watchdog_loop,
                daemon=True,
                name="engine_worker_watchdog",
            )
            self._watchdog_worker.start()

