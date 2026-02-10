from dataclasses import dataclass
from datetime import datetime


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
