"""
EDIS (e-disclosure) — required for selling delivery (CNC) equity from demat.

Not used for typical F&O / MIS-only algos. Implement when EQ delivery sell is in scope:
see DhanHQ v2 → EDIS section.

Raising NotImplementedError keeps accidental EQ delivery paths visible in logs/tests.
"""

from __future__ import annotations


def require_edis_for_delivery_sell() -> None:
    raise NotImplementedError(
        "EDIS flow is required for CNC delivery sells — see DhanHQ v2 EDIS documentation"
    )
