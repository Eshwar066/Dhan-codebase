from datetime import datetime, date

from .base import BaseAdapter
from core.models.strategy_context import StrategyContext


class NSEAdapter(BaseAdapter):

    def get_expiries(self, ctx: StrategyContext):
        ts = ctx.timestamp
        years = [ts.year]
        if ts.month > 6:
            years.append(ts.year + 1)

        raw_expiries = []
        instrument = ctx.instrument or "OPTIDX"
        for year in years:
            raw_expiries.extend(
                self.data.get_nse_expiries(
                    symbol=ctx.symbol,
                    year=year,
                    instrument=instrument,
                )
            )

        expiries = []
        for exp in raw_expiries:
            if isinstance(exp, date):
                expiries.append(exp)
            elif isinstance(exp, datetime):
                expiries.append(exp.date())
            elif isinstance(exp, str):
                expiries.append(datetime.strptime(exp, "%Y-%m-%d").date())
            else:
                raise ValueError(f"Unsupported expiry type: {type(exp)}")

        expiries = sorted(set(expiries))
        ctx.expiry_list = expiries
        return expiries

    def get_option_chain(self, ctx: StrategyContext, params: dict):
        return "Needs to implemented"

    def get_historical_option_chain(self, ctx: StrategyContext, params: dict):
        ts = ctx.timestamp
        from_date = ts.date() if hasattr(ts, "date") else ts
        expiry_date = params.get("expiry_code")
        return self.data.get_nse_optionchain_historical(
            symbol=ctx.symbol,
            from_date=from_date,
            instrumentType=params["instrument"],
            expiry_date=expiry_date,
            spot_price=ctx.spot_price,
            option_type=params["option_type"],
            strikes=params["strike"],
        )
