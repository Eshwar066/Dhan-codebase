from run.config import RUN_MODE, RunMode

from core.models.strategy_context import StrategyContext


class OptionChainService:
    def __init__(self, data_router):
        self.data_router = data_router

    def get_expiries(self, api: str, ctx: StrategyContext, instrument: str):
        ctx.instrument = instrument
        params = {
            "api": api,
            "symbol": ctx.symbol,
            "instrument": ctx.instrument,
        }

        adapter = self.data_router.from_candle(params)

        if RUN_MODE in (RunMode.LIVE, RunMode.PAPER):
            return adapter.get_expiries(ctx)
        return adapter.get_expiries(ctx)

    def get_chain(self, *, api: str, ctx: StrategyContext, params: dict):
        """api: "NSE" or "DHAN"; ctx: StrategyContext; params: option chain params."""
        params["api"] = api
        adapter = self.data_router.from_candle(params)

        if RUN_MODE == RunMode.LIVE or RUN_MODE == RunMode.PAPER:
            return adapter.get_option_chain(ctx, params)
        return adapter.get_historical_option_chain(ctx, params)
