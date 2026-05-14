"""
Convenience helpers for instrument loading by path (Dhan CSV vs Delta API).
Broker-specific store logic is in dhan.py and delta.py.
"""

from pathlib import Path
from typing import Optional

from .delta import DeltaInstrumentProvider, fetch_delta_products
from .dhan import DhanInstrumentProvider


def get_provider_for_path(
    csv_path: Path,
    broker: Optional[str] = None,
    delta_fallback: bool = True,
    save_delta_to_csv: bool = False,
    delta_base_url: Optional[str] = None,
):
    """
    Return provider based on broker; path is used for Dhan CSV or optional Delta save.

    - broker="DELTA" → always Delta provider (even if Dhan CSV exists). If save_delta_to_csv=True, fetch and save raw Delta products to csv_path.
    - broker="DHAN" or None → Dhan provider if csv_path exists; else (if delta_fallback) Delta provider.
    """
    path = Path(csv_path).resolve()
    effective_broker = (broker or "DHAN").upper()

    if effective_broker == "DELTA":
        delta = DeltaInstrumentProvider(delta_base_url)
        if save_delta_to_csv and path:
            raw = delta.fetch_products()
            if not raw.empty:
                path.parent.mkdir(parents=True, exist_ok=True)
                raw.to_csv(path, index=False, float_format="%.2f")
        return delta

    if path.exists():
        return DhanInstrumentProvider(path)
    if not delta_fallback:
        raise FileNotFoundError(f"Instrument file not found: {path}")
    delta = DeltaInstrumentProvider(delta_base_url)
    if save_delta_to_csv:
        raw = delta.fetch_products()
        if not raw.empty:
            path.parent.mkdir(parents=True, exist_ok=True)
            raw.to_csv(path, index=False, float_format="%.2f")
    return delta
