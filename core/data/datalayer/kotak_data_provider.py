"""
Kotak Neo data provider (quotes / scrip / live option chain).

Neo has no historical candles; live bars come from KotakWebSocketFeed +
CandleAggregator. Live option chains are synthesised from the NSE instrument
master CSV + Neo quotes (REST, with SFeed websocket fallback).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, List, Optional

import pandas as pd

from core.data.option_chain.kotak_chain import (
    build_dhan_shaped_chain,
    list_option_expiries,
    option_rows_for_expiry,
    resolve_expiry,
)
from core.utils.expiry_resolver import ExpiryResolver

from .base import IDataProvider

logger = logging.getLogger(__name__)


class KotakDataProvider(IDataProvider):
    """Data layer for Kotak Neo. Orders belong to the broker layer."""

    def __init__(self, kotak_source, instrument_store: Any = None):
        self._source = kotak_source
        self._instrument_store = instrument_store

    def bind_instrument_store(self, store: Any) -> None:
        self._instrument_store = store

    def _instruments_df(self) -> Optional[pd.DataFrame]:
        store = self._instrument_store
        if store is None:
            return None
        df = getattr(store, "df", None)
        return df if isinstance(df, pd.DataFrame) else None

    def get_intraday(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        timeframe: str,
        exchange: str = None,
        sector: str = None,
    ) -> Optional[pd.DataFrame]:
        # Neo wrapper has no historical OHLC API during dual-broker phase.
        return None

    def get_latest_candles(
        self, symbols: List[str], debug: str = "NO"
    ) -> Optional[dict]:
        return None

    def get_live_expiry(self, symbol: str, exchange: str = None) -> Any:
        store = self._instrument_store
        if store is not None and hasattr(store, "list_option_expiries"):
            return store.list_option_expiries(symbol, monthly_only=False)
        df = self._instruments_df()
        if df is None:
            logger.warning("Kotak get_live_expiry: no instrument store bound")
            return []
        return list_option_expiries(df, symbol, monthly_only=False)

    def get_live_option_chain(
        self,
        symbol: str,
        exchange: str,
        expiry_index: int,
        strikes_around_atm: int,
        expiry_flag: str,
        expiry_date=None,
        expiry_match_same_month: bool = False,
        spot_price: float = 0.0,
    ) -> Optional[dict]:
        store = self._instrument_store
        df = self._instruments_df()
        if df is None or df.empty:
            logger.warning(
                "Kotak get_live_option_chain: instrument master missing for %s",
                symbol,
            )
            return None

        monthly_only = str(expiry_flag or "").upper() in (
            "MONTH",
            "MONTHLY",
            "M",
        )
        if store is not None and hasattr(store, "list_option_expiries"):
            expiries = store.list_option_expiries(symbol, monthly_only=monthly_only)
        else:
            expiries = list_option_expiries(df, symbol, monthly_only=monthly_only)
        if not expiries:
            # Fall back to all expiries if monthly filter emptied the list
            if monthly_only:
                if store is not None and hasattr(store, "list_option_expiries"):
                    expiries = store.list_option_expiries(symbol, monthly_only=False)
                else:
                    expiries = list_option_expiries(df, symbol, monthly_only=False)
        if not expiries:
            logger.warning(
                "Kotak get_live_option_chain: no expiries for symbol=%s", symbol
            )
            return None

        resolved = resolve_expiry(
            expiries,
            expiry_index=expiry_index,
            expiry_date=expiry_date,
            expiry_match_same_month=expiry_match_same_month,
        )
        if resolved is None:
            return None

        if store is not None and hasattr(store, "list_options_for_expiry"):
            opt_rows = store.list_options_for_expiry(
                symbol, resolved, monthly_only=False
            )
        else:
            opt_rows = option_rows_for_expiry(
                df, symbol, resolved, monthly_only=False
            )
        if opt_rows is None or opt_rows.empty:
            logger.warning(
                "Kotak get_live_option_chain: no option rows symbol=%s expiry=%s",
                symbol,
                resolved,
            )
            return None

        spot = float(spot_price or 0.0)
        if spot <= 0:
            # Best-effort index LTP via WS/REST using INDEX security id from store
            spot = self._resolve_spot(symbol, exchange) or 0.0
        if spot <= 0:
            logger.warning(
                "Kotak get_live_option_chain: spot_price missing for %s", symbol
            )
            return None

        # Narrow to strikes near ATM before quoting (keeps WS batch small)
        strikes = pd.to_numeric(opt_rows["SEM_STRIKE_PRICE"], errors="coerce")
        opt_rows = opt_rows.assign(_strike=strikes).dropna(subset=["_strike"])
        from core.data.option_chain.kotak_chain import (
            atm_strike_from_spot,
            filter_strikes_around_atm,
        )

        atm_pre = atm_strike_from_spot(spot, opt_rows["_strike"].tolist())
        if atm_pre is None:
            return None
        keep = set(
            filter_strikes_around_atm(
                opt_rows["_strike"].tolist(), atm_pre, int(strikes_around_atm or 60)
            )
        )
        opt_rows = opt_rows.loc[opt_rows["_strike"].isin(keep)].drop(
            columns=["_strike"], errors="ignore"
        )

        tokens: List[dict] = []
        for _, r in opt_rows.iterrows():
            tok = str(r.get("SEM_SMST_SECURITY_ID") or "").strip()
            if not tok:
                continue
            tokens.append(
                {"instrument_token": tok, "exchange_segment": "nse_fo"}
            )

        quotes = self._source.fetch_quote_map(tokens)
        chain, atm = build_dhan_shaped_chain(
            opt_rows,
            quotes,
            spot_price=spot,
            strikes_around_atm=int(strikes_around_atm or 60),
        )
        if chain is None or chain.empty:
            return None

        expiry_str = (
            resolved.isoformat()
            if isinstance(resolved, date)
            else str(ExpiryResolver.as_calendar_date(resolved) or resolved)
        )
        return {
            "symbol": symbol,
            "exchange": exchange,
            "chain": chain,
            "atm_strike": atm,
            "expiry": expiry_str,
        }

    def _resolve_spot(self, symbol: str, exchange: str = None) -> Optional[float]:
        store = self._instrument_store
        if store is None or not hasattr(store, "get_feed_instruments"):
            return None
        try:
            feed = store.get_feed_instruments([symbol])
        except Exception:
            return None
        if not feed:
            return None
        row = feed[0]
        tok = str(row.get("instrument_token") or row.get("SecurityId") or "").strip()
        seg = str(row.get("exchange_segment") or "nse_cm").strip()
        if not tok:
            return None
        qmap = self._source.fetch_quote_map(
            [{"instrument_token": tok, "exchange_segment": seg}],
            ws_timeout_sec=8.0,
        )
        raw = qmap.get(tok)
        if raw is None:
            return None
        from core.data.option_chain.kotak_chain import quote_fields

        ltp = quote_fields(raw).get("ltp") or 0.0
        return float(ltp) if ltp and ltp > 0 else None
