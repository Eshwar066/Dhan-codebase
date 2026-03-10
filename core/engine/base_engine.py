from datetime import datetime

from core.data.data_router import DataRouter
from core.data.option_chain_service import OptionChainService
from core.models.strategy_context import StrategyContext
from core.strategies.runtime_spec import STRATEGY_RUNTIME_SPEC
from run.config import RUN_MODE, RunMode


class BaseEngine:

    def __init__(
        self,
        strategy,
        data,
        instrument_store,
        position_manager,
        universe_service=None,
    ):
        self.strategy = strategy
        self.data = data
        self.instrument_store = instrument_store
        self.position_manager = position_manager
        self.universe_service = universe_service
        self.data_router = DataRouter(data)
        self.option_chain_service = OptionChainService(self.data_router)

    def get_strategy_params(self):
        return STRATEGY_RUNTIME_SPEC[self.strategy.name][RUN_MODE]

    def build_context(self, candle, recent_candles=None, intent_store=None):
        ts = candle["timestamp"]
        if not isinstance(ts, datetime):
            ts = datetime.fromisoformat(str(ts))

        ctx = StrategyContext(
            symbol=candle["symbol"],
            exchange=candle.get("exchange"),
            timestamp=ts,
            spot_price=float(candle["close"]),
            instrument_store=self.instrument_store,
            position_store=self.position_manager,
            option_chain_service=self.option_chain_service,
            universe_service=getattr(self, "universe_service", None),
            recent_candles=recent_candles,
            intent_store=intent_store,
        )

        intent = self.strategy.on_candle(candle, ctx)
        return ctx, intent
