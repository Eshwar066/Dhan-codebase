"""
Dynamic stock filter engine: ChartInk-style conditions (price_above, volume_above, etc.).
Uses DhanDataProvider v2 API (LTP, quote). No pandas in live path; lightweight only.
"""

import logging
from typing import Any, Dict, List, Optional

from core.library.dhan_marketfeed import (
    parse_ltp_response,
    parse_quote_response,
)

logger = logging.getLogger(__name__)


class StockFilterEngine:
    """
    Accepts filter_conditions dict (e.g. price_above, volume_above, rsi_below).
    Fetches LTP/quote via data_provider; computes only when required; returns filtered symbol list.
    No pandas in live path.
    """

    def __init__(
        self,
        data_provider: Any,
        segment: str = "NSE_EQ",
        engine_logger: Optional[Any] = None,
    ):
        self._data_provider = data_provider
        self._segment = segment
        self._engine_logger = engine_logger

    def _log(self, event: str, **kwargs: Any) -> None:
        if self._engine_logger and hasattr(self._engine_logger, "log"):
            self._engine_logger.log(event, **kwargs)
        else:
            logger.debug(event, extra=kwargs)

    def filter(
        self,
        symbols: List[str],
        conditions: Dict[str, Any],
        universe_service: Any,
    ) -> List[str]:
        """
        Filter symbols by conditions. Uses universe_service to build NSE_EQ instruments
        and to resolve security_id <-> symbol. Returns list of symbols passing all conditions.
        Never raises; on API/parse errors returns empty list.
        """
        if not symbols or not conditions:
            return list(symbols) if symbols else []

        instruments = universe_service.build_instruments_by_segment(symbols)
        if not instruments:
            return []

        id_to_symbol = getattr(universe_service, "get_security_id_to_symbol", lambda s: {})(symbols)
        if not id_to_symbol:
            for sym, meta in universe_service.get_meta_for_symbols(symbols).items():
                if getattr(meta, "security_id", None) is not None:
                    id_to_symbol[str(meta.security_id)] = sym

        # Fetch quote (has last_price, volume, ohlc) in one call
        try:
            raw_quote = self._data_provider.get_quote_v2(instruments)
        except Exception as e:
            self._log("filter_fetch_error", error=str(e))
            return []

        if not raw_quote:
            return []
        quote_by_id = parse_quote_response(raw_quote)
        if not quote_by_id:
            return []

        # Build per-symbol data (no pandas)
        def _float(v: Any) -> float:
            if v is None:
                return 0.0
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0

        passed = []
        for sec_id, q in quote_by_id.items():
            sym = id_to_symbol.get(sec_id)
            if not sym:
                continue
            price = _float(q.get("last_price"))
            ohlc = q.get("ohlc") or {}
            volume = _float(q.get("volume")) or _float(ohlc.get("volume"))
            open_p = _float(ohlc.get("open"))
            close_p = _float(ohlc.get("close")) if ohlc.get("close") is not None else price
            high = _float(ohlc.get("high")) if ohlc.get("high") is not None else price
            low = _float(ohlc.get("low")) if ohlc.get("low") is not None else price

            ok = True
            if "price_above" in conditions:
                if price <= _float(conditions["price_above"]):
                    ok = False
            if ok and "price_below" in conditions:
                if price >= _float(conditions["price_below"]):
                    ok = False
            if ok and "volume_above" in conditions:
                if volume < _float(conditions["volume_above"]):
                    ok = False
            if ok and "gap_percent_above" in conditions:
                if open_p <= 0:
                    ok = False
                else:
                    gap_pct = ((price - open_p) / open_p) * 100.0
                    if gap_pct < _float(conditions["gap_percent_above"]):
                        ok = False
            # RSI / market_cap need extra data; skip if not computable
            if ok and "rsi_below" in conditions:
                rsi_val = self._rsi_from_ohlc(open_p, high, low, close_p)
                if rsi_val is not None and rsi_val > _float(conditions["rsi_below"]):
                    ok = False
            if ok and "rsi_above" in conditions:
                rsi_val = self._rsi_from_ohlc(open_p, high, low, close_p)
                if rsi_val is not None and rsi_val < _float(conditions["rsi_above"]):
                    ok = False
            if ok:
                passed.append(sym)
        return passed

    @staticmethod
    def _rsi_from_ohlc(open_p: float, high: float, low: float, close: float) -> Optional[float]:
        """Single-bar RSI approximation (no pandas). Returns None if insufficient data."""
        if open_p <= 0:
            return None
        change = close - open_p
        up = max(change, 0.0)
        down = max(-change, 0.0)
        if down == 0:
            return 100.0 if up > 0 else 50.0
        rs = up / down
        return 100.0 - (100.0 / (1.0 + rs))
