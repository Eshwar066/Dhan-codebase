"""
Universe module data models.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class EquityMeta:
    """Metadata for one equity instrument (NSE EQ). From NSE EQUITY_L: symbol, listing_date, isin, market_lot."""

    symbol: str
    listing_date: Optional[datetime] = None
    isin: Optional[str] = None
    market_lot: Optional[int] = None
    security_id: Optional[int] = None  # Filled from broker when needed for LTP/quote API
