"""Manual LEAPS emergency tools — not loaded by the live engine.

Run only with the live engine stopped, from the repo root:

  .venv/bin/python -m core.strategies.Leaps.emergency.force_leaps_cycle
  .venv/bin/python -m core.strategies.Leaps.emergency.retry_leaps_main

These modules are never imported by registry / LiveEngine.
"""

__all__: list[str] = []
