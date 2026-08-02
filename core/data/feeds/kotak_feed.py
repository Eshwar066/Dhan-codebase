"""
Kotak Neo live market feed implementing RealtimeFeed.

Uses NeoAPI.subscribe / NeoWebSocket callbacks; normalizes ticks onto the
CandleAggregator queue (same shape as DhanWebSocketFeed).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from core.data.feeds.base_feed import RealtimeFeed

logger = logging.getLogger(__name__)


def normalize_kotak_tick(message: Any, symbol_by_token: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """
    Normalize Neo WS / quote payload into {symbol, price, volume, timestamp}.
    ``symbol_by_token`` maps instrument_token → strategy symbol.
    """
    if message is None:
        return None
    if isinstance(message, list):
        # Prefer first parseable item
        for item in message:
            tick = normalize_kotak_tick(item, symbol_by_token)
            if tick:
                return tick
        return None
    if not isinstance(message, dict):
        return None

    # Unwrap common envelopes
    data = message.get("data") if isinstance(message.get("data"), dict) else message
    if isinstance(message.get("data"), list) and message["data"]:
        return normalize_kotak_tick(message["data"], symbol_by_token)

    token = str(
        data.get("instrument_token")
        or data.get("tok")
        or data.get("token")
        or data.get("ts")
        or data.get("iTok")
        or ""
    ).strip()
    symbol = (
        symbol_by_token.get(token)
        or str(data.get("symbol") or data.get("trdSym") or data.get("tsym") or "").strip()
    )
    if not symbol and token:
        symbol = symbol_by_token.get(token, "")
    if not symbol:
        return None

    price = None
    for key in (
        "ltp",
        "LTP",
        "last_price",
        "lastPrice",
        "lp",
        "close",
        "avgPrice",
        "ap",
    ):
        if data.get(key) is not None:
            try:
                price = float(data.get(key))
                break
            except (TypeError, ValueError):
                continue
    if price is None or price <= 0:
        return None

    volume = 0.0
    for key in ("volume", "v", "vol", "ltq", "last_quantity"):
        if data.get(key) is not None:
            try:
                volume = float(data.get(key) or 0)
                break
            except (TypeError, ValueError):
                continue

    ts = time.time()
    for key in ("timestamp", "t", "ltt", "last_trade_time", "ft"):
        raw = data.get(key)
        if raw is None:
            continue
        try:
            candidate = float(raw)
            if candidate > 1e12:
                candidate /= 1000.0
            if candidate > 1e9:
                ts = candidate
                break
        except (TypeError, ValueError):
            continue

    return {
        "symbol": str(symbol).strip().upper(),
        "price": float(price),
        "volume": float(volume),
        "timestamp": float(ts),
    }


class KotakWebSocketFeed(RealtimeFeed):
    """Realtime Neo market feed → optional tick queue for CandleAggregator."""

    def __init__(
        self,
        neo_api: Any,
        instruments: List[Dict[str, Any]],
        engine_logger: Optional[Any] = None,
        debug_mode: bool = False,
    ):
        """
        instruments: list of {
          "instrument_token": "...",
          "exchange_segment": "nse_cm",
          "symbol": "NIFTY",
          "isIndex": bool (optional),
        }
        """
        self._api = neo_api
        self.instruments = list(instruments or [])
        self._engine_logger = engine_logger
        self._debug_mode = bool(debug_mode)
        self._tick_queue: Optional[Any] = None
        self._connected = False
        self._last_ticker: Dict[str, Dict[str, Any]] = {}
        self._symbol_by_token: Dict[str, str] = {}
        for inst in self.instruments:
            tok = str(inst.get("instrument_token") or inst.get("token") or "").strip()
            sym = str(inst.get("symbol") or "").strip().upper()
            if tok and sym:
                self._symbol_by_token[tok] = sym

    def set_tick_queue(self, queue: Any) -> None:
        self._tick_queue = queue

    def _on_message(self, message: Any) -> None:
        tick = normalize_kotak_tick(message, self._symbol_by_token)
        if not tick:
            return
        self._last_ticker[tick["symbol"]] = {
            "close": tick["price"],
            "ltp": tick["price"],
            "symbol": tick["symbol"],
            "volume": tick["volume"],
            "timestamp": tick["timestamp"],
        }
        if self._tick_queue is not None:
            try:
                self._tick_queue.put_nowait(tick)
            except Exception:
                try:
                    self._tick_queue.put(tick, timeout=0.01)
                except Exception as e:
                    if self._debug_mode:
                        logger.debug("Kotak tick queue full/drop: %s", e)

    def _on_error(self, message: Any) -> None:
        logger.warning("KotakWebSocketFeed error: %s", message)
        self._connected = False

    def _on_close(self, message: Any = None) -> None:
        logger.info("KotakWebSocketFeed closed: %s", message)
        self._connected = False

    def _on_open(self, message: Any = None) -> None:
        logger.info("KotakWebSocketFeed open")
        self._connected = True

    def start(self) -> None:
        if not self.instruments:
            logger.warning("KotakWebSocketFeed start skipped: no instruments")
            return
        self._api.on_message = self._on_message
        self._api.on_error = self._on_error
        self._api.on_close = self._on_close
        self._api.on_open = self._on_open

        # Group by isIndex for Neo subscribe API
        index_tokens = []
        other_tokens = []
        for inst in self.instruments:
            tok = {
                "instrument_token": str(
                    inst.get("instrument_token") or inst.get("token") or ""
                ),
                "exchange_segment": str(
                    inst.get("exchange_segment") or "nse_cm"
                ),
            }
            if not tok["instrument_token"]:
                continue
            if inst.get("isIndex"):
                index_tokens.append(tok)
            else:
                other_tokens.append(tok)

        try:
            if index_tokens:
                self._api.subscribe(index_tokens, isIndex=True, isDepth=False)
            if other_tokens:
                self._api.subscribe(other_tokens, isIndex=False, isDepth=False)
            self._connected = True
            logger.info(
                "KotakWebSocketFeed subscribed index=%s other=%s",
                len(index_tokens),
                len(other_tokens),
            )
        except Exception as e:
            self._connected = False
            logger.exception("KotakWebSocketFeed subscribe failed: %s", e)
            raise

    def stop(self) -> None:
        try:
            tokens = [
                {
                    "instrument_token": str(
                        i.get("instrument_token") or i.get("token") or ""
                    ),
                    "exchange_segment": str(i.get("exchange_segment") or "nse_cm"),
                }
                for i in self.instruments
                if i.get("instrument_token") or i.get("token")
            ]
            if tokens and hasattr(self._api, "un_subscribe"):
                self._api.un_subscribe(tokens)
        except Exception as e:
            logger.debug("KotakWebSocketFeed unsubscribe: %s", e)
        self._connected = False

    def is_connected(self) -> bool:
        return bool(self._connected)

    def get_last_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        return self._last_ticker.get(str(symbol or "").strip().upper())
