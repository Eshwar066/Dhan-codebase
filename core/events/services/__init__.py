"""Event-path services — orchestration extracted from LiveEngine for testability."""

from __future__ import annotations

from core.events.services.execution import ExecutionService
from core.events.services.exit_rollover import ExitRolloverService
from core.events.services.feed_supervisor import FeedSupervisorService
from core.events.services.scheduled_eval import ScheduledEvalService
from core.events.services.strategy_eval import StrategyEvalService


def attach_event_services(engine: object) -> dict:
    """
    Attach service instances on ``engine`` (idempotent).

    Called from ``wire_event_bus`` so handlers and LiveEngine share one set of services.
    """
    services = {
        "exit_rollover_service": ExitRolloverService(engine),
        "strategy_eval_service": StrategyEvalService(engine),
        "execution_service": ExecutionService(engine),
        "scheduled_eval_service": ScheduledEvalService(engine),
        "feed_supervisor_service": FeedSupervisorService(engine),
    }
    for name, svc in services.items():
        setattr(engine, name, svc)
    return services


__all__ = [
    "ExecutionService",
    "ExitRolloverService",
    "FeedSupervisorService",
    "ScheduledEvalService",
    "StrategyEvalService",
    "attach_event_services",
]
