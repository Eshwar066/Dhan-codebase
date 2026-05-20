"""Shared types and schedule constants for OI Positional Buy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Any

import pandas as pd

ENTRY_SNAPSHOT_TIME = time(9, 30)
ENTRY_EVAL_TIME = time(10, 45)
EOD_REVIEW_TIME = time(15, 15)
REFERENCE_SNAPSHOT_TIMES = frozenset(
    {ENTRY_SNAPSHOT_TIME, ENTRY_EVAL_TIME, EOD_REVIEW_TIME}
)

PREMIUM_MIN = 170
PREMIUM_MAX = 220


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
