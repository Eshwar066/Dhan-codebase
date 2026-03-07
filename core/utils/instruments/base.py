"""
Shared instrument model and abstract store interface.
Broker-specific logic lives in dhan.py and delta.py.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from run.config import RUN_MODE, RunMode


class Instrument:
    """Single tradable contract (option/future/equity). Used by order intents and position manager."""

    def __init__(
        self,
        trading_symbol,
        custom_symbol,
        exchange,
        segment,
        instrument_type,
        lot_size=1,
        contract_multiplier=1,
        expiry=None,
        strike=None,
        option_type=None,
        instrument_id=None,
        series=None,
    ):
        self.trading_symbol = trading_symbol
        self.custom_symbol = custom_symbol
        self.exchange = exchange
        self.segment = segment
        self.instrument_type = instrument_type
        self.expiry = expiry
        self.strike = strike
        self.option_type = option_type
        self.instrument_id = instrument_id
        self.series = series
        self.lot_size = lot_size
        self.contract_multiplier = contract_multiplier

    def __repr__(self):
        return (
            f"Instrument("
            f"{self.custom_symbol}, "
            f"{self.exchange}, "
            f"{self.segment}, "
            f"{self.instrument_type}, "
            f"expiry={self.expiry}, "
            f"strike={self.strike}, "
            f"option_type={self.option_type}"
            f")"
        )

    @property
    def contract_key(self):
        """Uniquely identifies a tradable contract (netting, hedges, rollovers)."""
        return (
            self.exchange,
            self.segment,
            self.instrument_type,
            (self.custom_symbol or "").split()[0],
            self.expiry,
            self.strike,
            self.option_type,
        )


class BaseInstrumentStore(ABC):
    """Broker-specific instrument store: load + lookup by symbol/expiry."""

    @abstractmethod
    def intent_creation_details(
        self, trading_symbol, exchange, expiry, option_type, strike
    ) -> Optional[Instrument]:
        """Resolve option contract to Instrument for order intent. Returns None if not found."""
        raise NotImplementedError

    @abstractmethod
    def futures_intent_creation_details(
        self, trading_symbol: str, exchange: str, expiry
    ) -> Optional[Instrument]:
        """Resolve futures contract to Instrument. Returns None if not found."""
        raise NotImplementedError

    def get_tick_size(self, symbol: str) -> Optional[float]:
        """Return tick size for symbol when known; None otherwise. Override in broker implementations."""
        return None

    def get_lot_size(self, symbol: str) -> Optional[int]:
        """Return lot size for symbol when known; None otherwise. Override in broker implementations."""
        return None
