from run.config import RUN_MODE, RunMode

from core.models.strategy_context import StrategyContext


class OptionChainService:
    def __init__(self, data_router):
        self.data_router = data_router

    def _resolve_api(self, api: str | None) -> str:
        resolve = getattr(self.data_router, "resolve_api", None)
        if callable(resolve):
            return resolve(api)
        return (api or "").upper()

    def get_expiries(self, api: str, ctx: StrategyContext, instrument: str):
        ctx.instrument = instrument
        params = {
            "api": self._resolve_api(api),
            "symbol": ctx.symbol,
            "instrument": ctx.instrument,
        }

        adapter = self.data_router.from_candle(params)

        if RUN_MODE in (RunMode.LIVE, RunMode.PAPER):
            return adapter.get_expiries(ctx)
        return adapter.get_expiries(ctx)

    def get_chain(self, *, api: str, ctx: StrategyContext, params: dict):
        """Fetch option chain; ``api`` is resolved via DataRouter.default_api when set."""
        params = dict(params or {})
        params["api"] = self._resolve_api(api)
        adapter = self.data_router.from_candle(params)

        if RUN_MODE == RunMode.LIVE or RUN_MODE == RunMode.PAPER:
            return adapter.get_option_chain(ctx, params)
        return adapter.get_historical_option_chain(ctx, params)
