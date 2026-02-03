from run.config import RUN_MODE, RunMode


class OptionChainService:
    def __init__(self, data_router):
        self.data_router = data_router

    def get_chain(self, *, api, ctx, params):
        """
        api   : "NSE" or "DHAN"
        ctx   : engine context
        params: option chain params
        """

        # 🔑 DataRouter expects api inside params
        params["api"] = api

        adapter = self.data_router.from_candle(params)

        if RUN_MODE == RunMode.LIVE or RUN_MODE == RunMode.PAPER:
            if api == "DHAN":
                return adapter.get_option_chain(ctx, params)
            else:
                return adapter.get_option_chain(ctx, params)
        else:
            if api == "DHAN":
                return adapter.get_historical_option_chain(ctx, params)
            else:
                return adapter.get_historical_option_chain(ctx, params)
