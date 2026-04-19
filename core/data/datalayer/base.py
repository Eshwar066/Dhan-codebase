"""
Data layer: abstract interface for all market data feeding the engines.

Pro-level algo: LTP, option chain, expiry list, candles are provided only
via this layer. Engines and option_chain_service depend on IDataProvider,
not on any specific broker or exchange implementation.
"""

from abc import ABC, abstractmethod
from typing import Any, List, Optional
import pandas as pd


class IDataProvider(ABC):
    """
    Contract for market data used by engines and order management.
    Implementations: DhanDataProvider, NseDataProvider, (future: DeltaDataProvider).
    """

    # ---------- Candles / OHLC ----------
    @abstractmethod
    def get_intraday(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        timeframe: str,
        exchange: str,
        sector: str,
    ) -> Optional[pd.DataFrame]:
        """Historical intraday candles for backtest."""
        raise NotImplementedError

    @abstractmethod
    def get_latest_candles(self, symbols: List[str], debug: str = "NO") -> Optional[dict]:
        """Latest OHLC/LTP per symbol (live/tick mode)."""
        raise NotImplementedError

    # ---------- Expiries ----------
    @abstractmethod
    def get_live_expiry(self, symbol: str, exchange: str) -> Any:
        """Live expiry list (broker-specific format, e.g. indices)."""
        raise NotImplementedError

    def get_nse_expiries(
        self, symbol: str, year: int, instrument: str = "OPTIDX"
    ) -> List[Any]:
        """NSE expiry dates for a symbol/year. Optional for non-NSE providers."""
        return []

    # ---------- Option chain: live ----------
    def get_live_option_chain(
        self,
        symbol: str,
        exchange: str,
        expiry_index: int,
        strikes_around_atm: int,
        expiry_flag: str,
    ) -> Optional[dict]:
        """Live option chain (e.g. Dhan format)."""
        raise NotImplementedError

    # ---------- Option chain: historical (backtest) ----------
    def get_expired_optionchain(
        self,
        exchange: str,
        interval: str,
        expiry_flag: str,
        expiry_code: Any,
        strike: Any,
        option_type: str,
        from_date: str,
        to_date: str,
        securityId: str,
        instrument: str,
        exchangeSegment: str,
        symbol: Optional[str] = None,
        spot_price: Optional[float] = None,
    ) -> Any:
        """Expired option data for backtest (e.g. Dhan)."""
        raise NotImplementedError

    def get_nse_optionchain_historical(
        self,
        symbol: str,
        from_date: Any,
        expiry_date: Any,
        instrumentType: str,
        spot_price: float,
        option_type: str,
        strikes: List[Any],
    ) -> Optional[dict]:
        """NSE historical option chain. Optional for non-NSE providers."""
        return None
