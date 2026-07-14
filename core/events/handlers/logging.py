"""Structured event tap — optional JSONL audit log."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from core.events.context import EngineEventContext
from core.events.types import Event, EventType

logger = logging.getLogger(__name__)

# Keep tap payloads small — dumping StrategyContext / live objects grew events.jsonl
# by tens of KB per bar and caused GC/I/O pressure on small droplets.
_OHLC_KEYS = ("symbol", "exchange", "timestamp", "open", "high", "low", "close", "volume", "bucket_ts")


def _summarize_intent(intent: Any) -> Any:
    if intent is None:
        return None
    if isinstance(intent, list):
        return [_summarize_intent(x) for x in intent]
    try:
        inst = getattr(intent, "instrument", None)
        return {
            "intent_id": getattr(intent, "intent_id", None),
            "symbol": getattr(intent, "symbol", None)
            or getattr(inst, "trading_symbol", None),
            "side": getattr(intent, "side", None),
            "qty": getattr(intent, "qty", None),
            "price": getattr(intent, "price", None),
            "order_type": getattr(intent, "order_type", None),
            "strategy": getattr(intent, "strategy", None),
            "structure_id": getattr(intent, "structure_id", None),
            "tag": getattr(intent, "tag", None),
            "action": getattr(intent, "action", None),
        }
    except Exception:
        return str(intent)[:200]


def _summarize_candle(candle: Any) -> Any:
    if not isinstance(candle, dict):
        return str(candle)[:200] if candle is not None else None
    return {k: candle.get(k) for k in _OHLC_KEYS if k in candle}


def sanitize_event_payload_for_log(payload: Any) -> Any:
    """Shrink event payloads for disk tap (never stringify full ctx/strategy)."""
    if not isinstance(payload, dict):
        return payload
    out: Dict[str, Any] = {}
    for key, val in payload.items():
        if key == "ctx":
            continue
        if key == "strategy":
            out[key] = str(getattr(val, "name", None) or val)[:120]
            continue
        if key == "intent":
            out[key] = _summarize_intent(val)
            continue
        if key == "candle":
            out[key] = _summarize_candle(val)
            continue
        if key in ("intents",) and isinstance(val, list):
            out[key] = [_summarize_intent(x) for x in val]
            continue
        try:
            json.dumps(val, default=str)
            out[key] = val
        except TypeError:
            out[key] = str(val)[:200]
    return out


class EventTapHandler:
    def __init__(self, ctx: EngineEventContext, log_path: Optional[Path] = None) -> None:
        self._ctx = ctx
        self._log_path = log_path

    def __call__(self, event: Event) -> None:
        if self._log_path is None:
            return
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "type": event.type.value,
                "ts": event.ts,
                "engine_id": event.engine_id,
                "trace_id": event.trace_id,
                "payload": sanitize_event_payload_for_log(event.payload),
            }
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, default=str) + "\n")
        except Exception:
            logger.debug("Event tap write failed", exc_info=True)


def register_event_tap(
    ctx: EngineEventContext, *, enabled: bool = True
) -> None:
    if not enabled:
        return
    log_dir = Path("logs")
    path = log_dir / f"{ctx.engine_id}_events.jsonl"
    tap = EventTapHandler(ctx, path)
    for event_type in EventType:
        ctx.bus.subscribe(
            event_type,
            tap,
            priority=1000,
            name="event_tap",
        )
