"""
Instrument store facade: pick Dhan or Delta implementation by broker.
Import Instrument and InstrumentStore from here; broker-specific logic is in dhan.py and delta.py.
"""

from pathlib import Path
from typing import Optional

from .base import Instrument
from .dhan import DhanInstrumentStore
from .delta import DeltaInstrumentStore


def InstrumentStore(
    csv_path: Optional[Path] = None,
    broker: Optional[str] = None,
    base_url: Optional[str] = None,
):
    """
    Factory: returns broker-specific instrument store.

    - InstrumentStore(path)  or  InstrumentStore(csv_path=path)  → Dhan
    - InstrumentStore(broker="DHAN", csv_path=path)  → Dhan
    - InstrumentStore(broker="DELTA", csv_path=path, base_url=...)  → Delta; path = cache file in Dependencies (load/save)
    """
    path = Path(csv_path) if csv_path is not None else None
    effective_broker = (broker or "DHAN").upper()
    if effective_broker == "DELTA":
        return DeltaInstrumentStore(base_url=base_url, cache_path=path)
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
]
