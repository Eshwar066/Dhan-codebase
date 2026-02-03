from core.data.adapters.nse_adapter import NSEAdapter
from core.data.adapters.dhan_adapter import DhanAdapter


class DataRouter:
    def __init__(self, data_service):
        self.adapters = {
            "NSE": NSEAdapter(data_service),
            "DHAN": DhanAdapter(data_service),
        }

    def from_candle(self, params):
        if "api" not in params:
            raise ValueError("params must define 'api' (NSE / DHAN)")

        api = params["api"].upper()

        if api not in self.adapters:
            raise ValueError(f"Unsupported api source: {api}")

        return self.adapters[api]
