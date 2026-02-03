from abc import ABC, abstractmethod


class BaseAdapter(ABC):
    def __init__(self, data_service):
        self.data = data_service

    @abstractmethod
    def get_expiries(self, ctx):
        pass

    @abstractmethod
    def get_option_chain(self, ctx, params):
        pass

    @abstractmethod
    def get_historical_option_chain(self, ctx, params):
        pass
