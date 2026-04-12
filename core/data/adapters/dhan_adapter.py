from .base import BaseAdapter

from core.models.strategy_context import StrategyContext
from core.utils.expiry_resolver import ExpiryResolver


class DhanAdapter(BaseAdapter):

    def get_expiries(self, ctx: StrategyContext):
        expiries = self.data.get_live_expiry(
            symbol=ctx.symbol,
            exchange=ctx.exchange or "",
        )
        if not expiries:
            return []
        return expiries

    def get_option_chain(self, ctx: StrategyContext, params: dict):
        expiry_index = ctx.get_selected_expiry()
        if expiry_index is None:
            expiry_index = 0
        if isinstance(expiry_index, (int, float)):
            expiry_index = int(expiry_index)
        else:
            expiry_index = 0

        return self.data.get_live_option_chain(
            symbol=ctx.symbol,
            exchange=ctx.exchange or "",
            expiry_index=expiry_index,
            strikes_around_atm=params.get("strikes", 10),
        )

    def get_historical_option_chain(self, ctx: StrategyContext, params: dict):
        # Prefer params (strike selection / SL pricing pass instrument calendar expiry); else ctx.
        raw = params.get("expiry_code", ctx.selected_expiry)
        expiry_index = ExpiryResolver.coerce_to_dhan_expiry_index(ctx.timestamp, raw)

        spot_price = ctx.spot_price
        raw = params["strike"]
        # Strategies pass either one strike or a list of candidate strikes (e.g. OTM ladder from mixins).
        if isinstance(raw, (list, tuple)):
            if not raw:
                raise ValueError("params['strike'] list is empty")
            target_strike = raw[0]
        else:
            target_strike = raw
        strike_step = 50
        atm_strike = round(spot_price / strike_step) * strike_step
        diff = int(float(target_strike)) - int(atm_strike)
        n = int(diff / strike_step)
        MAX_N = 10

        if n == 0:
            strike = "ATM"
        elif 0 < n <= MAX_N:
            strike = f"ATM+{n}"
        elif -MAX_N <= n < 0:
            strike = f"ATM{n}"
        elif n > MAX_N:
            strike = f"ATM+{MAX_N}"
        else:
            strike = f"ATM-{MAX_N}"

        ts = ctx.timestamp
        date_str = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)[:10]

        return self.data.get_expired_optionchain(
            exchange=params["exchange"],
            securityId=params["securityId"],
            interval=params["interval"],
            expiry_flag=params["expiry_flag"],
            expiry_code=expiry_index,
            strike=strike,
            option_type=params["option_type"],
            from_date=date_str,
            to_date=date_str,
            instrument=params["instrument"],
            exchangeSegment=params["exchangeSegment"],
        )
