from .base import BaseAdapter

from core.models.strategy_context import StrategyContext


class DeltaAdapter(BaseAdapter):
    """
    Adapter for Delta Exchange option chain data.
    Uses DeltaDataProvider (via data_service) which wraps DeltaSource.
    """

    def get_expiries(self, ctx: StrategyContext):
        expiries = self.data.get_live_expiry(
            symbol=ctx.symbol,
            exchange=ctx.exchange or "",
        )
        if not expiries:
            return []
        return expiries

    def get_option_chain(self, ctx: StrategyContext, params: dict):
        """
        Fetch live option chain from Delta.
        Delta uses product symbols like C-ETH-2430-191026, not traditional chain format.
        """
        # DeltaDataProvider has get_live_option_chain method
        # but we need to get products and filter by expiry/strike
        expiry_code = params.get("expiry_code", ctx.selected_expiry)
        if not expiry_code:
            # Try to get from context
            expiry_code = getattr(ctx, "selected_expiry", None)

        # Get products from DeltaSource
        products = self.data.get_products()
        if not products:
            return None

        # Filter products for the symbol and expiry
        underlying = ctx.symbol.replace("USD", "")  # e.g., ETHUSD -> ETH
        prefix_c = f"C-{underlying}-"
        prefix_p = f"P-{underlying}-"

        matching = [
            p for p in products
            if str(p.get("symbol") or "").upper().startswith(prefix_c)
            or str(p.get("symbol") or "").upper().startswith(prefix_p)
        ]

        if expiry_code:
            matching = [p for p in matching if self._product_expiry(p) == expiry_code]

        # Format as option chain
        chain = {"records": {"data": []}}
        for p in matching:
            chain["records"]["data"].append({
                "symbol": p.get("symbol"),
                "strike_price": p.get("strike_price"),
                "expiry": self._product_expiry(p),
                "option_type": "CE" if "C-" in str(p.get("symbol", "")).upper() else "PE",
                "last_price": p.get("last_price", 0),
                "bid": p.get("best_bid", 0),
                "ask": p.get("best_ask", 0),
                "iv": p.get("iv", 0),
                "oi": p.get("open_interest", 0),
                "volume": p.get("volume_24h", 0),
            })

        return chain

    def get_historical_option_chain(self, ctx: StrategyContext, params: dict):
        # Delta doesn't have historical option chain in the same way
        # Return empty chain
        return {"records": {"data": []}}

    @staticmethod
    def _product_expiry(product: dict) -> str:
        symbol = str(product.get("symbol") or "").upper()
        parts = symbol.split("-")
        return str(parts[-1]).strip() if len(parts) >= 4 else ""

    @staticmethod
    def _product_strike(product: dict):
        value = product.get("strike_price")
        if value is None:
            parts = str(product.get("symbol") or "").split("-")
            value = parts[2] if len(parts) >= 4 else None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None