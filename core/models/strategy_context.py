"""
Typed strategy context passed to strategies and services.
Replaces dict-based ctx to avoid KeyError, improve refactoring, and enable IDE support.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, List, Optional

if TYPE_CHECKING:
    from core.data.option_chain_service import OptionChainService
    from core.orderExecution.position_manager import PositionManager
    from core.utils.instruments.instrument_store import InstrumentStore


@dataclass
class StrategyContext:
    """
    Immutable core fields are set by the engine; mutable fields (expiry_list,
    selected_expiry, otm_strikes, instrument) are set by option_chain_service/adapters
    during the same candle evaluation.
    """

    # ---- Set once by engine ----
    symbol: str
    exchange: Optional[str]
    timestamp: datetime
    spot_price: float
    instrument_store: "InstrumentStore"
    position_store: "PositionManager"
    option_chain_service: "OptionChainService"

    # ---- Mutable; set by adapters / option chain flow ----
    expiry_list: Optional[List[Any]] = None
    selected_expiry: Optional[Any] = None
    otm_strikes: Optional[List[Any]] = None
    instrument: Optional[Any] = None  # Instrument instance for futures/options

    # ---- Optional; set by engine for strategies that need them (e.g. Futures) ----
    qty: Optional[int] = None
    intent_builder: Optional[Any] = None

    # ---- Optional; set by engine for DHAN equity strategies ----
    universe_service: Optional[Any] = None

    def get_expiry_list(self) -> Optional[List[Any]]:
        """Safe access for expiry_list (may not be set yet)."""
        return self.expiry_list

    def get_selected_expiry(self) -> Optional[Any]:
        """Safe access for selected_expiry."""
        return self.selected_expiry
