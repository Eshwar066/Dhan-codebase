"""
Data from Dhan API (single source of truth).
Use DhanDataProvider for historical, intraday, instruments.
"""

from core.api.dhan_data import DhanDataProvider, get_instrument_file

__all__ = ["DhanDataProvider", "get_instrument_file"]
