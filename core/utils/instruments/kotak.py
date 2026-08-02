"""
Kotak Neo instrument store.

Dual-broker period: reuses the NSE instrument master CSV (same schema as Dhan)
so India F&O / equity resolution and ``required_context.instrument_store`` work
unchanged. Feed subscription payloads are mapped to Neo token format.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

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

    def __init__(self, csv_path: Path, kotak_source: Any = None):
        super().__init__(csv_path)
        self._kotak_source = kotak_source

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
