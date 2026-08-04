"""
Kotak Neo private order-update feed (fills → synthetic trades for LiveEngine).

Uses NeoAPI.create_order_feed() (neo_api_client >= 2.2.0) on a background
asyncio thread.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


def _as_dict(message: Any) -> Any:
    if message is None:
        return None
    if isinstance(message, dict):
        return message
    dump = getattr(message, "model_dump", None)
    if callable(dump):
        try:
            # Prefer wire aliases (nOrdNo, ordSt, …) for normalize_kotak_order_update
            return dump(mode="python", by_alias=True)
        except TypeError:
            try:
                return dump(by_alias=True)
            except TypeError:
                return dump()
    data_attr = getattr(message, "data", None)
    if data_attr is not None:
        nested = _as_dict(data_attr)
        return {"type": getattr(message, "type", "order"), "data": nested}
    return None


def normalize_kotak_order_update(message: Any) -> Optional[Dict[str, Any]]:
    """
    Normalize Neo order-feed payload into a synthetic trade dict:
    {trade_id, order_id, symbol, side, qty, price, status, raw}
    """
    if message is None:
        return None
    if isinstance(message, list):
        for item in message:
            out = normalize_kotak_order_update(item)
            if out:
                return out
        return None

    message = _as_dict(message)
    if not isinstance(message, dict):
        return None
    data = message.get("data") if isinstance(message.get("data"), dict) else message
    if isinstance(message.get("data"), list) and message["data"]:
        return normalize_kotak_order_update(message["data"])
    data = _as_dict(data) if not isinstance(data, dict) else data
    if not isinstance(data, dict):
        return None

    order_id = str(
        data.get("nOrdNo")
        or data.get("order_id")
        or data.get("orderId")
        or data.get("NOrdNo")
        or ""
    ).strip()
    symbol = str(
        data.get("trdSym")
        or data.get("trading_symbol")
        or data.get("tsym")
        or data.get("symbol")
        or ""
    ).strip()
    status = str(
        data.get("ordSt")
        or data.get("status")
        or data.get("order_status")
        or ""
    ).strip().upper()
    side_raw = str(
        data.get("trantype")
        or data.get("transaction_type")
        or data.get("trnsTp")
        or data.get("side")
        or ""
    ).strip().upper()
    side = "BUY" if side_raw in {"B", "BUY"} else "SELL" if side_raw in {"S", "SELL"} else side_raw

    qty = 0.0
    for key in ("fldQty", "filled_qty", "filled_quantity", "fillShares", "qty", "quantity", "tokQty"):
        if data.get(key) is not None:
            try:
                qty = float(data.get(key) or 0)
                break
            except (TypeError, ValueError):
                continue
    price = 0.0
    for key in ("avgPrc", "avg_price", "average_price", "fillPrice", "price", "ltp", "prc"):
        if data.get(key) is not None:
            try:
                price = float(data.get(key) or 0)
                break
            except (TypeError, ValueError):
                continue

    filled_like = status in {
        "COMPLETE",
        "COMPLETED",
        "TRADED",
        "FILLED",
        "PARTIALLY_TRADED",
        "PARTIAL",
        "EXECUTED",
    }
    if not order_id or not filled_like or qty <= 0 or price <= 0:
        if order_id and status in {"REJECTED", "CANCELLED", "CANCELED"}:
            return {
                "trade_id": f"KOTAK_WS:{order_id}:{status}",
                "order_id": f"KOTAK_WS:{order_id}",
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "price": price,
                "status": status,
                "raw": data,
            }
        return None

    trade_id = f"KOTAK_WS:{order_id}:{int(qty)}:{price}"
    return {
        "trade_id": trade_id,
        "order_id": f"KOTAK_WS:{order_id}",
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "price": price,
        "status": status,
        "raw": data,
    }


class KotakOrderUpdateFeed:
    """Async OrderFeedWebSocket → synthetic trade callback for LiveEngine."""

    def __init__(self, neo_api: Any):
        self._api = neo_api
        self._callback: Optional[Callable[[Dict[str, Any]], None]] = None
        self._connected = False
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws: Any = None

    def set_synthetic_trade_callback(
        self, callback: Callable[[Dict[str, Any]], None]
    ) -> None:
        self._callback = callback

    def _on_message(self, message: Any) -> None:
        trade = normalize_kotak_order_update(message)
        if not trade:
            return
        cb = self._callback
        if not cb:
            return
        try:
            cb(trade)
        except Exception as e:
            logger.debug("KotakOrderUpdateFeed callback error: %s", e)

    async def _run_feed(self) -> None:
        while not self._stop.is_set():
            try:
                async with self._api.create_order_feed() as feed:
                    self._ws = feed
                    self._connected = True
                    logger.info("KotakOrderUpdateFeed connected")
                    async for message in feed:
                        if self._stop.is_set():
                            break
                        self._on_message(message)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._connected = False
                if self._stop.is_set():
                    break
                logger.warning(
                    "KotakOrderUpdateFeed disconnected: %s; reconnecting in 5s", e
                )
                await asyncio.sleep(5.0)
            finally:
                self._ws = None
                self._connected = False

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run_feed())
        finally:
            try:
                loop.close()
            except Exception:
                pass
            self._loop = None
            self._connected = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._thread_main,
            name="KotakOrderUpdateFeed",
            daemon=True,
        )
        self._thread.start()
        deadline = time.time() + 3.0
        while time.time() < deadline and not self._connected and self._thread.is_alive():
            time.sleep(0.05)
        logger.info("KotakOrderUpdateFeed thread started")

    def stop(self) -> None:
        self._stop.set()
        loop = self._loop
        ws = self._ws
        if loop and ws is not None:
            try:
                fut = asyncio.run_coroutine_threadsafe(ws.close(), loop)
                fut.result(timeout=5.0)
            except Exception as e:
                logger.debug("KotakOrderUpdateFeed close: %s", e)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=8.0)
        self._thread = None
        self._connected = False

    def is_connected(self) -> bool:
        return bool(self._connected)
