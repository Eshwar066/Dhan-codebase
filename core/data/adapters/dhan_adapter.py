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

        # Required inputs
        spot_price = ctx["spot_price"]  # e.g. 19735
        target_strike = params["strike"]  # e.g. 19850
        strike_step = 50

        # Calculate ATM strike
        atm_strike = round(spot_price / strike_step) * strike_step

        # Calculate N
        diff = int(target_strike) - int(atm_strike)
        n = int(diff / strike_step)

        # Build strike string

        MAX_N = 10

        if n == 0:
            strike = "ATM"
        elif 0 < n <= MAX_N:
            strike = f"ATM+{n}"
        elif -MAX_N <= n < 0:
            strike = f"ATM{n}"  # n is negative → ATM-1, ATM-5
        elif n > MAX_N:
            strike = f"ATM+{MAX_N}"
        else:  # n < -MAX_N
            strike = f"ATM-{MAX_N}"
            # n already negative → ATM-1, ATM-2

        return self.data.get_expired_optionchain(
            exchange=params["exchange"],
            securityId=params["securityId"],
            interval=params["interval"],
            expiry_flag=params["expiry_flag"],
            expiry_code=expiry_index,
            strike=strike,  # <-- computed strike
            option_type=params["option_type"],
            from_date=ctx["timestamp"].strftime("%Y-%m-%d"),
            to_date=ctx["timestamp"].strftime("%Y-%m-%d"),
            instrument=params["instrument"],
            exchangeSegment=params["exchangeSegment"],
        )
