"""
Kotak Neo source: REST market/order APIs via NeoAPI.
Used by KotakDataProvider and KotakBrokerApi.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from core.broker.internal.kotak import mappings as kotak_map
from core.utils.kotak_env import KotakCredentials, create_logged_in_neo_api, get_kotak_credentials

logger = logging.getLogger(__name__)


class KotakSource:
    """
    Single entry for Kotak Neo: orders, positions, quotes, scrip master.
    Historical candles are not available on NeoAPI — live engines use WS ticks.
    """

    def __init__(
        self,
        *,
        neo_api: Any = None,
        credentials: Optional[KotakCredentials] = None,
        auto_login: bool = True,
    ):
        if neo_api is not None:
            self._api = neo_api
        elif auto_login:
            self._api = create_logged_in_neo_api(credentials)
        else:
            creds = credentials or get_kotak_credentials()
            from core.library.kotak_neo.neo_api import NeoAPI

            env = "prod" if creds.environment in ("prod", "production", "live") else "uat"
            self._api = NeoAPI(
                environment=env,
                access_token=creds.access_token or None,
                neo_fin_key=creds.neo_fin_key or None,
                consumer_key=creds.consumer_key or None,
            )
        self._scrip_cache: Optional[List[Dict[str, Any]]] = None

    @property
    def api(self) -> Any:
        return self._api

    def place_order(self, **kwargs) -> Dict[str, Any]:
        raw = self._api.place_order(**kwargs)
        if kotak_map.is_error_response(raw):
            return {
                "status": "error",
                "order_id": None,
                "message": kotak_map.response_message(raw),
                "raw": raw,
            }
        oid = kotak_map.extract_order_id(raw)
        return {
            "status": "success" if oid else "error",
            "order_id": oid,
            "message": kotak_map.response_message(raw) if not oid else "",
            "raw": raw,
        }

    def modify_order(self, **kwargs) -> Dict[str, Any]:
        raw = self._api.modify_order(**kwargs)
        if kotak_map.is_error_response(raw):
            return {
                "status": "error",
                "order_id": kwargs.get("order_id"),
                "message": kotak_map.response_message(raw),
                "raw": raw,
            }
        oid = kotak_map.extract_order_id(raw) or kwargs.get("order_id")
        return {"status": "success", "order_id": oid, "raw": raw}

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        raw = self._api.cancel_order(order_id=str(order_id))
        if kotak_map.is_error_response(raw):
            return {
                "status": "error",
                "order_id": order_id,
                "message": kotak_map.response_message(raw),
                "raw": raw,
            }
        return {"status": "success", "order_id": order_id, "raw": raw}

    def get_positions(self, debug: str = "NO") -> Any:
        return self._api.positions()

    def get_holdings(self) -> Any:
        return self._api.holdings()

    def get_order_list(self) -> List[Dict[str, Any]]:
        raw = self._api.order_report()
        if isinstance(raw, list):
            return [r for r in raw if isinstance(r, dict)]
        if isinstance(raw, dict):
            data = raw.get("data")
            if isinstance(data, list):
                return [r for r in data if isinstance(r, dict)]
            if not kotak_map.is_error_response(raw):
                return [raw]
        return []

    def get_order_by_id(self, order_id: str) -> Optional[Dict[str, Any]]:
        oid = str(order_id or "").strip()
        if not oid:
            return None
        for row in self.get_order_list():
            for key in ("nOrdNo", "order_id", "orderId", "NOrdNo"):
                if str(row.get(key) or "").strip() == oid:
                    return row
        try:
            hist = self._api.order_history(order_id=oid)
        except Exception as e:
            logger.debug("Kotak order_history failed for %s: %s", oid, e)
            return None
        if isinstance(hist, list) and hist:
            return hist[0] if isinstance(hist[0], dict) else None
        if isinstance(hist, dict) and not kotak_map.is_error_response(hist):
            data = hist.get("data")
            if isinstance(data, list) and data:
                return data[0] if isinstance(data[0], dict) else None
            return hist
        return None

    def quotes(
        self,
        instrument_tokens: Optional[List[Dict[str, Any]]] = None,
        quote_type: Optional[str] = None,
    ) -> Any:
        return self._api.quotes(
            instrument_tokens=instrument_tokens, quote_type=quote_type
        )

    def search_scrip(
        self,
        *,
        exchange_segment: str,
        symbol: str,
        expiry: Optional[str] = None,
        option_type: Optional[str] = None,
        strike_price: Optional[str] = None,
    ) -> Any:
        return self._api.search_scrip(
            exchange_segment=exchange_segment,
            symbol=symbol,
            expiry=expiry,
            option_type=option_type,
            strike_price=strike_price,
        )

    def scrip_master(
        self, exchange_segment: Optional[str] = None, force: bool = False
    ) -> List[Dict[str, Any]]:
        if self._scrip_cache is not None and not force and exchange_segment is None:
            return self._scrip_cache
        raw = self._api.scrip_master(exchange_segment=exchange_segment)
        rows: List[Dict[str, Any]] = []
        if isinstance(raw, list):
            rows = [r for r in raw if isinstance(r, dict)]
        elif isinstance(raw, dict):
            data = raw.get("data") or raw.get("scripMaster") or raw.get("scrips")
            if isinstance(data, list):
                rows = [r for r in data if isinstance(r, dict)]
        if exchange_segment is None:
            self._scrip_cache = rows
        return rows

    def limits(self) -> Any:
        return self._api.limits()

    def margin_required(self, **kwargs) -> Any:
        return self._api.margin_required(**kwargs)
