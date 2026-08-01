"""Event types and payloads for the live engine event bus."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class EventType(str, Enum):
    BAR_CLOSED = "BarClosed"
    SCHEDULED_SLOT = "ScheduledSlot"
    QUOTE_UPDATED = "QuoteUpdated"
    INTENT_CREATED = "IntentCreated"
    INTENT_FILLED = "IntentFilled"
    POSITION_CLOSED = "PositionClosed"
    FEED_DISCONNECTED = "FeedDisconnected"
    FEED_RECOVERED = "FeedRecovered"


@dataclass(frozen=True)
class Event:
    type: EventType
    payload: Dict[str, Any]
    ts: float
    engine_id: str
    trace_id: Optional[str] = None

    def to_log_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "ts": self.ts,
            "engine_id": self.engine_id,
            "trace_id": self.trace_id,
            "payload": self.payload,
        }


def make_event(
    event_type: EventType,
    payload: Dict[str, Any],
    *,
    engine_id: str,
    ts: Optional[float] = None,
    trace_id: Optional[str] = None,
) -> Event:
    return Event(
        type=event_type,
        payload=dict(payload or {}),
        ts=float(ts if ts is not None else time.time()),
        engine_id=str(engine_id or "live"),
        trace_id=trace_id or uuid.uuid4().hex[:12],
    )
