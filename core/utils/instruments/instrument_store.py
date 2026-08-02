"""
Instrument store facade: pick Dhan, Delta, or Kotak implementation by broker.
Import Instrument and InstrumentStore from here; broker-specific logic is in dhan/delta/kotak.
"""

from pathlib import Path
from typing import Any, Optional

from .base import Instrument
from .dhan import DhanInstrumentStore
from .delta import DeltaInstrumentStore
from .kotak import KotakInstrumentStore


def InstrumentStore(
    csv_path: Optional[Path] = None,
    broker: Optional[str] = None,
    base_url: Optional[str] = None,
    kotak_source: Any = None,
):
    """
    Factory: returns broker-specific instrument store.

    - InstrumentStore(path)  or  InstrumentStore(csv_path=path)  → Dhan
    - InstrumentStore(broker="DHAN", csv_path=path)  → Dhan
    - InstrumentStore(broker="DELTA", csv_path=path, base_url=...)  → Delta
    - InstrumentStore(broker="KOTAK", csv_path=path, kotak_source=...)  → Kotak
      (reuses NSE master CSV; Neo feed token mapping)
    """
    path = Path(csv_path) if csv_path is not None else None
    effective_broker = (broker or "DHAN").upper()
    if effective_broker == "DELTA":
        return DeltaInstrumentStore(base_url=base_url, cache_path=path)
    if effective_broker == "KOTAK":
        if path is None:
            raise ValueError("Kotak InstrumentStore requires csv_path (NSE master CSV)")
        return KotakInstrumentStore(path, kotak_source=kotak_source)
    if effective_broker == "DHAN":
        if path is None:
            raise ValueError("Dhan InstrumentStore requires csv_path")
        return DhanInstrumentStore(path)
    raise ValueError(f"Unknown broker for InstrumentStore: {broker}")


__all__ = [
    "Instrument",
    "InstrumentStore",
    "DhanInstrumentStore",
    "DeltaInstrumentStore",
    "KotakInstrumentStore",
]
