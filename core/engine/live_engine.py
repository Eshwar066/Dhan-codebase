"""
LiveEngine: production-grade live/paper engine with reconciliation,
kill switch, closed-candle validation, feed health, EOD export, and structured logging.
"""

import csv
import os
import time
import datetime as dt
from typing import Any, Dict, Optional

from core.engine.base_engine import BaseEngine

try:
    from logs.engine_logger import REPORTS_DIR
except ImportError:
    REPORTS_DIR = "reports"

DEFAULT_FEED_STALE_SECONDS = 60


class LiveEngine(BaseEngine):
    """
    Live/paper engine. Optional realtime_feed (WebSocket); falls back to
    candle_service / data.get_latest_candles. Supports broker reconciliation,
    risk kill switch, closed-candle validation, feed health, EOD export.
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
    ):
        super().__init__(strategy, data, instrument_store, position_manager)
        self.symbols = symbols
        self.candle_service = candle_service
        self.order_router = order_router
        self.position_manager = position_manager
        self.realtime_feed = realtime_feed
        self.engine_id = engine_id or "live"
        self.venue = venue or ""
        self.engine_logger = engine_logger
        self.feed_stale_seconds = feed_stale_seconds
        self._last_tick_timestamp: Dict[str, float] = {}
        self._last_candle_timestamp: Dict[str, float] = {}
        self._last_eod_date: Optional[str] = None
        self._entries_paused_feed_stale = False

    def reconcile_positions_on_start(self) -> None:
        """
        Fetch broker positions, sync PositionManager to broker truth, log any mismatch.
        Must run before live loop starts.
        """
        broker = getattr(self.order_router, "broker", None)
        if not broker or not hasattr(broker, "get_positions_for_recon"):
            if self.engine_logger:
                self.engine_logger.reconciliation("No broker or get_positions_for_recon; skip reconcile")
            return
        try:
            broker_positions = broker.get_positions_for_recon()
        except Exception as e:
            if self.engine_logger:
                self.engine_logger.reconciliation(f"Failed to fetch broker positions: {e}")
            return
        local_snapshot = self.position_manager.snapshot()
        diff = []
        for sym, bp in broker_positions.items():
            local = local_snapshot.get(sym, {})
            lq = local.get("qty", 0)
            bq = int(bp.get("qty", 0))
            if lq != bq or abs(local.get("avg_price", 0) - float(bp.get("avg_price", 0))) > 0.01:
                diff.append({"symbol": sym, "local_qty": lq, "broker_qty": bq, "broker_avg": bp.get("avg_price")})
        for sym in set(local_snapshot.keys()) - set(broker_positions.keys()):
            if local_snapshot[sym].get("qty", 0) != 0:
                diff.append({"symbol": sym, "local_qty": local_snapshot[sym].get("qty"), "broker_qty": 0})
        if diff and self.engine_logger:
            self.engine_logger.reconciliation("Position mismatch; syncing PM to broker", details={"diff": diff})
        self.position_manager.reconcile_with_broker(broker_positions)

    def _is_closed_candle(self, candle: Dict, timeframe: str, now: Optional[dt.datetime] = None) -> bool:
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
            ts_dt = ts if isinstance(ts, dt.datetime) else dt.datetime.fromisoformat(str(ts))
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
        for symbol in self.symbols:
            last_tick = self._last_tick_timestamp.get(symbol, 0)
            last_candle = self._last_candle_timestamp.get(symbol, 0)
            stale = (now - max(last_tick, last_candle)) > self.feed_stale_seconds
            if stale and (last_tick or last_candle) and self.engine_logger:
                self.engine_logger.feed_health_warning(
                    f"No data for {symbol} in {self.feed_stale_seconds}s",
                    symbol=symbol,
                )
                self._entries_paused_feed_stale = True

    def _export_eod(self, date_str: str) -> None:
        """Export open positions, realized pnl to reports/{engine_id}_{date}.csv."""
        reports_dir = REPORTS_DIR
        os.makedirs(reports_dir, exist_ok=True)
        path = os.path.join(reports_dir, f"{self.engine_id}_{date_str}.csv")
        rows = []
        for sym, pos in self.position_manager.positions.items():
            if pos.net_qty == 0:
                continue
            rows.append({
                "symbol": sym,
                "qty": pos.net_qty,
                "avg_price": pos.avg_price,
                "realized_pnl": pos.realized_pnl,
                "unrealized_pnl": "",
            })
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["symbol", "qty", "avg_price", "realized_pnl", "unrealized_pnl"])
            w.writeheader()
            w.writerows(rows)
        if self.engine_logger:
            self.engine_logger.eod_export(path)

    def start(self, exchange, sector, rsi):
        if self.engine_logger:
            self.engine_logger.log("engine_start", "Live engine started")
        else:
            print("Live engine started")

        self.reconcile_positions_on_start()
        tf = getattr(self.strategy, "timeframe", None)
        use_feed = self.realtime_feed and self.realtime_feed.is_connected()
        risk_manager = getattr(self.order_router, "risk", None)
        loop_count = 0

        while True:
            loop_count += 1
            if risk_manager and risk_manager.is_engine_blocked():
                if self.engine_logger:
                    self.engine_logger.log("risk_block", "Engine blocked by kill switch; skipping entries")
                time.sleep(1)
                continue

            self.check_feed_health()
            if loop_count % 60 == 0:
                today = dt.datetime.utcnow().strftime("%Y%m%d")
                if self._last_eod_date and self._last_eod_date != today:
                    self._export_eod(self._last_eod_date)
                self._last_eod_date = today

            if tf:
                for symbol in self.symbols:
                    candle = None
                    if use_feed:
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

                    if not self._is_closed_candle(candle, tf):
                        if self.engine_logger:
                            self.engine_logger.closed_candle_skip(symbol, "Forming or misaligned candle; skip evaluation")
                        continue

                    if not self.strategy.should_evaluate(candle):
                        continue

                    t0 = time.perf_counter()
                    ctx, intent = self.build_context(candle)
                    strategy_time_ms = (time.perf_counter() - t0) * 1000
                    if intent and self._entries_paused_feed_stale:
                        continue
                    self._run_strategy(symbol, candle, ctx, intent, strategy_time_ms=strategy_time_ms)
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
                    t0 = time.perf_counter()
                    ctx, intent = self.build_context(candle)
                    strategy_time_ms = (time.perf_counter() - t0) * 1000
                    self._run_strategy(symbol, candle, ctx, intent, strategy_time_ms=strategy_time_ms)

            use_feed = self.realtime_feed and self.realtime_feed.is_connected()
            time.sleep(1)

    def get_price_map(self, symbol):
        if self.realtime_feed and self.realtime_feed.is_connected():
            ticker = self.realtime_feed.get_last_ticker(symbol)
            if ticker and ticker.get("close") is not None:
                return ticker["close"]
        if self.data:
            candles = self.data.get_latest_candles([symbol])
            if candles and symbol in candles and candles[symbol].get("close") is not None:
                return candles[symbol]["close"]
        return None

    def _run_strategy(self, symbol, candle, ctx, intent, strategy_time_ms: Optional[float] = None):
        risk_manager = getattr(self.order_router, "risk", None)
        open_positions = self.position_manager.get_open_positions(
            symbol=symbol, strategy=self.strategy.name
        )

        for position in open_positions:
            exit_signal = self.strategy.should_exit(position, candle, ctx)
            if exit_signal:
                exit_intent = self.strategy.create_exit_intent(position, exit_signal)
                price_map = self.get_price_map(symbol)
                if price_map is not None:
                    if self.engine_logger:
                        self.engine_logger.exit_triggered(symbol, "SELL" if position.net_qty > 0 else "BUY", abs(position.net_qty), "Strategy exit")
                    self.order_router.process_intent(exit_intent, price_map)

        if intent:
            if risk_manager and risk_manager.is_engine_blocked():
                return
            price_map = candle.get("close")
            if price_map is not None:
                t0 = time.perf_counter()
                self.order_router.process_intent(intent, price_map)
                broker_latency_ms = (time.perf_counter() - t0) * 1000
                if self.engine_logger and strategy_time_ms is not None:
                    self.engine_logger.latency(
                        strategy_time_ms=strategy_time_ms,
                        broker_latency_ms=broker_latency_ms,
                        total_latency_ms=strategy_time_ms + broker_latency_ms,
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
