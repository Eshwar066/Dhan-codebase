"""
Kotak Neo data provider (quotes / scrip). No historical candles on NeoAPI.
Live bars come from KotakWebSocketFeed + CandleAggregator.
"""

from __future__ import annotations

from typing import Any, List, Optional

import pandas as pd

from .base import IDataProvider


class KotakDataProvider(IDataProvider):
    """Data layer for Kotak Neo. Orders belong to the broker layer."""

    def __init__(self, kotak_source):
        self._source = kotak_source

    def get_intraday(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        timeframe: str,
        exchange: str = None,
        sector: str = None,
    ) -> Optional[pd.DataFrame]:
        # Neo wrapper has no historical OHLC API during dual-broker phase.
        return None

    def get_latest_candles(
        self, symbols: List[str], debug: str = "NO"
    ) -> Optional[dict]:
        return None

    def get_live_expiry(self, symbol: str, exchange: str = None) -> Any:
        return None

    def get_live_option_chain(
        self,
        symbol: str,
        exchange: str,
        expiry_index: int,
        strikes_around_atm: int,
        expiry_flag: str,
    ) -> Optional[dict]:
        return None

    def quotes(self, instrument_tokens=None, quote_type=None) -> Any:
        return self._source.quotes(
            instrument_tokens=instrument_tokens, quote_type=quote_type
        )

    def scrip_master(self, exchange_segment: Optional[str] = None) -> Any:
        return self._source.scrip_master(exchange_segment=exchange_segment)
