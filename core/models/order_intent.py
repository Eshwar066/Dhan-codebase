from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from core.utils.instruments.instrument_store import Instrument


@dataclass(frozen=True)
class OrderIntent:
    # identity
    intent_id: str
    instrument: Instrument

    # execution
    side: str  # BUY / SELL
    qty: int
    price: float | None
    order_type: str  # MARKET / LIMIT / SL / SL-M

    # strategy metadata
    strategy: str
    structure_id: str
    trade_type: str  # ENTRY / EXIT / HEDGE
    tag: str | None
    symbol: str
    action: str

    # timing / linkage
    candle_ts: datetime
    parent_intent_id: str | None = None
    # Optional JSON-serializable blob (e.g. strategy ML1 state); stored on intent payload as strategy_meta
    metadata_extras: Optional[dict[str, Any]] = None
