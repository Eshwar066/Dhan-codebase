"""Engine context passed to event handlers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from core.events.bus import EventBus


@dataclass
class EngineEventContext:
    """Thin wrapper around LiveEngine for handler access."""

    engine: Any
    bus: EventBus
    engine_id: str
    engine_logger: Optional[Any] = None

    @classmethod
    def from_engine(cls, engine: Any, bus: EventBus) -> "EngineEventContext":
        return cls(
            engine=engine,
            bus=bus,
            engine_id=str(getattr(engine, "engine_id", None) or "live"),
            engine_logger=getattr(engine, "engine_logger", None),
        )
