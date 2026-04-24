"""
Dhan Live Order Update WebSocket (private stream).

Docs: https://dhanhq.co/docs/v2/order-update/
Endpoint: wss://api-order-update.dhan.co
Auth: JSON with LoginReq MsgCode 42, ClientId, Token, UserType SELF.

Unlike Delta's v2/user_trades, Dhan streams order snapshots (Type: order_alert).
We derive incremental fills from TradedQty / AvgTradedPrice deltas and emit
synthetic trade dicts for OrderRouter.process_trade.

Reconnect: background loop recreates the socket; on_open re-sends LoginReq (auth)
so order_alert stream resumes (same idea as Delta private resubscribe after reconnect).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from typing import Any, Callable, Dict, Optional

import websocket

from core.library.dhan_ws_common import (
    StallWatchdog,
    is_dhan_market_open,
    reconnect_sleep_with_jitter,
    sleep_until_next_dhan_market_open,
)

logger = logging.getLogger(__name__)

DHAN_ORDER_UPDATE_WS_URL = "wss://api-order-update.dhan.co"


def _txn_to_side(txn: Any) -> str:
    s = str(txn or "").strip().upper()
    if s == "B":
        return "BUY"
    if s == "S":
        return "SELL"
    return ""


class DhanOrderUpdateClient:
    """
    Background WebSocket to Dhan order-update stream.
    Calls on_synthetic_trade with incremental fill payloads (pre-intent resolution).
    """

    def __init__(
        self,
        access_token: str,
        client_id: str,
        on_synthetic_trade: Callable[[Dict[str, Any]], None],
        on_auth_ok: Optional[Callable[[], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        stall_timeout_seconds: Optional[float] = None,
    ):
        """
        stall_timeout_seconds: optional zombie detection (no inbound JSON for N sec → close socket).
        Default None disables — quiet accounts may have long gaps with no orders.
        """
        self.access_token = access_token
        self.client_id = str(client_id)
        self.on_synthetic_trade = on_synthetic_trade
        self.on_auth_ok = on_auth_ok
        self.on_error = on_error
        self._stall_timeout_seconds = (
            float(stall_timeout_seconds)
            if stall_timeout_seconds is not None
            else 0.0
        )

        self._ws: Optional[websocket.WebSocketApp] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        # order_no -> {"tq": int, "cum_notional": float}
        self._fill_state: Dict[str, Dict[str, Any]] = {}
        # order_no -> last known order snapshot (status, traded qty, time) for debugging / cancel handling
        self._order_state: Dict[str, Dict[str, Any]] = {}
        self._logged_in = False
        self._connect_generation = 0
        self._reconnect_backoff_sec = 2.0
        self._reconnect_backoff_cap_sec = 180.0
        self._last_activity_ts = time.time()
        self._is_warm = False
        self._cooldown_until_ts = 0.0
        self._failure_timestamps: deque[float] = deque()
        self._reconnect_guard_threshold = 10
        self._reconnect_guard_window_sec = 60.0
        self._reconnect_guard_cooldown_sec = 90.0
        self._stall = StallWatchdog(
            name="DhanOrderUpdateWS",
            stall_sec=self._stall_timeout_seconds,
            get_last_activity_ts=lambda: self._last_activity_ts,
            get_ws=lambda: self._ws,
            should_run=lambda: not self._stop.is_set(),
        )

    def _touch_activity(self) -> None:
        self._last_activity_ts = time.time()

    def _login_payload(self) -> Dict[str, Any]:
        return {
            "LoginReq": {
                "MsgCode": 42,
                "ClientId": self.client_id,
                "Token": self.access_token,
            },
            "UserType": "SELF",
        }

    def _parse_traded_qty(self, data: Dict[str, Any]) -> int:
        raw = data.get("TradedQty")
        try:
            return int(float(raw or 0))
        except (TypeError, ValueError):
            return 0

    def _parse_avg_price(self, data: Dict[str, Any]) -> float:
        raw = data.get("AvgTradedPrice")
        try:
            return float(raw or 0)
        except (TypeError, ValueError):
            return 0.0

    def _parse_traded_price(self, data: Dict[str, Any]) -> float:
        raw = data.get("TradedPrice")
        try:
            return float(raw or 0)
        except (TypeError, ValueError):
            return 0.0

    def _parse_order_quantity(self, data: Dict[str, Any]) -> int:
        raw = data.get("Quantity")
        try:
            return int(float(raw or 0))
        except (TypeError, ValueError):
            return 0

    def _handle_order_data(self, data: Dict[str, Any]) -> None:
        if not isinstance(data, dict):
            return
        order_no = str(data.get("OrderNo") or "").strip()
        if not order_no:
            return

        new_tq = self._parse_traded_qty(data)
        new_avg = self._parse_avg_price(data)
        traded_px = self._parse_traded_price(data)
        order_qty = self._parse_order_quantity(data)
        status_u = str(data.get("Status") or "").strip()
        last_upd = data.get("LastUpdatedTime")
        side = _txn_to_side(data.get("TxnType"))
        if not side:
            return

        correlation_id = str(data.get("CorrelationId") or "").strip()

        with self._lock:
            state = self._fill_state.get(order_no, {"tq": 0, "cum_notional": 0.0})
            prev_tq = int(state.get("tq") or 0)
            prev_cum = float(state.get("cum_notional") or 0.0)

            self._order_state[order_no] = {
                "status": status_u,
                "traded_qty": new_tq,
                "last_update_time": last_upd,
                "order_qty": order_qty,
            }

            # Stale / duplicate: never reduce TradedQty in our model on out-of-order packets
            if new_tq < prev_tq:
                logger.debug(
                    "Dhan order WS: ignoring stale OrderNo=%s (tq %s < prev %s)",
                    order_no,
                    new_tq,
                    prev_tq,
                )
                return

            if new_tq == prev_tq:
                return

            delta = new_tq - prev_tq
            new_cum = float(new_avg) * float(new_tq) if new_tq else 0.0

            incremental_notional = new_cum - prev_cum

            # Slice price priority: TradedPrice (exchange last print) > full-fill avg >
            # notional-delta / qty (rounding can drift — last resort).
            slice_price = 0.0
            if traded_px > 0:
                slice_price = traded_px
            elif prev_tq == 0 and order_qty > 0 and new_tq >= order_qty:
                slice_price = new_avg if new_avg > 0 else traded_px
            elif prev_tq == 0 and new_tq > 0 and delta == new_tq:
                slice_price = new_avg if new_avg > 0 else traded_px
            elif incremental_notional > 0 and delta > 0:
                slice_price = incremental_notional / float(delta)
            if slice_price <= 0:
                slice_price = new_avg
            if slice_price <= 0:
                slice_price = traded_px

            self._fill_state[order_no] = {"tq": new_tq, "cum_notional": new_cum}

        recv_ts = time.time()
        out = {
            "order_no": order_no,
            "correlation_id": correlation_id,
            "delta_qty": int(delta),
            "cumulative_tq": int(new_tq),
            "slice_price": float(slice_price),
            "side": side,
            "status": status_u,
            "last_updated": last_upd,
            "ws_received_at": recv_ts,
        }
        try:
            self.on_synthetic_trade(out)
        except Exception as e:
            logger.debug("Dhan order WS on_synthetic_trade error: %s", e)

    def _on_message(self, _ws: websocket.WebSocketApp, message: str) -> None:
        if isinstance(message, bytes):
            try:
                message = message.decode("utf-8", errors="replace")
            except Exception:
                return
        try:
            msg = json.loads(message)
        except json.JSONDecodeError:
            logger.debug("Dhan order WS non-JSON message (ignored)")
            return

        if not isinstance(msg, dict):
            return

        self._touch_activity()
        mtype = str(msg.get("Type") or "").lower()
        if mtype == "order_alert":
            data = msg.get("Data")
            if isinstance(data, dict):
                self._is_warm = True
                self._handle_order_data(data)
            return

        # Login / heartbeat style responses (structure varies)
        if msg.get("LoginResp") or msg.get("status") == "connected":
            self._logged_in = True
            self._is_warm = True
            if self.on_auth_ok:
                try:
                    self.on_auth_ok()
                except Exception:
                    pass

    def _on_open(self, ws: websocket.WebSocketApp) -> None:
        with self._lock:
            self._connect_generation += 1
            gen = self._connect_generation
        self._reconnect_backoff_sec = 2.0
        self._logged_in = False
        self._is_warm = False
        self._touch_activity()
        logger.info(
            "Dhan order-update WebSocket connected (generation=%s); sending auth",
            gen,
        )
        try:
            ws.send(json.dumps(self._login_payload()))
        except Exception as e:
            logger.warning("Dhan order WS auth send failed: %s", e)

    def _on_error(self, _ws: websocket.WebSocketApp, error: Exception) -> None:
        logger.warning("Dhan order-update WebSocket error: %s", error)
        self._mark_failure(error)
        if self.on_error:
            try:
                self.on_error(error)
            except Exception:
                pass

    def _on_close(
        self,
        _ws: websocket.WebSocketApp,
        close_status_code: Optional[int],
        close_msg: Optional[str],
    ) -> None:
        logger.info(
            "Dhan order-update WebSocket closed: code=%s msg=%s",
            close_status_code,
            close_msg,
        )
        self._mark_failure(close_msg)

    @staticmethod
    def _is_429_signal(err: Any) -> bool:
        msg = str(err or "").lower()
        return "429" in msg or "too many requests" in msg or "blocked" in msg

    def _mark_failure(self, err: Any) -> None:
        now = time.time()
        self._failure_timestamps.append(now)
        while self._failure_timestamps and (
            now - self._failure_timestamps[0] > self._reconnect_guard_window_sec
        ):
            self._failure_timestamps.popleft()
        if self._is_429_signal(err):
            self._cooldown_until_ts = max(
                self._cooldown_until_ts, now + self._reconnect_guard_cooldown_sec
            )
            self._reconnect_backoff_sec = max(self._reconnect_backoff_sec, 20.0)
            logger.warning(
                "Dhan order-update WS entered cooldown after 429 until %s",
                time.strftime("%H:%M:%S", time.localtime(self._cooldown_until_ts)),
            )
            return
        if len(self._failure_timestamps) >= self._reconnect_guard_threshold:
            self._cooldown_until_ts = max(
                self._cooldown_until_ts, now + self._reconnect_guard_cooldown_sec
            )
            self._reconnect_backoff_sec = max(self._reconnect_backoff_sec, 15.0)
            logger.warning(
                "Dhan order-update WS reconnect storm detected; cooling down until %s",
                time.strftime("%H:%M:%S", time.localtime(self._cooldown_until_ts)),
            )

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            if not is_dhan_market_open():
                sleep_until_next_dhan_market_open(stop_event=self._stop, log=logger.info)
                continue
            now = time.time()
            if now < self._cooldown_until_ts:
                time.sleep(min(5.0, self._cooldown_until_ts - now))
                continue
            self._ws = websocket.WebSocketApp(
                DHAN_ORDER_UPDATE_WS_URL,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
            )
            try:
                self._ws.run_forever(ping_interval=25, ping_timeout=20)
            except Exception as e:
                if not self._stop.is_set():
                    logger.warning("Dhan order WS run_forever: %s", e)
            if self._stop.is_set():
                break
            logger.info("Dhan order-update WebSocket scheduling reconnect (jittered backoff)")
            self._reconnect_backoff_sec = reconnect_sleep_with_jitter(
                self._reconnect_backoff_sec, cap=self._reconnect_backoff_cap_sec
            )

    def connect(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._thread_main, daemon=True)
        self._thread.start()
        self._stall.start()
        time.sleep(0.5)

    def _thread_main(self) -> None:
        try:
            self._run_loop()
        finally:
            with self._lock:
                self._thread = None

    def disconnect(self) -> None:
        self._stop.set()
        self._stall.stop()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

    def is_connected(self) -> bool:
        return (
            self._ws is not None
            and self._ws.sock is not None
            and getattr(self._ws.sock, "connected", False)
        )

    @property
    def connect_generation(self) -> int:
        with self._lock:
            return int(self._connect_generation)

    @property
    def is_warm(self) -> bool:
        return bool(self._is_warm)
