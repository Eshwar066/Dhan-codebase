from datetime import datetime
from core.data.data_router import DataRouter
from core.strategies.runtime_spec import STRATEGY_RUNTIME_SPEC
from core.data.option_chain_service import OptionChainService
from run.config import RUN_MODE, RunMode
import pdb


class BaseEngine:
    def __init__(self, strategy, data, instrument_store):
        self.strategy = strategy
        self.data = data
        self.instrument_store = instrument_store
        self.option_chain_service = OptionChainService
        self.data_router = DataRouter(data)

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
            "instrument_store": self.instrument_store,
            # 🔑 Inject capability, not data
            "option_chain_service": self.option_chain_service,
        }
        ctx["option_chain_service"] = OptionChainService(self.data_router)
        # ONE call only
        intent = self.strategy.on_candle(candle, ctx)
        pdb.set_trace()
        return ctx, intent
