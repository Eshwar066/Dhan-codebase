from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Position:
    # ---- Instrument ----
    symbol: str  # NIFTY, BANKNIFTY, RELIANCE
    side: str  # BUY / SELL
    qty: int

    # ---- Trade details ----
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None

    sl: Optional[float] = None  # Stop Loss
    target: Optional[float] = None  # Target

    # ---- Options specific (optional) ----
    option_type: Optional[str] = None  # CALL / PUT
    strike: Optional[float] = None
    expiry: Optional[datetime] = None

    # ---- Lifecycle ----
    status: str = "OPEN"  # OPEN / CLOSED / CANCELLED
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None

    # ---- PnL ----
    pnl: float = 0.0

    # ---- Metadata ----
    note: Optional[str] = None
    broker_order_id: Optional[str] = None

    def is_open(self) -> bool:
        return self.status == "OPEN"

    def close(self, exit_price: float, exit_time: Optional[datetime] = None):
        self.exit_price = exit_price
        self.exit_time = exit_time or datetime.now()
        self.status = "CLOSED"

        if self.entry_price is not None:
            direction = 1 if self.side == "BUY" else -1
            self.pnl = (exit_price - self.entry_price) * self.qty * direction
