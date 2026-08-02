"""Kotak Neo adapter for live option chains (DHAN-shaped DataFrame contract)."""

from __future__ import annotations

from .base import BaseAdapter
from core.models.strategy_context import StrategyContext
from core.utils.expiry_resolver import ExpiryResolver


class KotakAdapter(BaseAdapter):
    """Live option chain / expiries via KotakDataProvider. No Dhan broker coupling."""

    def get_expiries(self, ctx: StrategyContext):
        store = ctx.instrument_store
        if store is not None and hasattr(self.data, "bind_instrument_store"):
            self.data.bind_instrument_store(store)
        expiries = self.data.get_live_expiry(
            symbol=ctx.symbol,
            exchange=ctx.exchange or "",
        )
        return expiries or []

    def get_option_chain(self, ctx: StrategyContext, params: dict):
        store = ctx.instrument_store
        if store is not None and hasattr(self.data, "bind_instrument_store"):
            self.data.bind_instrument_store(store)

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
            spot_price=float(ctx.spot_price or 0.0),
        )

    def get_historical_option_chain(self, ctx: StrategyContext, params: dict):
        # Neo has no historical option-chain API; KOTAK backtests use Dhan provider.
        raise NotImplementedError(
            "KotakAdapter does not support historical option chains; "
            "use DHAN/NSE adapter for backtest"
        )
