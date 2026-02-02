from core.strategies.runtime_spec import STRATEGY_RUNTIME_SPEC
from run.config import RUN_MODE, RunMode
import pdb
from datetime import datetime


class BaseEngine:
    def __init__(self, strategy, data, instrument_store):
        self.strategy = strategy
        self.data = data
        self.instrument_store = instrument_store

    def get_strategy_params(self):
        return STRATEGY_RUNTIME_SPEC[self.strategy.name][RUN_MODE]

    def build_context(self, candle):

        ctx = {
            "symbol": candle["symbol"],
            "timestamp": candle["timestamp"],
            "exchange": candle.get("exchange"),
            "instrument_store": self.instrument_store,
            "strike": 18000,
            "option_type": "PE",
            "instrumentType": "OPTIDX",
            "strike_step": 500,
            "strike_count": 3,
        }

        ts = candle["timestamp"]
        if not isinstance(ts, datetime):
            ts = datetime.fromisoformat(str(ts))
        ctx["timestamp"] = ts

        spec = self.get_strategy_params()

        if "option_chain" in spec.get("data", {}):
            params = spec["data"]["option_chain"]
            # Stage 1: expiry selection
            # ctx["expiry_list"] = self.data.get_live_expiry(
            #     symbol=ctx["symbol"],
            #     exchange=ctx["exchange"],
            # )
            ctx["expiry_list"] = self.data.get_nse_expiries(
                symbol=ctx["symbol"],
                year=ctx["timestamp"].year,
                instrument="FUTIDX",
            )
            result = self.strategy.on_candle(candle, ctx)
            if RUN_MODE == RunMode.LIVE:

                if result and result.get("selected_expiry"):
                    ctx["selected_expiry"] = result["selected_expiry"]

                    ctx["option_chain"] = self.data.get_live_option_chain(
                        symbol=ctx["symbol"],
                        exchange=ctx["exchange"],
                        expiry_index=result["selected_expiry"],
                        strikes_around_atm=params.get("strikes", 10),
                    )
                    intent = self.strategy.on_candle(candle, ctx)
                    # pdb.set_trace()

            else:

                ctx["option_chain"] = self.data.get_nse_optionchain_historical(
                    symbol=ctx["symbol"],
                    from_date=ctx["timestamp"].date(),
                    # to_date=result["selected_expiry"],
                    instrumentType=ctx["instrumentType"],
                    expiry_date=result["selected_expiry"],
                    # strike=ctx["strike"],
                    spot_price=candle["close"],
                    strike_step=ctx["strike_step"],
                    strike_count=ctx["strike_count"],
                    option_type=ctx["option_type"],
                    # year=result["selected_expiry"].year,
                )
                intent = self.strategy.on_candle(candle, ctx)

        return ctx, intent
