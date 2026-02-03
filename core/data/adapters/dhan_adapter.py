from .base import BaseAdapter
import pdb
from datetime import date


class DhanAdapter(BaseAdapter):

    def get_expiries(self, ctx):
        expiries = self.data.get_live_expiry(
            symbol=ctx["symbol"],
            exchange=ctx["exchange"],
        )

        # invariant
        if not all(isinstance(e, int) for e in expiries):
            raise ValueError("DHAN expiries must be expiry index integers")

        return expiries

    def get_option_chain(self, ctx, params):
        expiry_index = ctx["selected_expiry"]

        if not isinstance(expiry_index, int):
            raise ValueError("DHAN selected_expiry must be expiry index")

        return self.data.get_live_option_chain(
            symbol=ctx["symbol"],
            exchange=ctx["exchange"],
            expiry_index=expiry_index,
            strikes_around_atm=params.get("strikes", 10),
        )

    def get_historical_option_chain(self, ctx, params):
        """
        Fetch cross-sectional option chain snapshot
        at a single timestamp using DHAN expired option API
        """

        expiry_index = ctx["selected_expiry"]

        if not isinstance(expiry_index, int):
            raise ValueError("DHAN selected_expiry must be expiry index")

        # DHAN strike expansion logic (ATM+N)
        strike_count = ctx.get("strike_count", 0)

        if strike_count == 0:
            strike = "ATM"
        else:
            strike = f"ATM+{strike_count}"

        pdb.set_trace()
        return self.data.get_expired_optionchain(
            # tradingsymbol=ctx["symbol"],
            exchange=params["exchange"],
            interval=params["interval"],  # 60 min
            expiry_flag=params["expiry_flag"],  # Monthly
            expiry_code=expiry_index,
            strike=strike,  # ATM+N → multiple strikes
            option_type=params["option_type"],  # CE / PE
            from_date=ctx["timestamp"].date(),
            to_date=ctx["timestamp"].date(),
        )
