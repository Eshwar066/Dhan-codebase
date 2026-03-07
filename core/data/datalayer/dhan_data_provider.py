"""
Dhan implementation of the data layer.
Delegates to DhanSource for all market data (candles, LTP, option chain, expiries).
No order placement — that belongs to the broker layer.
"""

from typing import Any, List, Optional
import pandas as pd

from .base import IDataProvider


class DhanDataProvider(IDataProvider):
    """Data layer for Dhan: candles, option chain, expiries. No orders."""

    def __init__(self, dhan_source):
        """
        Args:
            dhan_source: DhanSource instance (or any object exposing get_* data methods).
        """
        self._source = dhan_source

    def get_intraday(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        timeframe: str,
        exchange: str,
        sector: str,
    ) -> Optional[pd.DataFrame]:
        return self._source.get_intraday(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            timeframe=timeframe,
            exchange=exchange,
            sector=sector,
        )

    # not providing exact data
    def get_Futures_historical_intraday_data(
        self,
        securityId: str,
        exchangeSegment: str,
        instrument: str,
        interval: str,
        oi: bool,
        fromDate: str,
        toDate: str,
    ) -> Optional[pd.DataFrame]:
        df= self._source.get_Futures_historical_intraday_data(
            security_id=securityId,
            exchange_segment=exchangeSegment,
            instrument=instrument,
            interval=interval,
            oi=oi,
            from_date=fromDate,
            to_date=toDate,
        )
        
        return df

    def get_latest_candles(
        self, symbols: List[str], debug: str = "NO"
    ) -> Optional[dict]:
        return self._source.get_latest_candles(symbols, debug)

    def get_live_expiry(self, symbol: str, exchange: str) -> Any:
        return self._source.get_live_expiry(symbol=symbol, exchange=exchange)

    def get_nse_expiries(
        self, symbol: str, year: int, instrument: str = "OPTIDX"
    ) -> List[Any]:
        return self._source.get_nse_expiries(
            symbol=symbol, year=year, instrument=instrument
        )

    def get_live_option_chain(
        self,
        symbol: str,
        exchange: str,
        expiry_index: int,
        strikes_around_atm: int,
    ) -> Optional[dict]:
        return self._source.get_live_option_chain(
            symbol=symbol,
            exchange=exchange,
            expiry_index=expiry_index,
            strikes_around_atm=strikes_around_atm,
        )

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
    ) -> Any:
        return self._source.get_expired_optionchain(
            exchange=exchange,
            interval=interval,
            expiry_flag=expiry_flag,
            expiry_code=expiry_code,
            strike=strike,
            option_type=option_type,
            from_date=from_date,
            to_date=to_date,
            securityId=securityId,
            instrument=instrument,
            exchangeSegment=exchangeSegment,
        )

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
        return self._source.get_nse_optionchain_historical(
            symbol=symbol,
            from_date=from_date,
            expiry_date=expiry_date,
            instrumentType=instrumentType,
            spot_price=spot_price,
            option_type=option_type,
            strikes=strikes,
        )

    # ---------- Dhan v2 Market Quote API ----------
    def get_ltp_v2(self, instruments: dict) -> Any:
        """LTP via v2 /marketfeed/ltp. instruments: { 'NSE_EQ': [id], 'NSE_FNO': [id], ... }."""
        return self._source.get_ltp_v2(instruments)

    def get_ohlc_v2(self, instruments: dict) -> Any:
        """OHLC + LTP via v2 /marketfeed/ohlc."""
        return self._source.get_ohlc_v2(instruments)

    def get_quote_v2(self, instruments: dict) -> Any:
        """Full quote via v2 /marketfeed/quote (depth, OI, volume)."""
        return self._source.get_quote_v2(instruments)
