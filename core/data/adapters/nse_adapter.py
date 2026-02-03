from datetime import date
from .base import BaseAdapter


class NSEAdapter(BaseAdapter):

    def get_expiries(self, ctx):
        expiries = self.data.get_nse_expiries(
            symbol=ctx["symbol"],
            year=ctx["timestamp"].year,
            instrument=ctx["instrumentType"],
        )

        # invariant
        for e in expiries:
            if not isinstance(e, date):
                raise ValueError("NSE expiries must be datetime.date")

        return expiries

    def get_option_chain(self, ctx, params):
        expiry = ctx["selected_expiry"]

        # if not isinstance(expiry, date):
        #     raise ValueError("NSE selected_expiry must be date")

        return "Needs to implemented"

    def get_historical_option_chain(self, ctx, params):
        expiry = ctx["selected_expiry"]

        if not isinstance(expiry, date):
            raise ValueError("NSE selected_expiry must be date")

        return self.data.get_nse_optionchain_historical(
            symbol=ctx["symbol"],
            from_date=ctx["timestamp"].date(),
            to_date=ctx["timestamp"].date(),
            instrumentType=ctx["instrumentType"],
            expiry_date=expiry,
            spot_price=ctx["spot_price"],
            strike_step=ctx["strike_step"],
            strike_count=ctx["strike_count"],
            option_type=ctx["option_type"],
        )
