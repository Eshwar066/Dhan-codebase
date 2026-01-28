from core.strategies.runtime_spec import STRATEGY_RUNTIME_SPEC
from run.config import RUN_MODE


class BaseEngine:
    def __init__(self, strategy, data):
        self.strategy = strategy
        self.data = data

    def get_strategy_params(self):
        return STRATEGY_RUNTIME_SPEC[self.strategy.name][RUN_MODE]

    def build_context(self, candle):
        ctx = {
            "symbol": candle["symbol"],
            "timestamp": candle["timestamp"],
        }

        spec = self.get_strategy_params()

        # ---------- OPTION CHAIN ----------
        if "option_chain" in spec.get("data", {}):
            params = spec["data"]["option_chain"]

            expiry = self.strategy.get_expiry(candle["timestamp"])

            ctx["option_chain"] = self.data.get_expired_option_chain(
                symbol=ctx["symbol"],
                expiry=expiry,
                params=params,
            )

        # ---------- FUTURE EXTENSIONS ----------
        if "vix" in spec.get("data", {}):
            ctx["vix"] = self.data.get_vix()

        if "oi" in spec.get("data", {}):
            ctx["oi"] = self.data.get_open_interest(ctx["symbol"])

        return ctx
