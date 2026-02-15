"""
Delta Exchange source: market data and order/position APIs via delta_rest_client.
Used by DeltaDataProvider (data layer) and DeltaBrokerApi (broker layer).
"""

import os
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
import requests
import pandas as pd
from datetime import datetime
from typing import Optional, Any


from core.library.delta_rest_client import (
    DeltaRestClient,
    OrderType,
    TimeInForce,
    parseResponse,
)

# Delta Exchange base URLs
DELTA_BASE_URL_INDIA_PROD = "https://api.india.delta.exchange"
DELTA_BASE_URL_INDIA_TEST = "https://cdn-ind.testnet.deltaex.org"
DELTA_BASE_URL_GLOBAL_PROD = "https://api.delta.exchange"
DELTA_BASE_URL_GLOBAL_TEST = "https://testnet-api.delta.exchange"


class DeltaSource:
    """
    Single entry point for Delta Exchange: market data and order/position APIs.
    Uses core.library.delta_rest_client.DeltaRestClient.
    """

    def __init__(
        self,
        testnet: bool = True,
        india: bool = False,
    ):
        load_dotenv()
        base_url = os.getenv("DELTA_BASE_URL")
        api_key = os.getenv("DELTA_API_KEY")
        api_secret = os.getenv("DELTA_API_SECRET")

        if not api_key or not api_secret:
            raise ValueError("Delta API credentials not found in environment variables")
        if base_url is None:
            if india:
                base_url = (
                    DELTA_BASE_URL_INDIA_TEST if testnet else DELTA_BASE_URL_INDIA_PROD
                )
            else:
                base_url = (
                    DELTA_BASE_URL_GLOBAL_TEST
                    if testnet
                    else DELTA_BASE_URL_GLOBAL_PROD
                )
        self._client = DeltaRestClient(
            base_url=base_url,
            api_key=api_key,
            api_secret=api_secret,
            raise_for_status=True,
        )
        self._products_cache: Optional[List[Dict]] = None
        self._symbol_to_product: Dict[str, Dict] = {}

    @property
    def client(self) -> DeltaRestClient:
        """Raw Delta REST client for advanced use."""
        return self._client

    # -------------------------------------------------------------------------
    # Products (symbol <-> product_id)
    # -------------------------------------------------------------------------
    def get_products(self, use_cache: bool = True) -> List[Dict]:
        """List all tradable products. Cached by default."""
        if use_cache and self._products_cache is not None:
            return self._products_cache
        self._products_cache = self._client.get_products(auth=False)
        if not isinstance(self._products_cache, list):
            self._products_cache = []
        self._symbol_to_product = {}
        for p in self._products_cache:
            sym = p.get("symbol") or p.get("trading_symbol") or str(p.get("id", ""))
            self._symbol_to_product[sym] = p
            self._symbol_to_product[str(p.get("id"))] = p
        return self._products_cache

    def product_id_for_symbol(self, symbol: str) -> Optional[int]:
        """Resolve symbol (e.g. BTCUSD) or product symbol to product_id."""
        self.get_products(use_cache=True)
        p = self._symbol_to_product.get(symbol)
        if p is not None:
            return p.get("id")
        for prod in self._products_cache or []:
            if (prod.get("symbol") or "").upper() == str(symbol).upper():
                return prod.get("id")
        return None

    # -------------------------------------------------------------------------
    # Data: Ticker / LTP / orderbook
    # -------------------------------------------------------------------------
    def get_ticker(self, identifier: str) -> Any:
        """Single ticker by symbol or product identifier."""
        return self._client.get_ticker(identifier, auth=False)

    def get_l2_orderbook(self, identifier: str) -> Any:
        """L2 orderbook by symbol or product identifier."""
        return self._client.get_l2_orderbook(identifier, auth=False)

    def get_latest_candles(
        self, symbols: List[str], debug: str = "NO"
    ) -> Optional[Dict[str, Dict]]:
        """
        Latest price/candle-like data per symbol from ticker.
        Returns { symbol: { open, high, low, close, ltp, volume, ... } }.
        """
        if not symbols:
            return {}
        out = {}
        for sym in symbols:
            try:
                t = self._client.get_ticker(sym, auth=False)
                if not t:
                    continue
                # Delta ticker often has: mark_price, last_price, open_interest, etc.
                ltp = float(
                    t.get("mark_price") or t.get("last_price") or t.get("close") or 0
                )
                out[sym] = {
                    "open": ltp,
                    "high": ltp,
                    "low": ltp,
                    "close": ltp,
                    "ltp": ltp,
                    "volume": t.get("volume") or 0,
                    "symbol": sym,
                }
            except Exception:
                continue
        return out if out else None

    def get_intraday(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        timeframe: str,
    ) -> Optional[Any]:

        try:
            # Convert to UNIX timestamps
            start_ts = int(datetime.fromisoformat(start_date).timestamp())
            end_ts = int(datetime.fromisoformat(end_date).timestamp())

            # Map timeframe (if needed)
            resolution_map = {
                "1m": "1m",
                "3m": "3m",
                "5m": "5m",
                "15m": "15m",
                "30m": "30m",
                "1h": "1h",
                "2h": "2h",
                "4h": "4h",
                "6h": "6h",
                "1d": "1d",
                "1w": "1w",
            }

            resolution = resolution_map.get(timeframe, "5m")

            url = "https://api.india.delta.exchange/v2/history/candles"

            headers = {"Accept": "application/json"}

            params = {
                "resolution": resolution,
                "symbol": symbol,
                "start": start_ts,
                "end": end_ts,
            }

            response = requests.get(url, params=params, headers=headers)
            response.raise_for_status()

            data = response.json()

            if not data.get("success"):
                return None

            candles = data["result"]

            # Convert to DataFrame
            df = pd.DataFrame(candles)

            # Rename columns to match your engine standard
            df.rename(
                columns={
                    "time": "timestamp",
                    "open": "open",
                    "high": "high",
                    "low": "low",
                    "close": "close",
                    "volume": "volume",
                },
                inplace=True,
            )

            # Convert timestamp to datetime
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")

            df.sort_values("timestamp", inplace=True)
            df.reset_index(drop=True, inplace=True)

            return df

        except Exception as e:
            print(f"Delta get_intraday error: {e}")
            return None

    def get_live_expiry(self, symbol: str, exchange: str = None) -> List[Any]:
        """Expiry list from products (e.g. futures/options expiries)."""
        products = self.get_products(use_cache=True)
        expiries = set()
        for p in products:
            sym = (p.get("symbol") or "").upper()
            if symbol.upper() in sym or not symbol:
                e = p.get("expiry_date") or p.get("expiry") or p.get("settlement_date")
                if e:
                    expiries.add(e)
        return sorted(expiries)

    def get_live_option_chain(
        self,
        symbol: str,
        exchange: str,
        expiry_index: int,
        strikes_around_atm: int,
    ) -> Optional[Dict]:
        """Minimal option chain from products (Delta options)."""
        products = self.get_products(use_cache=True)
        chain = [
            p
            for p in products
            if (p.get("symbol") or "").upper().startswith(symbol.upper())
        ]
        if not chain:
            return None
        return {"symbol": symbol, "exchange": exchange, "chain": chain}

    def get_expired_optionchain(self, *args, **kwargs) -> Any:
        """Not provided by Delta REST in this client."""
        return None

    # -------------------------------------------------------------------------
    # Wallet / assets
    # -------------------------------------------------------------------------
    def get_assets(self, auth: bool = False) -> Any:
        return self._client.get_assets(auth=auth)

    def get_balances(self, asset_id: int) -> Any:
        return self._client.get_balances(asset_id)

    # -------------------------------------------------------------------------
    # Positions
    # -------------------------------------------------------------------------
    def get_position(self, product_id: int) -> Any:
        return self._client.get_position(product_id)

    def get_margined_position(self, product_id) -> Any:
        return self._client.get_margined_position(product_id)

    def get_positions(self, debug: str = "NO") -> Any:
        """All positions in a list; normalize to Dhan-like rows for broker sync."""
        raw = self._client.get_all_positions()
        if not isinstance(raw, list):
            return []
        # Normalize to list of dicts with tradingSymbol, netQty, avgPrice, etc.
        rows = []
        for p in raw:
            product_id = p.get("product_id") or p.get("id")
            size = int(p.get("size") or 0)
            entry_price = float(
                p.get("entry_price") or p.get("average_fill_price") or 0
            )
            rows.append(
                {
                    "tradingSymbol": str(
                        p.get("product", {}).get("symbol", product_id)
                    ),
                    "product_id": product_id,
                    "netQty": size,
                    "avgPrice": entry_price,
                    "segment": "DELTA",
                    "lotSize": 1,
                }
            )
        return rows

    # -------------------------------------------------------------------------
    # Orders
    # -------------------------------------------------------------------------
    def place_order(
        self,
        product_id: int,
        size: int,
        side: str,
        limit_price: Optional[float] = None,
        order_type: str = "MARKET",
        client_order_id: Optional[str] = None,
        reduce_only: str = "false",
        time_in_force: Optional[str] = None,
        post_only: str = "false",
    ) -> Dict[str, Any]:
        """
        Place order via Delta. Returns { status, order_id }.
        side: buy | sell (lowercase).
        order_type: MARKET | LIMIT.
        """
        side = (side or "buy").lower()
        ot = (
            OrderType.MARKET
            if (order_type or "MARKET").upper() == "MARKET"
            else OrderType.LIMIT
        )
        tif = None
        if time_in_force:
            tif = getattr(TimeInForce, time_in_force.upper(), None)
        try:
            result = self._client.place_order(
                product_id=product_id,
                size=size,
                side=side,
                limit_price=limit_price,
                time_in_force=tif,
                order_type=ot,
                post_only=post_only,
                client_order_id=client_order_id,
                reduce_only=reduce_only,
            )
            oid = result.get("id") or result.get("order_id")
            return {
                "status": "success",
                "order_id": str(oid) if oid is not None else None,
            }
        except Exception as e:
            return {"status": "error", "order_id": None, "message": str(e)}

    def get_order_list(self) -> List[Dict[str, Any]]:
        """Live orders for idempotency / status. Normalized to have order_id, tag."""
        try:
            raw = self._client.get_live_orders(query=None)
            if not isinstance(raw, list):
                return []
            return [
                {
                    "order_id": str(o.get("id", "")),
                    "tag": o.get("client_order_id"),
                    "product_id": o.get("product_id"),
                    "status": o.get("state"),
                }
                for o in raw
            ]
        except Exception:
            return []

    def cancel_order(self, product_id: int, order_id: Any) -> Any:
        return self._client.cancel_order(product_id=product_id, order_id=order_id)

    def get_live_orders(self, query: Optional[Dict] = None) -> Any:
        return self._client.get_live_orders(query=query)

    # -------------------------------------------------------------------------
    # Advanced: stop orders, leverage, margin, batch, history
    # -------------------------------------------------------------------------
    def place_stop_order(
        self,
        product_id: int,
        size: int,
        side: str,
        stop_price: Optional[float] = None,
        limit_price: Optional[float] = None,
        trail_amount: Optional[float] = None,
        order_type: str = "LIMIT",
        is_trailing_stop_loss: bool = False,
    ) -> Any:
        ot = OrderType.LIMIT if order_type.upper() == "LIMIT" else OrderType.MARKET
        return self._client.place_stop_order(
            product_id=product_id,
            size=size,
            side=side.lower(),
            stop_price=stop_price,
            limit_price=limit_price,
            trail_amount=trail_amount,
            order_type=ot,
            isTrailingStopLoss=is_trailing_stop_loss,
        )

    def set_leverage(self, product_id: int, leverage: int) -> Any:
        return self._client.set_leverage(product_id=product_id, leverage=leverage)

    def change_position_margin(self, product_id: int, delta_margin: float) -> Any:
        return self._client.change_position_margin(
            product_id=product_id, delta_margin=delta_margin
        )

    def batch_create(self, product_id: int, orders: List[Dict]) -> Any:
        return self._client.batch_create(product_id=product_id, orders=orders)

    def batch_cancel(self, product_id: int, orders: List[Dict]) -> Any:
        return self._client.batch_cancel(product_id=product_id, orders=orders)

    def batch_edit(self, product_id: int, orders: List[Dict]) -> Any:
        return self._client.batch_edit(product_id=product_id, orders=orders)

    def order_history(
        self, query: Optional[Dict] = None, page_size: int = 100, after: Any = None
    ) -> Any:
        return self._client.order_history(
            query=query or {}, page_size=page_size, after=after
        )

    def fills(
        self, query: Optional[Dict] = None, page_size: int = 100, after: Any = None
    ) -> Any:
        return self._client.fills(query=query or {}, page_size=page_size, after=after)
