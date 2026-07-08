"""
Dhan data and order execution via in-project Tradehull library.
All data feeding (candles, LTP, option chain, expiries) and order placement
go through this source; the data layer (DhanDataProvider) and broker layer
(DhanBrokerApi) wrap it for engines and order management.
"""

import logging
import os
import sys
import time
import pandas as pd
logger = logging.getLogger(__name__)
from datetime import date, datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
import requests
import json

# Use in-project Dhan Tradehull library and v2 Market Quote API
from core.library.dhan_tradehull import Tradehull
from datetime import datetime
from core.library.dhan_marketfeed import (
    DhanMarketFeedClient,
    parse_ltp_response,
    parse_ohlc_response,
    parse_quote_response,
)
from core.data.sources.NSEClient import NSEClient
from core.data.sources.dhan_historical_cache import (
    cache_key_futures,
    cache_key_intraday,
    load_df,
    save_df,
)
from core.utils.expiry_resolver import ExpiryResolver
from core.utils.dhan_expired_option_chain_files import (
    default_expired_option_chain_root,
    load_expired_option_chain_from_files,
    strikes_to_atm_folder_labels,
)

load_dotenv()

# Project root: parent of 'core' so that Dependencies/ and instrument file paths work
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class DhanSource:
    """
    Single entry point for Dhan: market data (for data layer) and order placement (for broker).
    Uses core.library.dhan_tradehull.Tradehull for all Dhan API calls.
    """

    def __init__(self, client_id=None, access_token=None, dependencies_path=None):
        client_id = client_id or os.getenv("DHAN_CLIENT_CODE")
        access_token = access_token or os.getenv("DHAN_ACCESS_TOKEN")
        if not client_id or not access_token:
            raise RuntimeError(
                "❌ Dhan credentials missing (DHAN_CLIENT_CODE, DHAN_ACCESS_TOKEN)"
            )

        self._deps_path = Path(dependencies_path or PROJECT_ROOT / "Dependencies")
        self._ensure_deps_path()

        self.tsl = Tradehull(client_id, access_token)
        self.tsl.validate_api_credentials()
        self._latest_candles_req_cache: dict = {}
        self._latest_candles_backoff_until = 0.0
        self._marketfeed = DhanMarketFeedClient(
            client_id=client_id,
            access_token=access_token,
            rate_limit_seconds=1.0,
        )
        self.expiry_cache = {}
        self.nse_client = NSEClient()

    def _ensure_deps_path(self):
        """Ensure Dependencies folder exists for Tradehull instrument file."""
        self._deps_path.mkdir(parents=True, exist_ok=True)
        # Tradehull uses os.listdir("Dependencies") and "Dependencies\\file" - run from project root
        if os.getcwd() != str(PROJECT_ROOT):
            os.chdir(PROJECT_ROOT)

    @staticmethod
    def _to_date(value):
        """Normalize to date for range comparison."""
        if value is None:
            return None
        if hasattr(value, "date") and callable(getattr(value, "date")):
            return value.date() if isinstance(value, datetime) else value
        if hasattr(value, "strftime"):
            return value
        s = str(value).strip()
        if not s:
            return None
        try:
            return datetime.fromisoformat(s[:10]).date()
        except ValueError:
            return datetime.strptime(s[:10], "%Y-%m-%d").date()

    # -------------------------------------------------------------------------
    # Data: Candles / OHLC
    # -------------------------------------------------------------------------
    def get_latest_candles(self, symbols, debug="NO"):
        """Latest OHLC/LTP per symbol. Returns dict { symbol: { open, high, low, close, ... } }."""
        if not isinstance(symbols, list):
            symbols = [symbols]
        now = time.time()
        cache_key = tuple(sorted(str(s).strip().upper() for s in symbols if str(s).strip()))
        cached = self._latest_candles_req_cache.get(cache_key)
        if cached and (now - cached[0]) < 15.0:
            return dict(cached[1])
        if now < float(self._latest_candles_backoff_until or 0.0):
            if cached:
                return dict(cached[1])
            return {}
        data = self.tsl.get_ohlc_data(symbols, debug) or {}
        if data:
            self._latest_candles_req_cache[cache_key] = (now, dict(data))
        backoff = float(getattr(self.tsl, "_ohlc_backoff_until", 0.0) or 0.0)
        if backoff > now:
            self._latest_candles_backoff_until = backoff
        elif cached and not data:
            return dict(cached[1])
        return data

    def _normalize_intraday_df(self, df: pd.DataFrame) -> pd.DataFrame | None:
        """Normalize raw API df: timestamp column, sort, time column. Returns None if invalid."""
        if df is None or df.empty:
            return None
        if "timestamp" in df.columns:
            df = df.copy()
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        elif "date" in df.columns:
            df = df.copy()
            df["timestamp"] = pd.to_datetime(df["date"], utc=True)
        elif "start_Time" in df.columns:
            df = df.copy()
            df["timestamp"] = pd.to_datetime(df["start_Time"], utc=True)
        else:
            return None
        df = (
            df.sort_values("timestamp")
            .drop_duplicates(subset=["timestamp"])
            .reset_index(drop=True)
        )
        df["time"] = df["timestamp"].dt.time
        return df

    def get_intraday(self, symbol, start_date, end_date, timeframe, exchange, sector):
        """Long-term historical intraday. Cache key = symbol+timeframe+exchange (no dates). Returns requested range; fetches only missing dates and stitches into same cache file."""
        cache_name = cache_key_intraday(symbol, str(timeframe), exchange or "")
        start_d = self._to_date(start_date)
        end_d = self._to_date(end_date)
        if start_d is None or end_d is None:
            return None

        cached = load_df(cache_name)
        stitched = cached.copy() if cached is not None and not cached.empty else None

        if (
            stitched is not None
            and not stitched.empty
            and "timestamp" in stitched.columns
        ):
            stitched["timestamp"] = pd.to_datetime(stitched["timestamp"], utc=True)
            stitched["time"] = stitched["timestamp"].dt.time
            earliest = stitched["timestamp"].dt.date.min()
            latest = stitched["timestamp"].dt.date.max()
            if (
                pd.notna(earliest)
                and pd.notna(latest)
                and earliest <= start_d
                and latest >= end_d
            ):
                out = stitched[
                    (stitched["timestamp"].dt.date >= start_d)
                    & (stitched["timestamp"].dt.date <= end_d)
                ].copy()
                return out.reset_index(drop=True)

        # Backward fetch: need data before current earliest
        cache_earliest = (
            stitched["timestamp"].dt.date.min()
            if stitched is not None
            and not stitched.empty
            and "timestamp" in stitched.columns
            else None
        )
        if (
            cache_earliest is None
            or pd.isna(cache_earliest)
            or start_d < cache_earliest
        ):
            fetch_end = (
                (cache_earliest - timedelta(days=1))
                if cache_earliest is not None and pd.notna(cache_earliest)
                else end_d
            )
            before = self.tsl.get_long_term_historical_data(
                tradingsymbol=symbol,
                exchange=exchange,
                timeframe=timeframe,
                from_date=start_d,
                to_date=fetch_end,
                sector=sector or "NO",
            )
            before = self._normalize_intraday_df(before)
            if before is not None and not before.empty:
                stitched = (
                    pd.concat([before, stitched], ignore_index=True)
                    if stitched is not None and not stitched.empty
                    else before
                )
            elif stitched is None:
                stitched = before

        # Ensure timestamp is datetime (concat can yield object dtype); utc=True for tz-aware values
        if (
            stitched is not None
            and not stitched.empty
            and "timestamp" in stitched.columns
        ):
            stitched["timestamp"] = pd.to_datetime(stitched["timestamp"], utc=True)
            stitched["time"] = stitched["timestamp"].dt.time

        # Forward fetch: need data after current latest
        cache_latest = (
            stitched["timestamp"].dt.date.max()
            if stitched is not None and not stitched.empty
            else None
        )
        if cache_latest is not None and pd.notna(cache_latest) and end_d > cache_latest:
            fetch_start = stitched["timestamp"].dt.date.max() + timedelta(days=1)
            after = self.tsl.get_long_term_historical_data(
                tradingsymbol=symbol,
                exchange=exchange,
                timeframe=timeframe,
                from_date=fetch_start,
                to_date=end_d,
                sector=sector or "NO",
            )
            after = self._normalize_intraday_df(after)
            if after is not None and not after.empty:
                stitched = pd.concat([stitched, after], ignore_index=True)

        if stitched is None or stitched.empty:
            return None
        stitched["timestamp"] = pd.to_datetime(stitched["timestamp"], utc=True)
        stitched["time"] = stitched["timestamp"].dt.time
        stitched = (
            stitched.sort_values("timestamp")
            .drop_duplicates(subset=["timestamp"])
            .reset_index(drop=True)
        )
        save_df(cache_name, stitched)
        out = stitched[
            (stitched["timestamp"].dt.date >= start_d)
            & (stitched["timestamp"].dt.date <= end_d)
        ].copy()
        return out.reset_index(drop=True)

    def _fetch_futures_intraday(
        self,
        security_id: str,
        exchange_segment: str,
        instrument: str,
        interval: str,
        from_date: str,
        to_date: str,
        oi: bool,
    ) -> pd.DataFrame:
        """Call Dhan charts/intraday API and return normalized DataFrame."""
        payload = {
            "securityId": str(security_id),
            "exchangeSegment": exchange_segment,
            "instrument": instrument,
            "interval": str(interval),
            "oi": oi,
            "fromDate": from_date,
            "toDate": to_date,
            "exchange": "NSE",
            "sector": "NO",
        }
        headers = {
            "Content-Type": "application/json",
            "access-token": os.getenv("DHAN_ACCESS_TOKEN"),
            "client-id": os.getenv("DHAN_CLIENT_CODE"),
        }
        response = requests.post(
            "https://api.dhan.co/v2/charts/intraday",
            headers=headers,
            data=json.dumps(payload),
        )
        if response.status_code != 200:
            raise Exception(f"API Error {response.status_code}: {response.text}")
        data = response.json()
        if not data or "timestamp" not in data:
            return pd.DataFrame()
        df = pd.DataFrame(
            {
                "timestamp": data["timestamp"],
                "open": data["open"],
                "high": data["high"],
                "low": data["low"],
                "close": data["close"],
                "volume": data["volume"],
            }
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        df["timestamp"] = df["timestamp"].dt.tz_convert("Asia/Kolkata")
        return df

    # not providing exact data
    def get_Futures_historical_intraday_data(
        self,
        security_id: str,
        exchange_segment: str,
        instrument: str,
        interval: str,
        from_date: str,
        to_date: str,
        oi: bool = False,
    ):
        """Futures intraday. Cache key = security+segment+instrument+interval+oi (no dates). Fetches only missing range and stitches into same cache file."""
        cache_name = cache_key_futures(
            str(security_id), exchange_segment, instrument, str(interval), oi
        )
        start_d = self._to_date(from_date)
        end_d = self._to_date(to_date)
        if start_d is None or end_d is None:
            return pd.DataFrame()

        cached = load_df(cache_name)
        stitched = cached.copy() if cached is not None and not cached.empty else None

        if (
            stitched is not None
            and not stitched.empty
            and "timestamp" in stitched.columns
        ):
            stitched["timestamp"] = pd.to_datetime(stitched["timestamp"], utc=True)
            earliest = stitched["timestamp"].dt.date.min()
            latest = stitched["timestamp"].dt.date.max()
            if (
                pd.notna(earliest)
                and pd.notna(latest)
                and earliest <= start_d
                and latest >= end_d
            ):
                out = stitched[
                    (stitched["timestamp"].dt.date >= start_d)
                    & (stitched["timestamp"].dt.date <= end_d)
                ].copy()
                return out.reset_index(drop=True)

        cache_earliest = (
            stitched["timestamp"].dt.date.min()
            if stitched is not None
            and not stitched.empty
            and "timestamp" in stitched.columns
            else None
        )
        if (
            cache_earliest is None
            or pd.isna(cache_earliest)
            or start_d < cache_earliest
        ):
            fetch_end_d = (
                (cache_earliest - timedelta(days=1))
                if cache_earliest is not None and pd.notna(cache_earliest)
                else end_d
            )
            fetch_end_str = (
                fetch_end_d.strftime("%Y-%m-%d")
                if hasattr(fetch_end_d, "strftime")
                else str(fetch_end_d)
            )
            fetch_start_str = (
                start_d.strftime("%Y-%m-%d")
                if hasattr(start_d, "strftime")
                else str(start_d)
            )
            before = self._fetch_futures_intraday(
                security_id,
                exchange_segment,
                instrument,
                interval,
                fetch_start_str,
                fetch_end_str,
                oi,
            )
            if not before.empty:
                stitched = (
                    pd.concat([before, stitched], ignore_index=True)
                    if stitched is not None and not stitched.empty
                    else before
                )
            elif stitched is None:
                stitched = before

        if (
            stitched is not None
            and not stitched.empty
            and "timestamp" in stitched.columns
        ):
            stitched["timestamp"] = pd.to_datetime(stitched["timestamp"], utc=True)
        cache_latest = (
            stitched["timestamp"].dt.date.max()
            if stitched is not None and not stitched.empty
            else None
        )
        if cache_latest is not None and pd.notna(cache_latest) and end_d > cache_latest:
            fetch_start_d = stitched["timestamp"].dt.date.max() + timedelta(days=1)
            fetch_start_str = (
                fetch_start_d.strftime("%Y-%m-%d")
                if hasattr(fetch_start_d, "strftime")
                else str(fetch_start_d)
            )
            fetch_end_str = (
                end_d.strftime("%Y-%m-%d") if hasattr(end_d, "strftime") else str(end_d)
            )
            after = self._fetch_futures_intraday(
                security_id,
                exchange_segment,
                instrument,
                interval,
                fetch_start_str,
                fetch_end_str,
                oi,
            )
            if not after.empty:
                stitched = pd.concat([stitched, after], ignore_index=True)

        if stitched is None or stitched.empty:
            return pd.DataFrame()
        stitched["timestamp"] = pd.to_datetime(stitched["timestamp"], utc=True)
        stitched = (
            stitched.sort_values("timestamp")
            .drop_duplicates(subset=["timestamp"])
            .reset_index(drop=True)
        )
        save_df(cache_name, stitched)
        out = stitched[
            (stitched["timestamp"].dt.date >= start_d)
            & (stitched["timestamp"].dt.date <= end_d)
        ].copy()
        return out.reset_index(drop=True)

    # -------------------------------------------------------------------------
    # Data: Expiries
    # -------------------------------------------------------------------------
    def get_live_expiry(self, symbol, exchange):
        """Live expiry list from Dhan. Returns list (format from API, typically dates/indices)."""
        return self.tsl.get_expiry_list(Underlying=symbol, exchange=exchange)

    # -------------------------------------------------------------------------
    # Data: Option chain (live)
    # -------------------------------------------------------------------------
    def filter_monthly_expiries(self,expiries):
        monthly = {}

        for e in expiries:
            d = datetime.strptime(e, "%Y-%m-%d")
            key = (d.year, d.month)

            # Always keep the latest date in that month
            if key not in monthly or e > monthly[key]:
                monthly[key] = e

        return sorted(monthly.values())

    def get_live_option_chain(
        self,
        symbol,
        exchange,
        expiry_index,
        strikes_around_atm,
        expiry_flag,
        expiry_date=None,
        expiry_match_same_month: bool = False,
    ):
        """
        Engine-friendly option chain.

        ``expiry_index`` indexes into the sorted expiry list when ``expiry_date`` is None.
        When ``expiry_date`` is set (e.g. LEAPS QUARTERLY calendar expiry), that date is
        resolved to the matching list index instead of treating ``expiry_index`` as a slot.
        """
        expiries = self.tsl.get_expiry_list(Underlying=symbol, exchange=exchange)
        if expiry_flag == "MONTH":
            expiries = self.filter_monthly_expiries(expiries)

        expiries = sorted(expiries)

        if not expiries:
            logger.warning(
                "get_live_option_chain: no expiries for symbol=%s exchange=%s expiry_flag=%s",
                symbol,
                exchange,
                expiry_flag,
            )
            return None

        if expiry_date is not None:
            target = ExpiryResolver.as_calendar_date(expiry_date)
            if expiry_match_same_month:
                ei = ExpiryResolver.index_in_expiry_list_same_month(expiries, expiry_date)
                if ei is None:
                    logger.warning(
                        "get_live_option_chain: no expiry in %04d-%02d for target=%s "
                        "(symbol=%s exchange=%s list=%s)",
                        target.year,
                        target.month,
                        target,
                        symbol,
                        exchange,
                        expiries,
                    )
                    return None
            else:
                ei = ExpiryResolver.index_in_expiry_list(expiries, expiry_date)
            resolved = ExpiryResolver.as_calendar_date(expiries[ei])
            if resolved != target:
                if expiry_match_same_month and (
                    resolved.year == target.year and resolved.month == target.month
                ):
                    logger.info(
                        "get_live_option_chain: expiry_date=%s matched same-month list[%s]=%s "
                        "(symbol=%s exchange=%s)",
                        target,
                        ei,
                        resolved,
                        symbol,
                        exchange,
                    )
                else:
                    logger.warning(
                        "get_live_option_chain: expiry_date=%s resolved to list[%s]=%s "
                        "(symbol=%s exchange=%s)",
                        target,
                        ei,
                        resolved,
                        symbol,
                        exchange,
                    )
        else:
            ei = int(expiry_index) if expiry_index is not None else 0
            if ei < 0:
                ei = 0
            if ei >= len(expiries):
                logger.warning(
                    "get_live_option_chain: expiry_index=%s out of range len=%s; "
                    "clamping to %s (symbol=%s exchange=%s)",
                    ei,
                    len(expiries),
                    len(expiries) - 1,
                    symbol,
                    exchange,
                )
                ei = len(expiries) - 1
        expiry = expiries[ei]
        if hasattr(expiry, "strftime"):
            expiry_date = expiry
        else:
            expiry_date = pd.to_datetime(expiry)
            if hasattr(expiry_date, "date"):
                expiry_date = expiry_date.date()
            else:
                expiry_date = pd.Timestamp(expiry_date).date()
        try:
            result = self.tsl.get_option_chain(
                Underlying=symbol,
                exchange=exchange,
                expiry=expiry_date,
                num_strikes=strikes_around_atm,
            )
        except Exception:
            return None
        if result is None:
            return None
        atm_strike, df, expiry_str = result
        return {
            "symbol": symbol,
            "exchange": exchange,
            "chain": df,
            "atm_strike": atm_strike,
            "expiry": expiry_str,
        }

    # -------------------------------------------------------------------------
    # Data: Option chain (historical / expired) for backtest
    # -------------------------------------------------------------------------
    @staticmethod
    def _coerce_expired_option_side_df(raw, option_type: str):
        """Pick CALL/CE or PUT/PE frame from DHAN rolling-option API payload."""
        if raw is None:
            return None
        ot = str(option_type or "").upper()
        want_ce = ot in ("CE", "CALL")
        want_pe = ot in ("PUT", "PE")
        if isinstance(raw, dict):
            inner = raw.get("chain")
            if isinstance(inner, pd.DataFrame) and not inner.empty:
                return inner
            if want_ce:
                ce = raw.get("CE") or raw.get("ce")
                if isinstance(ce, pd.DataFrame) and not ce.empty:
                    return ce
            if want_pe:
                pe = raw.get("PE") or raw.get("pe")
                if isinstance(pe, pd.DataFrame) and not pe.empty:
                    return pe
            return None
        if isinstance(raw, pd.DataFrame):
            return raw if not raw.empty else None
        return None

    def get_expired_optionchain(
        self,
        exchange,
        interval,
        expiry_flag,
        expiry_code,
        strike,
        option_type,
        from_date,
        to_date,
        securityId,
        instrument,
        exchangeSegment,
        symbol=None,
        spot_price=None,
    ):
        """
        Backtest option OHLC: prefer CSVs under ``DHAN_EXPIRED_OPTION_CHAIN_ROOT``
        (or ``data/dhan_expired_option_chain/Monthly Options data *``). Same layout as
        ``data/dhan_expired_option_chain/Expired options data.py``.
        """
        trade_dt = self._to_date(from_date)
        if trade_dt is None:
            return None

        cal_exp = ExpiryResolver.dhan_expiry_index_to_date(trade_dt, expiry_code)
        ec = ExpiryResolver.coerce_to_dhan_expiry_index(
            pd.Timestamp(from_date), expiry_code
        )
        sym = (symbol or "NIFTY").upper()
        sp = float(spot_price or 0.0)
        strikes = strike if isinstance(strike, (list, tuple)) else [strike]

        root = default_expired_option_chain_root()
        df = load_expired_option_chain_from_files(
            symbol=sym,
            calendar_expiry=cal_exp,
            strikes=strikes,
            option_type=option_type,
            spot_price=sp,
            from_date=from_date,
            to_date=to_date,
            root=root,
            strike_step=50,
        )
        
        if df is not None and not df.empty:
            print(">> returned data from expired dhan options files")
            return df
        
        labels = strikes_to_atm_folder_labels(strikes, sp, strike_step=50)
        if not labels:
            labels = ["ATM"]

        interval_arg = (
            int(interval)
            if isinstance(interval, str) and interval.isdigit()
            else interval
        )
        frames = []
        try:
            for strike_arg in labels:
                raw = self.tsl.get_expired_option_data(
                    exchangeSegment=exchangeSegment,
                    instrument=instrument,
                    fromDate=from_date,
                    toDate=to_date,
                    exchange=exchange,
                    interval=interval_arg,
                    securityId=securityId,
                    expiry_flag=expiry_flag,
                    expiry_code=int(ec),
                    strike=strike_arg,
                    option_type=option_type,
                )
                side = self._coerce_expired_option_side_df(raw, option_type)
                if side is not None and not side.empty:
                    frames.append(side)
            if frames:
                out = pd.concat(frames, ignore_index=True)
                out = out.sort_values("datetime").reset_index(drop=True)
                print(">> returned data from api")
                return out
            logger.warning(
                "Dhan expired option chain API returned no rows for %s %s labels=%s",
                sym,
                from_date,
                labels,
            )
            return None
        except Exception as e:
            logger.warning("Dhan expired option chain API fallback failed: %s", e)
            return None

    # -------------------------------------------------------------------------
    # Data: Strike helpers (for strategy building)
    # -------------------------------------------------------------------------
    def get_atm_options(self, symbol, expiry_index=0):
        ce, pe, strike = self.tsl.ATM_Strike_Selection(symbol, expiry_index)
        return {"ce": ce, "pe": pe, "strike": strike}

    def get_otm_options(self, symbol, expiry_index=0, distance=1):
        ce, pe, ce_strike, pe_strike = self.tsl.OTM_Strike_Selection(
            symbol, expiry_index, distance
        )
        return {"ce": ce, "pe": pe, "ce_strike": ce_strike, "pe_strike": pe_strike}

    def get_itm_options(self, symbol, expiry_index=0, distance=1):
        ce, pe, ce_strike, pe_strike = self.tsl.ITM_Strike_Selection(
            symbol, expiry_index, distance
        )
        return {"ce": ce, "pe": pe, "ce_strike": ce_strike, "pe_strike": pe_strike}

    def get_ltp_data(self, names, debug="NO"):
        """LTP for one or more symbols. Returns dict { symbol: values }."""
        return self.tsl.get_ltp_data(names, debug)

    def get_quote_data(self, names, debug="NO"):
        """Quote (bid/ask etc.) for symbols."""
        return self.tsl.get_quote_data(names, debug)

    # -------------------------------------------------------------------------
    # Dhan v2 Market Quote API – use when you have segment + security IDs
    # -------------------------------------------------------------------------
    def get_ltp_v2(self, instruments):
        """
        LTP via v2 /marketfeed/ltp. instruments: { "NSE_EQ": [11536], "NSE_FNO": [49081], ... }.
        Returns raw API response; use parse_ltp_response() for { sec_id: last_price }.
        """
        r = self._marketfeed.ltp(instruments)
        return r

    def get_ohlc_v2(self, instruments):
        """
        OHLC + LTP via v2 /marketfeed/ohlc. instruments: { "NSE_EQ": [11536], ... }.
        Returns raw API response; use parse_ohlc_response() for { sec_id: { last_price, open, high, low, close } }.
        """
        return self._marketfeed.ohlc(instruments)

    def get_quote_v2(self, instruments):
        """
        Full quote (depth, OHLC, OI, volume) via v2 /marketfeed/quote.
        Returns raw API response; use parse_quote_response() for flattened dict.
        """
        return self._marketfeed.quote(instruments)

    # -------------------------------------------------------------------------
    # Data: NSE (historical option chain / expiries)
    # -------------------------------------------------------------------------
    def get_nse_expiries(self, symbol, year, instrument="OPTIDX"):
        key = (symbol, year, instrument)
        if key not in self.expiry_cache:
            self.expiry_cache[key] = self.nse_client.get_expiries(
                symbol, year, instrument
            )
        return self.expiry_cache[key]

    def get_nse_optionchain_historical(
        self,
        symbol,
        from_date,
        expiry_date,
        instrumentType,
        spot_price,
        option_type,
        strikes,
    ):
        records = []
        for strike in strikes:
            try:
                hist = self.nse_client.get_options_history(
                    symbol=symbol,
                    from_date=(
                        from_date.strftime("%Y-%m-%d")
                        if hasattr(from_date, "strftime")
                        else from_date
                    ),
                    to_date=(
                        expiry_date.strftime("%Y-%m-%d")
                        if hasattr(expiry_date, "strftime")
                        else expiry_date
                    ),
                    instrumentType=instrumentType,
                    expiry_date=(
                        expiry_date.strftime("%Y-%m-%d")
                        if hasattr(expiry_date, "strftime")
                        else str(expiry_date)
                    ),
                    strike=int(float(strike)),
                    option_type=option_type,
                    year=(
                        expiry_date.year
                        if hasattr(expiry_date, "year")
                        else pd.Timestamp(expiry_date).year
                    ),
                )
                if not hist:
                    continue
                row = hist[0]
                records.append(
                    {
                        "Strike Price": strike,
                        f"{option_type} LTP": row.get("FH_LAST_TRADED_PRICE", 0),
                    }
                )
            except Exception:
                continue
        if not records:
            return None
        oc_df = (
            pd.DataFrame(records)
            .groupby("Strike Price")
            .first()
            .reset_index()
            .sort_values("Strike Price")
        )
        return {"symbol": symbol, "exchange": "OPTIDX", "chain": oc_df}

    # -------------------------------------------------------------------------
    # Orders & positions (for broker layer only)
    # -------------------------------------------------------------------------
    def get_positions(self, debug="NO"):
        return self.tsl.get_positions(debug=debug)

    def get_order_by_id(self, order_id: str):
        """Fetch a single order by broker order id (no tradehull status-poll sleep)."""
        oid = str(order_id or "").strip()
        if not oid:
            return None
        try:
            response = self.tsl.Dhan.get_order_by_id(oid)
            if isinstance(response, dict) and response.get("status") == "success":
                data = response.get("data")
                if isinstance(data, list) and data:
                    return data[0]
                if isinstance(data, dict):
                    return data
            http = self.tsl._get_dhan_http()
            if http is not None:
                parsed = http.get(f"/orders/{oid}")
                if isinstance(parsed, dict) and parsed.get("status") == "success":
                    data = parsed.get("data")
                    if isinstance(data, list) and data:
                        return data[0]
                    if isinstance(data, dict):
                        return data
        except Exception as exc:
            logger.warning("Dhan get_order_by_id failed order_id=%s: %s", oid, exc)
        return None

    def get_order_list(self):
        """Order list for idempotency / lookup. Uses Tradehull get_orderbook."""
        try:
            ob = self.tsl.get_orderbook(debug="NO")
            if ob is None:
                return []
            if isinstance(ob, pd.DataFrame):
                return ob.to_dict("records") if not ob.empty else []
            if isinstance(ob, dict) and ob.get("status") == "failure":
                return []
            if isinstance(ob, dict) and "data" in ob:
                return ob["data"] if isinstance(ob["data"], list) else []
            return []
        except Exception:
            return []

    def get_fills(self, page_size=50):
        """
        Filled orders as trade-led OMS fills. Derived from order list (status TRADED/filled/complete).
        Returns list of dicts: id, order_id, client_order_id, tag, price, size, side.
        """
        try:
            orders = self.get_order_list()
            if not orders:
                return []
            filled_statuses = {"traded", "filled", "complete", "completed"}
            out = []
            for o in orders[: page_size * 2]:
                status = (o.get("orderStatus") or o.get("status") or "").strip().lower()
                if status not in filled_statuses:
                    continue
                order_id = str(o.get("orderId") or o.get("order_id") or "")
                tag = o.get("tag") or o.get("intent_id") or ""
                price = float(o.get("averageTradedPrice") or o.get("AvgTradedPrice") or o.get("average_traded_price") or 0)
                size = int(o.get("TradedQty") or o.get("tradedQty") or o.get("quantity") or o.get("Quantity") or 0)
                side = (o.get("transactionType") or o.get("transaction_type") or o.get("side") or "BUY").upper()
                if not order_id or size <= 0:
                    continue
                out.append({
                    "id": order_id,
                    "order_id": order_id,
                    "client_order_id": tag,
                    "tag": tag,
                    "price": price,
                    "size": size,
                    "side": side,
                })
                if len(out) >= page_size:
                    break
            return out
        except Exception:
            return []

    def place_order(
        self,
        tradingsymbol,
        exchange,
        quantity,
        price=0,
        trigger_price=0,
        order_type="MARKET",
        transaction_type="BUY",
        trade_type="MARGIN",
        disclosed_quantity=0,
        after_market_order=False,
        validity="DAY",
        amo_time="OPEN",
        bo_profit_value=None,
        bo_stop_loss_value=None,
        tag=None,
        correlation_id=None,
    ):
        """
        Place order via Tradehull. Used only by broker layer (DhanBrokerApi).
        Dhan REST maps the same string to JSON ``correlationId`` (via dhanhq ``tag``).
        Pass intent_id as both tag and correlation_id for WS order_alert CorrelationId parity.
        Returns dict with "status" ("success" | "error"), "order_id", and on failure
        "message" + "payload" for OMS/engine logs.
        """
        request_payload = {
            "tradingsymbol": tradingsymbol,
            "exchange": str(exchange).upper(),
            "quantity": int(quantity),
            "price": int(price) if price else 0,
            "trigger_price": int(trigger_price) if trigger_price else 0,
            "order_type": str(order_type).upper(),
            "transaction_type": str(transaction_type).upper(),
            "trade_type": str(trade_type).upper(),
            "disclosed_quantity": int(disclosed_quantity),
            "after_market_order": bool(after_market_order),
            "validity": validity,
            "amo_time": amo_time,
            "tag": tag or "",
            "correlation_id": correlation_id if correlation_id is not None else tag,
        }
        try:
            cid = correlation_id if correlation_id is not None else tag
            logger.info("Dhan place_order request payload=%s", request_payload)
            result = self.tsl.order_placement(
                tradingsymbol=tradingsymbol,
                exchange=exchange.upper(),
                quantity=int(quantity),
                price=int(price) if price else 0,
                trigger_price=int(trigger_price) if trigger_price else 0,
                order_type=order_type.upper(),
                transaction_type=transaction_type.upper(),
                trade_type=trade_type.upper(),
                disclosed_quantity=int(disclosed_quantity),
                after_market_order=bool(after_market_order),
                validity=validity,
                amo_time=amo_time,
                bo_profit_value=bo_profit_value,
                bo_stop_loss_Value=bo_stop_loss_value,
                tag=tag or "",
                correlation_id=cid,
            )
            if result is not None and isinstance(result, str):
                return {"status": "success", "order_id": result, "payload": request_payload}
            from core.broker.internal.dhan.mappings import parse_dhan_api_error

            last_err = getattr(self.tsl, "_last_dhan_api_error", None)
            parsed = parse_dhan_api_error(last_err) if last_err is not None else {}
            display = (
                parsed.get("display_message")
                or "order_placement returned None (see tradehull logs for API response)"
            )
            logger.warning(
                "Dhan place_order returned no order_id payload=%s error=%s",
                request_payload,
                display,
            )
            return {
                "status": "error",
                "order_id": None,
                "message": display,
                "error_code": parsed.get("error_code"),
                "error_type": parsed.get("error_type"),
                "error_message": parsed.get("error_message"),
                "broker_response": last_err,
                "payload": request_payload,
            }
        except Exception as e:
            from core.broker.internal.dhan.mappings import parse_dhan_api_error

            parsed = parse_dhan_api_error(e)
            display = parsed.get("display_message") or str(e)
            logger.warning(
                "Dhan place_order exception payload=%s error=%s",
                request_payload,
                display,
                exc_info=True,
            )
            return {
                "status": "error",
                "order_id": None,
                "message": display,
                "error_code": parsed.get("error_code"),
                "error_type": parsed.get("error_type"),
                "error_message": parsed.get("error_message"),
                "broker_response": (
                    e.args[0] if getattr(e, "args", None) and isinstance(e.args[0], dict) else None
                ),
                "payload": request_payload,
            }

    def cancel_order(self, order_id):
        """Cancel a single order."""
        return self.tsl.cancel_order(order_id)

    def place_forever_order(
        self,
        tradingsymbol,
        exchange,
        quantity,
        price=0,
        trigger_price=0,
        order_type="LIMIT",
        transaction_type="BUY",
        trade_type="MARGIN",
        order_flag="SINGLE",
        disclosed_quantity=0,
        validity="DAY",
        tag=None,
        correlation_id=None,
    ):
        """Place Dhan Forever (GTT) order. Returns same shape as place_order."""
        request_payload = {
            "tradingsymbol": tradingsymbol,
            "exchange": str(exchange).upper(),
            "quantity": int(quantity),
            "price": float(price),
            "trigger_price": float(trigger_price),
            "order_type": str(order_type).upper(),
            "transaction_type": str(transaction_type).upper(),
            "trade_type": str(trade_type).upper(),
            "order_flag": str(order_flag or "SINGLE").upper(),
            "disclosed_quantity": int(disclosed_quantity),
            "validity": validity,
            "tag": tag or "",
            "correlation_id": correlation_id if correlation_id is not None else tag,
        }
        try:
            cid = correlation_id if correlation_id is not None else tag
            logger.info("Dhan place_forever_order request payload=%s", request_payload)
            result = self.tsl.forever_order_placement(
                tradingsymbol=tradingsymbol,
                exchange=exchange.upper(),
                quantity=int(quantity),
                price=float(price),
                trigger_price=float(trigger_price),
                order_type=order_type.upper(),
                transaction_type=transaction_type.upper(),
                trade_type=trade_type.upper(),
                order_flag=str(order_flag or "SINGLE").upper(),
                disclosed_quantity=int(disclosed_quantity),
                validity=validity,
                tag=tag or "",
                correlation_id=cid,
            )
            if result is not None and isinstance(result, str):
                return {"status": "success", "order_id": result, "payload": request_payload}
            from core.broker.internal.dhan.mappings import parse_dhan_api_error

            last_err = getattr(self.tsl, "_last_dhan_api_error", None)
            parsed = parse_dhan_api_error(last_err) if last_err is not None else {}
            display = (
                parsed.get("display_message")
                or "forever_order_placement returned None (see tradehull logs)"
            )
            logger.warning(
                "Dhan place_forever_order returned no order_id payload=%s error=%s",
                request_payload,
                display,
            )
            return {
                "status": "error",
                "order_id": None,
                "message": display,
                "error_code": parsed.get("error_code"),
                "error_type": parsed.get("error_type"),
                "error_message": parsed.get("error_message"),
                "broker_response": last_err,
                "payload": request_payload,
            }
        except Exception as e:
            from core.broker.internal.dhan.mappings import parse_dhan_api_error

            parsed = parse_dhan_api_error(e)
            display = parsed.get("display_message") or str(e)
            logger.warning(
                "Dhan place_forever_order exception payload=%s error=%s",
                request_payload,
                display,
                exc_info=True,
            )
            return {
                "status": "error",
                "order_id": None,
                "message": display,
                "error_code": parsed.get("error_code"),
                "error_type": parsed.get("error_type"),
                "error_message": parsed.get("error_message"),
                "broker_response": (
                    e.args[0] if getattr(e, "args", None) and isinstance(e.args[0], dict) else None
                ),
                "payload": request_payload,
            }

    def cancel_forever_order(self, order_id):
        """Cancel a pending Forever (GTT) order."""
        return self.tsl.cancel_forever_order(order_id)

    def get_forever_orders(self):
        """List all Forever (GTT) orders."""
        return self.tsl.get_forever_orders()

    def get_order_detail(self, order_id, debug="NO"):
        """Single order detail."""
        return getattr(self.tsl, "get_order_detail", lambda *a, **k: None)(
            order_id, debug
        )

    def get_holdings(self, debug="NO"):
        return self.tsl.get_holdings(debug=debug)

    def get_balance(self):
        return self.tsl.get_balance()

    def get_live_pnl(self):
        return self.tsl.get_live_pnl()
