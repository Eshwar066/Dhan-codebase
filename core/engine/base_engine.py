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

        # ---------- OPTION CHAIN ----------
        if "option_chain" in spec.get("data", {}):
            params = spec["data"]["option_chain"]

            if RUN_MODE == RunMode.LIVE:

                # 1) Get expiry list
                ctx["expiry_list"] = self.data.get_nse_expiries(
                    symbol=ctx["symbol"],
                    year=ctx["timestamp"].year,
                    instrument="FUTIDX",
                )

                # 2) Strategy selects expiry
                result = self.strategy.on_candle(candle, ctx)
                if not result:
                    return

                selected_expiry_index = result.get("selected_expiry")

                # 3) Save it
                ctx["selected_expiry"] = selected_expiry_index

                # 4) Fetch option chain
                ctx["option_chain"] = self.data.get_live_option_chain(
                    symbol=ctx["symbol"],
                    exchange=ctx["exchange"],
                    expiry_index=selected_expiry_index,
                    strikes_around_atm=params.get("strikes", 10),
                )

            else:
                # expiry = self.strategy.get_expiry(candle["timestamp"])
                ctx["option_chain"] = self.data.get_expired_option_chain(
                    symbol=ctx["symbol"],
                    expiry=expiry,
                    params=params,
                )

        return ctx
