"""
Kotak Neo instrument store.

Dual-broker period: reuses the NSE instrument master CSV (same schema as Dhan)
so India F&O / equity resolution and ``required_context.instrument_store`` work
unchanged. Feed subscription payloads are mapped to Neo token format.
"""

from __future__ import annotations

import logging
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from core.data.option_chain.kotak_chain import (
    list_option_expiries,
    option_rows_for_expiry,
)
from core.utils.instruments.dhan import DhanInstrumentStore

logger = logging.getLogger(__name__)

# Dhan WS segment → Neo exchange_segment
_DHAN_TO_NEO_SEGMENT = {
    "IDX_I": "nse_cm",
    "NSE_EQ": "nse_cm",
    "NSE_FNO": "nse_fo",
    "NSE_CURRENCY": "cde_fo",
    "BSE_EQ": "bse_cm",
    "BSE_FNO": "bse_fo",
    "BSE_CURRENCY": "cde_fo",
    "MCX_COMM": "mcx_fo",
}


class KotakInstrumentStore(DhanInstrumentStore):
    """Instrument lookups via NSE master CSV; Neo-shaped feed instruments."""

    # Kotak CSV column name -> Dhan SEM_* column name
    _KOTAK_TO_DHAN_COLS = {
        "pTrdSymbol": "SEM_TRADING_SYMBOL",
        "pSymbolName": "SEM_CUSTOM_SYMBOL",
        "dStrikePrice;": "SEM_STRIKE_PRICE",
        "pOptionType": "SEM_OPTION_TYPE",
        "pAssetCode": "SEM_SMST_SECURITY_ID",
        "lLotSize": "SEM_LOT_UNITS",
        "lExpiryDate ": "SEM_EXPIRY_DATE",  # note trailing space in Kotak column
        "lExpiryDate": "SEM_EXPIRY_DATE",   # without trailing space (just in case)
        "pExchSeg": "SEM_EXM_EXCH_ID",
        "pInstType": "SEM_EXCH_INSTRUMENT_TYPE",
        "pExpiryDate": "SEM_EXPIRY_DATE",   # string format
        "pSymbol": "SEM_SYMBOL",
        "pSymbolName": "SEM_CUSTOM_SYMBOL",
        "pTrdSymbol": "SEM_TRADING_SYMBOL",
        "pOptionType": "SEM_OPTION_TYPE",
        "pAssetCode": "SEM_SMST_SECURITY_ID",
        "lLotSize": "SEM_LOT_UNITS",
        "lExpiryDate ": "SEM_EXPIRY_DATE",
        "pExchSeg": "SEM_EXM_EXCH_ID",
        "pInstType": "SEM_EXCH_INSTRUMENT_TYPE",
        "pExpiryDate": "SEM_EXPIRY_DATE",
        # Additional mappings for instrument name/type
        "pInstName": "SEM_INSTRUMENT_NAME",
        "pInstType": "SEM_EXCH_INSTRUMENT_TYPE",
    }

    def __init__(self, csv_path: Path, kotak_source: Any = None):
        # Load Kotak CSV and rename columns to Dhan format before parent init
        import pandas as pd
        df = pd.read_csv(csv_path, low_memory=False)
        df.columns = df.columns.str.strip()  # strip whitespace from column names
        # Rename Kotak columns to Dhan SEM_* format
        df = df.rename(columns={k: v for k, v in self._KOTAK_TO_DHAN_COLS.items() if k in df.columns})
        # Save the renamed CSV to a temp file for parent to load
        import tempfile
        tmp_path = Path(tempfile.mktemp(suffix=".csv"))
        df.to_csv(tmp_path, index=False, float_format="%.2f")
        super().__init__(tmp_path)
        self._kotak_source = kotak_source
        # Clean up temp file after parent loads
        try:
            tmp_path.unlink()
        except Exception:
            pass

    def get_feed_instruments(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """
        Resolve symbols to Neo subscribe payloads:
        {"instrument_token", "exchange_segment", "symbol", "isIndex"}.
        """
        dhan_instruments = super().get_feed_instruments(symbols)
        out: List[Dict[str, Any]] = []
        for row in dhan_instruments:
            seg = str(row.get("ExchangeSegment") or "").strip().upper()
            sid = str(row.get("SecurityId") or "").strip()
            sym = str(row.get("symbol") or "").strip().upper()
            if not sid:
                continue
            neo_seg = _DHAN_TO_NEO_SEGMENT.get(seg, "nse_cm")
            out.append(
                {
                    "instrument_token": sid,
                    "exchange_segment": neo_seg,
                    "symbol": sym,
                    "isIndex": seg == "IDX_I",
                    # Keep Dhan keys for debugging / dual-run comparison
                    "ExchangeSegment": seg,
                    "SecurityId": sid,
                }
            )
        return out

    def refresh_scrip_master(self, exchange_segment: Optional[str] = None) -> int:
        """Optional: pull Neo scrip master (logged; CSV remains source of truth in v1)."""
        if self._kotak_source is None:
            return 0
        try:
            rows = self._kotak_source.scrip_master(exchange_segment=exchange_segment)
            n = len(rows) if isinstance(rows, list) else 0
            logger.info(
                "KotakInstrumentStore scrip_master rows=%s segment=%s",
                n,
                exchange_segment,
            )
            return n
        except Exception as e:
            logger.warning("KotakInstrumentStore scrip_master failed: %s", e)
            return 0

    def list_option_expiries(
        self, symbol: str, *, monthly_only: bool = False
    ) -> List[date]:
        """Sorted option expiry dates for an underlying from the NSE master CSV."""
        return list_option_expiries(
            self.df, symbol, monthly_only=monthly_only
        )

    def list_options_for_expiry(
        self,
        symbol: str,
        expiry: date,
        *,
        monthly_only: bool = False,
    ) -> pd.DataFrame:
        """OPTIDX/OPTSTK rows for ``symbol`` on ``expiry`` (CE+PE)."""
        return option_rows_for_expiry(
            self.df, symbol, expiry, monthly_only=monthly_only
        )
