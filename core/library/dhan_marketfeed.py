"""
Dhan v2 Market Quote API client.

Endpoints:
- POST /marketfeed/ltp   – LTP for list of instruments (up to 1000, rate limit 1 req/sec).
- POST /marketfeed/ohlc  – OHLC + LTP.
- POST /marketfeed/quote – Full market depth, OHLC, OI, volume.

Request body: { "NSE_EQ": [11536], "NSE_FNO": [49081, 49082], ... }
Headers: access-token (JWT), client-id.
"""

import time
from typing import Any, Dict, List, Optional

import requests


DHAN_MARKETFEED_BASE = "https://api.dhan.co/v2"


class DhanMarketFeedClient:
    """
    Client for Dhan v2 Market Quote API.
    Instruments: dict mapping exchange segment (e.g. NSE_EQ, NSE_FNO, IDX_I, MCX_COMM)
    to list of security IDs (int or str). Empty segments are omitted from the request.
    """

    def __init__(
        self,
        client_id: str,
        access_token: str,
        base_url: str = DHAN_MARKETFEED_BASE,
        rate_limit_seconds: float = 1.0,
    ):
        self.client_id = client_id
        self.access_token = access_token
        self.base_url = base_url.rstrip("/")
        self.rate_limit_seconds = rate_limit_seconds
        self._last_request_time: float = 0.0

    def _headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "access-token": self.access_token,
            "client-id": self.client_id,
        }

    def _payload(self, instruments: Dict[str, List[Any]]) -> Dict[str, List[int]]:
        """Build request body: only non-empty segments, values as list of ints."""
        out: Dict[str, List[int]] = {}
        for segment, ids in instruments.items():
            if not ids:
                continue
            out[segment] = [int(x) for x in ids]
        return out

    def _throttle(self) -> None:
        if self.rate_limit_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self.rate_limit_seconds:
            time.sleep(self.rate_limit_seconds - elapsed)
        self._last_request_time = time.monotonic()

    def _post(self, path: str, instruments: Dict[str, List[Any]]) -> Dict[str, Any]:
        self._throttle()
        url = f"{self.base_url}{path}"
        payload = self._payload(instruments)
        if not payload:
            return {
                "status": "failure",
                "data": {},
                "message": "No instruments provided",
            }
        resp = requests.post(url, headers=self._headers(), json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def ltp(self, instruments: Dict[str, List[Any]]) -> Dict[str, Any]:
        """
        Get LTP for instruments.
        Request: { "NSE_EQ": [11536], "NSE_FNO": [49081, 49082], ... }
        Response: { "status": "success", "data": { "NSE_EQ": { "11536": { "last_price": 4520 }, ... }, ... } }
        """
        return self._post("/marketfeed/ltp", instruments)

    def ohlc(self, instruments: Dict[str, List[Any]]) -> Dict[str, Any]:
        """
        Get OHLC + LTP for instruments.
        Response: { "status": "success", "data": { "NSE_EQ": { "11536": { "last_price": ..., "ohlc": { "open", "high", "low", "close" } }, ... }, ... } }
        """
        return self._post("/marketfeed/ohlc", instruments)

    def quote(self, instruments: Dict[str, List[Any]]) -> Dict[str, Any]:
        """
        Get full quote: market depth, OHLC, OI, volume, etc.
        Response: { "status": "success", "data": { "NSE_FNO": { "49081": { "last_price", "ohlc", "depth", "oi", "volume", ... } }, ... } }
        """
        return self._post("/marketfeed/quote", instruments)

    def parse_ltp_response(response: Dict[str, Any]) -> Dict[str, float]:
        """
        Flatten LTP API response to { symbol_or_id: last_price }.
        Caller must pass instrument_names mapping security_id (str) -> symbol if they want symbols as keys.
        """
        result: Dict[str, float] = {}
        if response.get("status") != "success":
            return result
        data = response.get("data") or {}
        for segment, sec_dict in data.items():
            if not isinstance(sec_dict, dict):
                continue
            for sec_id, obj in sec_dict.items():
                if isinstance(obj, dict) and "last_price" in obj:
                    result[str(sec_id)] = float(obj["last_price"])
        return result

    def parse_ohlc_response(
        response: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        """
        Flatten OHLC API response to { symbol_or_id: { last_price, open, high, low, close } }.
        """
        result: Dict[str, Dict[str, Any]] = {}
        if response.get("status") != "success":
            return result
        data = response.get("data") or {}
        for segment, sec_dict in data.items():
            if not isinstance(sec_dict, dict):
                continue
            for sec_id, obj in sec_dict.items():
                if not isinstance(obj, dict):
                    continue
                row = {"last_price": obj.get("last_price")}
                ohlc = obj.get("ohlc") or {}
                row["open"] = ohlc.get("open")
                row["high"] = ohlc.get("high")
                row["low"] = ohlc.get("low")
                row["close"] = ohlc.get("close")
                result[str(sec_id)] = row
        return result

    def parse_quote_response(response: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """
        Flatten Quote API response to { symbol_or_id: { last_price, ohlc, depth, oi, volume, ... } }.
        """
        result: Dict[str, Dict[str, Any]] = {}
        if response.get("status") != "success":
            return result
        data = response.get("data") or {}
        for segment, sec_dict in data.items():
            if not isinstance(sec_dict, dict):
                continue
            for sec_id, obj in sec_dict.items():
                if isinstance(obj, dict):
                    result[str(sec_id)] = dict(obj)
        return result
