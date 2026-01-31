from core.strategies.runtime_spec import STRATEGY_RUNTIME_SPEC
from run.config import RUN_MODE, RunMode
import pdb
from datetime import datetime


class BaseEngine:
    def __init__(self, strategy, data):
        self.strategy = strategy
        self.data = data

    def get_strategy_params(self):
        return STRATEGY_RUNTIME_SPEC[self.strategy.name][RUN_MODE]

    # def build_context(self, candle):
    #     ctx = {
    #         "symbol": candle["symbol"],
    #         "timestamp": candle["timestamp"],
    #         "exchange": candle.get("exchange"),
    #     }

    #     ts = candle["timestamp"]
    #     if not isinstance(ts, datetime):
    #         ts = datetime.fromisoformat(str(ts))
    #     ctx["timestamp"] = ts

    #     spec = self.get_strategy_params()

    #     # ---------- OPTION CHAIN ----------
    #     if "option_chain" in spec.get("data", {}):
    #         params = spec["data"]["option_chain"]

    #         if RUN_MODE == RunMode.LIVE:

    #             # 1) Get expiry list
    # ctx["expiry_list"] = self.data.get_live_expiry(
    #     symbol=ctx["symbol"],
    #     exchange=ctx["exchange"],
    # )
    #             ctx["expiry_list"] = self.data.get_nse_expiries(
    #                 symbol=ctx["symbol"],
    #                 year=ctx["timestamp"].year,
    #                 instrument="FUTIDX",
    #             )

    #             # 2) Strategy selects expiry
    #             result = self.strategy.on_candle(candle, ctx)
    #             if not result:
    #                 return ctx

    #             selected_expiry_date = result.get("selected_expiry")

    #             # 3) Save it
    #             ctx["selected_expiry"] = selected_expiry_date

    #             # 4) Fetch option chain
    #             ctx["option_chain"] = self.data.get_live_option_chain(
    #                 symbol=ctx["symbol"],
    #                 exchange=ctx["exchange"],
    #                 expiry_index=selected_expiry_date,
    #                 strikes_around_atm=params.get("strikes", 10),
    #             )
    #             # pdb.set_trace()
    #             # 5) Again redirect to strategy
    #             result = self.strategy.on_candle(candle, ctx)
    #             if not result:
    #                 return ctx

    #         else:
    #             # expiry = self.strategy.get_expiry(candle["timestamp"])
    #             ctx["option_chain"] = self.data.get_expired_option_chain(
    #                 symbol=ctx["symbol"],
    #                 expiry=expiry,
    #                 params=params,
    #             )

    #     return ctx
    def build_context(self, candle):

        ctx = {
            "symbol": candle["symbol"],
            "timestamp": candle["timestamp"],
            "exchange": candle.get("exchange"),
        }

        ts = candle["timestamp"]
        if not isinstance(ts, datetime):
            ts = datetime.fromisoformat(str(ts))
        ctx["timestamp"] = ts

        spec = self.get_strategy_params()

        if "option_chain" in spec.get("data", {}):
            params = spec["data"]["option_chain"]

            if RUN_MODE == RunMode.LIVE:

                # ctx["expiry_list"] = self.data.get_live_expiry(
                #     symbol=ctx["symbol"],
                #     exchange=ctx["exchange"],
                # )
                ctx["expiry_list"] = self.data.get_nse_expiries(
                    symbol=ctx["symbol"],
                    year=ctx["timestamp"].year,
                    instrument="FUTIDX",
                )

                # Stage 1: expiry selection
                result = self.strategy.on_candle(candle, ctx)

                if result and result.get("selected_expiry"):
                    ctx["selected_expiry"] = result["selected_expiry"]

                    ctx["option_chain"] = self.data.get_live_option_chain(
                        symbol=ctx["symbol"],
                        exchange=ctx["exchange"],
                        expiry_index=result["selected_expiry"],
                        strikes_around_atm=params.get("strikes", 10),
                    )
                    result = self.strategy.on_candle(candle, ctx)
                    # pdb.set_trace()

            else:
                ctx["option_chain"] = self.data.get_expired_option_chain(
                    symbol=ctx["symbol"],
                    expiry=expiry,
                    params=params,
                )

        return ctx
