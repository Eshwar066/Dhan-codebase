from datetime import datetime
from core.data.data_router import DataRouter
from core.strategies.runtime_spec import STRATEGY_RUNTIME_SPEC
from core.data.option_chain_service import OptionChainService
from run.config import RUN_MODE, RunMode
import pdb


class BaseEngine:

    def __init__(self, strategy, data, instrument_store, position_manager):
        self.strategy = strategy
        self.data = data
        self.instrument_store = instrument_store
        self.position_manager = position_manager
        self.data_router = DataRouter(data)
        self.option_chain_service = OptionChainService(self.data_router)

    def get_strategy_params(self):
        return STRATEGY_RUNTIME_SPEC[self.strategy.name][RUN_MODE]

    # core/engine/base_engine.py

    def build_context(self, candle):
        ts = candle["timestamp"]
        if not isinstance(ts, datetime):
            ts = datetime.fromisoformat(str(ts))

        ctx = {
            "symbol": candle["symbol"],
            "exchange": candle.get("exchange"),
            "timestamp": ts,
            "spot_price": candle["close"],
            # ✅ shared services
            "instrument_store": self.instrument_store,
            "position_store": self.position_manager,
            "option_chain_service": self.option_chain_service,
        }

        # ONE call only
        intent = self.strategy.on_candle(candle, ctx)
        return ctx, intent
