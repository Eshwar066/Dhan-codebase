"""
Broker package: order placement and position/exit.
- base: IBrokerApi, BaseBroker (abstract contracts)
- internal: per-broker implementations (dhan, delta, simulated)

Use: from core.broker import DhanBroker, DhanBrokerApi, DeltaBroker, DeltaBrokerApi,
KotakBroker, KotakBrokerApi, SimulatedBroker, BaseBroker, IBrokerApi
"""

from core.broker.base import BaseBroker, IBrokerApi
from core.broker.internal import (
    DhanBroker,
    DhanBrokerApi,
    DeltaBroker,
    DeltaBrokerApi,
    KotakBroker,
    KotakBrokerApi,
    SimulatedBroker,
)

__all__ = [
    "BaseBroker",
    "IBrokerApi",
    "DhanBroker",
    "DhanBrokerApi",
    "DeltaBroker",
    "DeltaBrokerApi",
    "KotakBroker",
    "KotakBrokerApi",
    "SimulatedBroker",
]
