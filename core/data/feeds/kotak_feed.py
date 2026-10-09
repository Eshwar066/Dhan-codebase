"""
Kotak Neo live market feed implementing RealtimeFeed.

Uses NeoAPI.create_websocket() (SFeed, neo_api_client >= 2.2.0) on a
background asyncio thread; normalizes ticks onto the CandleAggregator queue
(same shape as DhanWebSocketFeed).
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Dict, List, Optional

from core.data.feeds.base_feed import RealtimeFeed

logger = logging.getLogger(__name__)


def _as_dict(message: Any) -> Any:
    """Best-effort convert SFeed pydantic models / envelopes to dict."""
    if message is None:
        return None
    if isinstance(message, dict):
        return message
    dump = getattr(message, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="python")
        except TypeError:
            return dump()
    # Plain object with attributes
    out: Dict[str, Any] = {}
    for key in (
        "instrument_token",
        "exchange_segment",
        "trading_symbol",
        "last_traded_price",
        "volume_traded_today",
        "last_trade_qty",
        "last_trade_time",
        "last_update_time",
        "ltp",
        "tok",
        "token",
        "symbol",
        "trdSym",
        "data",
    ):
        if hasattr(message, key):
            out[key] = getattr(message, key)
    return out or None


def normalize_kotak_tick(message: Any, symbol_by_token: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """
    Normalize Neo WS / quote payload into {symbol, price, volume, timestamp}.
    ``symbol_by_token`` maps instrument_token → strategy symbol.
    """
    if message is None:
        return None
    if isinstance(message, list):
        for item in message:
            tick = normalize_kotak_tick(item, symbol_by_token)
            if tick:
                return tick
        return None

    message = _as_dict(message)
    if not isinstance(message, dict):
        return None

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
        or str(data.get("symbol") or data.get("trdSym") or data.get("tsym") or data.get("trading_symbol") or "").strip()
    )
    if not symbol and token:
        symbol = symbol_by_token.get(token, "")
    if not symbol:
        return None

    price = None
    for key in (
        "last_traded_price",
        "ltp",
        "LTP",
        "last_price",
        "lastPrice",
        "lp",
        "close",
        "close_price",
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
    for key in ("volume_traded_today", "volume", "v", "vol", "ltq", "last_quantity", "last_trade_qty"):
        if data.get(key) is not None:
            try:
                volume = float(data.get(key) or 0)
                break
            except (TypeError, ValueError):
                continue

    ts = time.time()
    for key in ("timestamp", "t", "ltt", "last_trade_time", "last_update_time", "ft"):
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
    """Realtime Neo SFeed market feed → optional tick queue for CandleAggregator."""

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
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws: Any = None
        for inst in self.instruments:
            tok = str(inst.get("instrument_token") or inst.get("token") or "").strip()
            sym = str(inst.get("symbol") or "").strip().upper()
            if tok and sym:
                self._symbol_by_token[tok] = sym

    def set_tick_queue(self, queue: Any) -> None:
        self._tick_queue = queue

    def _emit_tick(self, message: Any) -> None:
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

    def _build_ws_tokens(self) -> tuple[List[Any], List[Any]]:
        from neo_api_client.websocket.feed import WsToken

        index_tokens: List[Any] = []
        other_tokens: List[Any] = []
        for inst in self.instruments:
            tok = str(inst.get("instrument_token") or inst.get("token") or "").strip()
            seg = str(inst.get("exchange_segment") or "nse_cm").strip()
            if not tok:
                continue
            ws_tok = WsToken(seg, tok)
            if inst.get("isIndex"):
                index_tokens.append(ws_tok)
            else:
                other_tokens.append(ws_tok)
        return index_tokens, other_tokens

    async def _run_feed(self) -> None:
        index_tokens, other_tokens = self._build_ws_tokens()
        if not index_tokens and not other_tokens:
            logger.warning("KotakWebSocketFeed: no tokens to subscribe")
            return

        while not self._stop.is_set():
            try:
                async with self._api.create_websocket() as ws:
                    self._ws = ws
                    if index_tokens:
                        try:
                            await ws.snapshot(index_tokens, intent="index")
                        except Exception as e:
                            logger.debug("Kotak index snapshot: %s", e)
                        await ws.subscribe_index(index_tokens)
                    if other_tokens:
                        try:
                            await ws.snapshot(other_tokens, intent="scrips")
                        except Exception as e:
                            logger.debug("Kotak scrips snapshot: %s", e)
                        await ws.subscribe_scrips(other_tokens)
                    self._connected = True
                    logger.info(
                        "KotakWebSocketFeed SFeed subscribed index=%s other=%s",
                        len(index_tokens),
                        len(other_tokens),
                    )
                    async for msg in ws:
                        if self._stop.is_set():
                            break
                        self._emit_tick(msg)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._connected = False
                if self._stop.is_set():
                    break
                logger.warning("KotakWebSocketFeed disconnected: %s; reconnecting in 5s", e)
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
        if not self.instruments:
            logger.warning("KotakWebSocketFeed start skipped: no instruments")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._thread_main,
            name="KotakWebSocketFeed",
            daemon=True,
        )
        self._thread.start()
        # Brief wait so factory can observe early auth/connect failures in logs
        deadline = time.time() + 3.0
        while time.time() < deadline and not self._connected and self._thread.is_alive():
            time.sleep(0.05)
        if not self._thread.is_alive():
            raise RuntimeError("KotakWebSocketFeed thread exited during start")
        logger.info("KotakWebSocketFeed thread started")

    def stop(self) -> None:
        self._stop.set()
        loop = self._loop
        ws = self._ws
        if loop and ws is not None:
            try:
                fut = asyncio.run_coroutine_threadsafe(ws.close(), loop)
                fut.result(timeout=5.0)
            except Exception as e:
                logger.debug("KotakWebSocketFeed close: %s", e)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=8.0)
        self._thread = None
        self._connected = False

    def is_connected(self) -> bool:
        return bool(self._connected)

    def get_last_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        return self._last_ticker.get(str(symbol or "").strip().upper())
