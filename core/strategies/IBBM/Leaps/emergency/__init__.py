"""Manual LEAPS emergency tools — not loaded by the live engine.

Run only with the live engine stopped, from the repo root:

  python -m core.strategies.IBBM.Leaps.emergency.force_leaps_cycle
  python -m core.strategies.IBBM.Leaps.emergency.force_leaps_cycle --entry-only
  python -m core.strategies.IBBM.Leaps.emergency.retry_leaps_main
  python -m core.strategies.IBBM.Leaps.emergency.roll_leaps_hedge --dry-run
  python -m core.strategies.IBBM.Leaps.emergency.roll_leaps_hedge

Hedge roll (after market open): buy next-month hedge first, wait fill, then exit
old monthly hedge (margin-safe order).

Dual-structure entry (mini + quarterly): force_leaps_cycle places one bundle per
structure_id when both legs are enabled in strategy.yaml.

These modules are never imported by registry / LiveEngine.
"""

__all__: list[str] = []
