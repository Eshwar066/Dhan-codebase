"""Shared types and schedule constants for OI Positional Buy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Any, Dict, Tuple

import pandas as pd

ENTRY_SNAPSHOT_TIME = time(9, 30)
ENTRY_EVAL_TIME = time(10, 45)
EOD_REVIEW_TIME = time(15, 15)
REFERENCE_SNAPSHOT_TIMES = frozenset(
    {ENTRY_SNAPSHOT_TIME, ENTRY_EVAL_TIME, EOD_REVIEW_TIME}
)

# Legacy single-symbol band (kept for back-compat; per-symbol values in SYMBOL_CONFIG below).
PREMIUM_MIN = 170
PREMIUM_MAX = 220

# strategy_meta payload key (persisted on MAIN ENTRY for restart)
OI_POS_META_KEY = "oi_positional_buy"


@dataclass(frozen=True)
class SymbolConfig:
    """Per-underlying tuning for OI Positional Buy.

    - ``security_id`` / ``exchange_segment``: DHAN UnderlyingScrip + segment for the
      option-chain API. The live DHAN library re-resolves these from the underlying
      name (see ``Dhan_Tradehull.get_option_chain`` index_exchange map), so these are
      mainly used by the backtest / historical chain path.
    - ``chain_exchange``: exchange label passed to ``ctx.exchange`` for chain lookups
      (NSE for NIFTY/BANKNIFTY, BSE for SENSEX/BANKEX).
    - ``strike_step`` / ``strike_count``: OTM ladder width for ``ExpiryResolver.get_otm_strikes``.
    - ``premium_band``: (min, max) acceptable OTM premium ``₹`` for the entry filter.
    """

    security_id: str
    exchange_segment: str
    chain_exchange: str
    strike_step: int
    strike_count: int
    premium_band: Tuple[int, int]


# Underlying name (matches ``candle["symbol"]``) → tuning.
SYMBOL_CONFIG: Dict[str, SymbolConfig] = {
    "NIFTY": SymbolConfig(
        security_id="13",
        exchange_segment="NSE_FNO",
        chain_exchange="NSE",
        strike_step=100,
        strike_count=30,
        premium_band=(170, 220),
    ),
    "BANKNIFTY": SymbolConfig(
        security_id="25",
        exchange_segment="NSE_FNO",
        chain_exchange="NSE",
        strike_step=100,
        strike_count=30,
        premium_band=(200, 500),
    ),
    "SENSEX": SymbolConfig(
        security_id="51",
        exchange_segment="BSE_FNO",
        chain_exchange="BSE",
        strike_step=100,
        strike_count=30,
        premium_band=(200, 500),
    ),
}

DEFAULT_SYMBOL_CONFIG = SYMBOL_CONFIG["NIFTY"]


def get_symbol_config(symbol: Any) -> SymbolConfig:
    """Lookup per-symbol config; fall back to NIFTY defaults for unknown symbols."""
    if symbol is None:
        return DEFAULT_SYMBOL_CONFIG
    key = str(symbol).strip().upper()
    return SYMBOL_CONFIG.get(key, DEFAULT_SYMBOL_CONFIG)


@dataclass(frozen=True)
class OISnapshot:
    option_type: str
    strike: int
    premium: float
    oi: float
    ts: pd.Timestamp


@dataclass
class PositionMeta:
    symbol: str
    option_type: str
    strike: int
    benchmark_premium: float
    benchmark_oi: float
    entry_premium: float
    entry_date: date
    structure_id: str


@dataclass(frozen=True)
class PendingEntry:
    entry_intent: Any


@dataclass
class PendingReferenceSnapshot:
    symbol: str
    trade_date: date
    target: time
    attempts: int = 0
    last_error: str = ""
    first_attempt_unix: float = 0.0
    last_attempt_unix: float = 0.0
