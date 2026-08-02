"""
Kotak Neo private order-update feed (fills → synthetic trades for LiveEngine).
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


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
    if not isinstance(message, dict):
        return None
    data = message.get("data") if isinstance(message.get("data"), dict) else message
    if isinstance(message.get("data"), list) and message["data"]:
        return normalize_kotak_order_update(message["data"])

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
    for key in ("fldQty", "filled_qty", "fillShares", "qty", "quantity", "tokQty"):
        if data.get(key) is not None:
            try:
                qty = float(data.get(key) or 0)
                break
            except (TypeError, ValueError):
                continue
    price = 0.0
    for key in ("avgPrc", "avg_price", "fillPrice", "price", "ltp", "prc"):
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
        # Still emit rejected/cancelled for diagnostics when order_id present
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
    """Thin wrapper around NeoAPI.subscribe_to_orderfeed for LiveEngine."""

    def __init__(self, neo_api: Any):
        self._api = neo_api
        self._callback: Optional[Callable[[Dict[str, Any]], None]] = None
        self._connected = False

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

    def _on_error(self, message: Any) -> None:
        logger.warning("KotakOrderUpdateFeed error: %s", message)
        self._connected = False

    def _on_open(self, message: Any = None) -> None:
        self._connected = True

    def _on_close(self, message: Any = None) -> None:
        self._connected = False

    def start(self) -> None:
        # Order feed shares NeoWebSocket; set callbacks then subscribe.
        prev_msg = getattr(self._api, "on_message", None)

        def _fanout(message: Any) -> None:
            if callable(prev_msg):
                try:
                    prev_msg(message)
                except Exception:
                    pass
            self._on_message(message)

        self._api.on_message = _fanout
        self._api.on_error = self._on_error
        self._api.on_open = self._on_open
        self._api.on_close = self._on_close
        try:
            self._api.subscribe_to_orderfeed()
            self._connected = True
            logger.info("KotakOrderUpdateFeed subscribed")
        except Exception as e:
            self._connected = False
            logger.exception("KotakOrderUpdateFeed subscribe failed: %s", e)
            raise

    def stop(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return bool(self._connected)
