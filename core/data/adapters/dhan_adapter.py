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
        sel = ctx.get_selected_expiry()
        expiry_date = None
        expiry_index = 0
        if ExpiryResolver.is_calendar_expiry(sel):
            expiry_date = ExpiryResolver.as_calendar_date(sel)
        elif sel is not None:
            try:
                expiry_index = int(sel)
            except (TypeError, ValueError):
                expiry_index = 0

        strikes = int(params.get("strikes", 60) or 60)

        return self.data.get_live_option_chain(
            symbol=ctx.symbol,
            exchange=ctx.exchange or "",
            expiry_index=expiry_index,
            strikes_around_atm=strikes,
            expiry_flag=params.get("expiry_flag", "MONTH"),
            expiry_date=expiry_date,
            expiry_match_same_month=bool(params.get("expiry_match_same_month", False)),
        )

    def get_historical_option_chain(self, ctx: StrategyContext, params: dict):
        # Prefer params (strike selection / SL pricing pass instrument calendar expiry); else ctx.
        raw_exp = params.get("expiry_code", ctx.selected_expiry)
        expiry_index = ExpiryResolver.coerce_to_dhan_expiry_index(ctx.timestamp, raw_exp)

        spot_price = float(ctx.spot_price or 0.0)
        raw = params["strike"]
        # Strategies pass either one strike or a list of candidate strikes (e.g. OTM ladder from mixins).
        if isinstance(raw, (list, tuple)):
            if not raw:
                raise ValueError("params['strike'] list is empty")
            strikes = list(raw)
        else:
            strikes = [raw]

        ts = ctx.timestamp
        date_str = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)[:10]

        return self.data.get_expired_optionchain(
            exchange=params["exchange"],
            securityId=params["securityId"],
            interval=params["interval"],
            expiry_flag=params["expiry_flag"],
            expiry_code=expiry_index,
            strike=strikes,
            option_type=params["option_type"],
            from_date=date_str,
            to_date=date_str,
            instrument=params["instrument"],
            exchangeSegment=params["exchangeSegment"],
            symbol=ctx.symbol,
            spot_price=spot_price,
        )
