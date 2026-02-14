from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.models.strategy_context import StrategyContext


class BaseAdapter(ABC):
    def __init__(self, data_service):
        self.data = data_service

    @abstractmethod
    def get_expiries(self, ctx: "StrategyContext"):
        pass

    @abstractmethod
    def get_option_chain(self, ctx: "StrategyContext", params: dict):
        pass

    @abstractmethod
    def get_historical_option_chain(self, ctx: "StrategyContext", params: dict):
        pass
