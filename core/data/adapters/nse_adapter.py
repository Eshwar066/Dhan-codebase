from datetime import datetime, date
from .base import BaseAdapter
import pdb


class NSEAdapter(BaseAdapter):

    def get_expiries(self, ctx):
        ts = ctx["timestamp"]
        years = [ts.year]

        if ts.month > 6:
            years.append(ts.year + 1)

        raw_expiries = []

        for year in years:
            raw_expiries.extend(
                self.data.get_nse_expiries(
                    symbol=ctx["symbol"],
                    year=year,
                    instrument=ctx["instrument"],
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

        # Optional but recommended: unique + sorted
        expiries = sorted(set(expiries))

        ctx["expiry_list"] = expiries
        return expiries

    def get_option_chain(self, ctx, params):
        expiry = ctx["selected_expiry"]

        # if not isinstance(expiry, date):
        #     raise ValueError("NSE selected_expiry must be date")

        return "Needs to implemented"

    def get_historical_option_chain(self, ctx, params):

        return self.data.get_nse_optionchain_historical(
            symbol=ctx["symbol"],
            from_date=ctx["timestamp"].date(),
            instrumentType=params["instrument"],
            expiry_date=params["expiry_code"],
            spot_price=ctx["spot_price"],
            option_type=params["option_type"],
            strikes=params["strike"],
        )
