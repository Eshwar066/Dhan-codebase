"""
Delta Exchange broker: instrument loading (API) and lookup logic.
Product id / symbol, Delta API schema, backtest dummy rows.
"""

import logging
from pathlib import Path
from datetime import datetime
from threading import Lock
from typing import Optional

import pandas as pd
import pdb

logger = logging.getLogger(__name__)
import requests
from run.config import RUN_MODE, RunMode

from .base import BaseInstrumentStore, Instrument


def fetch_delta_products(
    base_url: str = "https://api.india.delta.exchange",
) -> pd.DataFrame:
    """Fetch product list from Delta /v2/products. Returns raw result as DataFrame."""
    r = requests.get(f"{base_url.rstrip('/')}/v2/products", timeout=30)
    r.raise_for_status()
    data = r.json()
    result = data.get("result", data) if isinstance(data, dict) else data
    return pd.DataFrame(result) if result else pd.DataFrame()


class DeltaInstrumentProvider:
    """Load Delta Exchange product list from API or from cache CSV in Dependencies."""

    DEFAULT_BASE_URL = "https://api.india.delta.exchange"

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")

    def fetch_products(self) -> pd.DataFrame:
        return fetch_delta_products(self.base_url)

    def load(self) -> pd.DataFrame:
        return self.fetch_products()


class DeltaInstrumentStore(BaseInstrumentStore):
    """Instrument store for Delta: product id/symbol lookup, Delta-specific backtest dummies. Uses Dependencies cache when cache_path is set."""

    dummy_security_counter = 100000

    def __init__(
        self,
        base_url: Optional[str] = None,
        cache_path: Optional[Path] = None,
    ):
        cache = Path(cache_path).resolve() if cache_path else None
        self.cache_path = cache
        self._provider = DeltaInstrumentProvider(base_url)
        self._refresh_lock = Lock()
        today = datetime.now().date()
        cache_stale = False
        if cache and cache.exists():
            try:
                mtime = cache.stat().st_mtime
                cache_date = datetime.fromtimestamp(mtime).date()
                if cache_date < today:
                    cache_stale = True
            except OSError:
                cache_stale = True
        if cache and cache.exists() and not cache_stale:
            self.df = pd.read_csv(cache, low_memory=False)
        else:
            self.df = self._provider.load()
            if cache and not self.df.empty:
                cache.parent.mkdir(parents=True, exist_ok=True)
                # Remove previous Delta instrument files so only the new one remains
                for old in cache.parent.glob("delta_instrument_*.csv"):
                    try:
                        old.unlink()
                    except OSError:
                        pass
                self.df.to_csv(cache, index=False, float_format="%.2f")
        self._rebuild_symbol_lookup()

    def _rebuild_symbol_lookup(self) -> None:
        """Rebuild symbol/product-id lookups after loading or refreshing products."""
        self._symbol_to_row = {}
        if not self.df.empty and "symbol" in self.df.columns:
            for _, row in self.df.iterrows():
                sym = row.get("symbol") or row.get("short_name", "")
                self._symbol_to_row[str(sym).upper()] = row
                pid = row.get("id")
                if pid is not None:
                    self._symbol_to_row[str(pid)] = row
                    num = pd.to_numeric(pid, errors="coerce")
                    if pd.notna(num):
                        try:
                            self._symbol_to_row[str(int(num))] = row
                        except (ValueError, OverflowError):
                            pass

    def refresh_products(self) -> bool:
        """Redownload products, atomically replace cache, and rebuild lookup."""
        with self._refresh_lock:
            try:
                refreshed = self._provider.load()
                if refreshed.empty or "symbol" not in refreshed.columns:
                    logger.warning(
                        "Delta instrument refresh returned no usable products"
                    )
                    return False
                if self.cache_path is not None:
                    self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                    tmp = self.cache_path.with_suffix(
                        self.cache_path.suffix + ".tmp"
                    )
                    refreshed.to_csv(tmp, index=False, float_format="%.2f")
                    tmp.replace(self.cache_path)
                self.df = refreshed
                self._rebuild_symbol_lookup()
                logger.info(
                    "Refreshed Delta instrument master (%s products)",
                    len(refreshed),
                )
                return True
            except Exception:
                logger.exception("Failed to refresh Delta instrument master")
                return False

    def _row_for_contract_key(self, trading_symbol) -> Optional[pd.Series]:
        """Resolve CSV row by contract symbol or numeric product id (string)."""
        if trading_symbol is None:
            return None
        s = str(trading_symbol).strip()
        if not s:
            return None
        row = self._symbol_to_row.get(s.upper())
        if row is not None:
            return row
        num = pd.to_numeric(s, errors="coerce")
        if pd.notna(num):
            try:
                return self._symbol_to_row.get(str(int(num)))
            except (ValueError, OverflowError):
                pass
        return None

    def get_tick_size(self, symbol: str) -> Optional[float]:
        """Return tick size for symbol from product data; None if not found."""
        key = str(symbol).upper()
        row = self._symbol_to_row.get(key)
        if row is not None:
            tick = row.get("tick_size")
            if tick is not None:
                v = pd.to_numeric(tick, errors="coerce")
                return None if pd.isna(v) else float(v)
        row = self._row_for_contract_key(symbol)
        if row is not None:
            tick = row.get("tick_size")
            if tick is not None:
                v = pd.to_numeric(tick, errors="coerce")
                return None if pd.isna(v) else float(v)
        return None

    def get_lot_size(self, symbol: str) -> Optional[int]:
        """Return lot size for symbol from product data; None if not found. Delta often uses 1."""
        key = str(symbol).upper()
        row = self._symbol_to_row.get(key)
        if row is not None:
            lot = row.get("lot_size")
            if lot is not None:
                v = pd.to_numeric(lot, errors="coerce")
                if pd.notna(v) and v >= 1:
                    return int(v)
        row = self._row_for_contract_key(symbol)
        if row is not None:
            lot = row.get("lot_size")
            if lot is not None:
                v = pd.to_numeric(lot, errors="coerce")
                if pd.notna(v) and v >= 1:
                    return int(v)
        return 1

    def _row_to_instrument(self, row: pd.Series) -> Instrument:
        symbol = row.get("symbol") or row.get("short_name", "")
        contract_multiplier = float(
            pd.to_numeric(row.get("contract_value", 1), errors="coerce") or 1
        )
        return Instrument(
            trading_symbol=str(symbol),
            custom_symbol=str(symbol),
            exchange="DELTA",
            segment="D",
            instrument_type=str(row.get("contract_type", "future"))
            .replace("_", "")
            .upper(),
            expiry=row.get("settlement_time") or row.get("expiry_date"),
            strike=(
                pd.to_numeric(row.get("strike_price"), errors="coerce")
                if row.get("strike_price") is not None
                else None
            ),
            option_type=row.get("option_type"),
            lot_size=1,
            contract_multiplier=contract_multiplier,
            instrument_id=row.get("id"),
            series=row.get("series"),
        )

    def intent_creation_details(
        self,
        trading_symbol,
        exchange,
        expiry,
        option_type,
        strike,
        *,
        prefer_monthly: bool = False,
    ) -> Optional[Instrument]:
        row = self._row_for_contract_key(trading_symbol)
        if row is not None:
            return self._row_to_instrument(row)

        if RUN_MODE in (RunMode.LIVE, RunMode.PAPER):
            logger.warning(
                "Delta instrument %s missing; refreshing product master once",
                trading_symbol,
            )
            if self.refresh_products():
                row = self._row_for_contract_key(trading_symbol)
                if row is not None:
                    logger.info(
                        "Delta instrument %s found after refresh", trading_symbol
                    )
                    return self._row_to_instrument(row)
            logger.warning("No Delta instrument found for %s", trading_symbol)
            return None

        DeltaInstrumentStore.dummy_security_counter += 1
        return Instrument(
            trading_symbol=trading_symbol,
            custom_symbol=trading_symbol,
            exchange="DELTA",
            segment="D",
            instrument_type="OP",
            expiry=expiry,
            strike=strike,
            option_type=option_type,
            lot_size=1,
            instrument_id=DeltaInstrumentStore.dummy_security_counter,
            series=None,
        )

    def futures_intent_creation_details(
        self, trading_symbol: str, exchange: str, expiry
    ) -> Optional[Instrument]:
        row = self._row_for_contract_key(trading_symbol)
        if row is not None:
            return self._row_to_instrument(row)

        if RUN_MODE in (RunMode.LIVE, RunMode.PAPER):
            logger.warning(
                "Delta FUT instrument %s missing; refreshing product master once",
                trading_symbol,
            )
            if self.refresh_products():
                row = self._row_for_contract_key(trading_symbol)
                if row is not None:
                    logger.info(
                        "Delta FUT instrument %s found after refresh",
                        trading_symbol,
                    )
                    return self._row_to_instrument(row)
            logger.warning("No Delta FUT instrument found for %s", trading_symbol)
            return None

        DeltaInstrumentStore.dummy_security_counter += 1
        return Instrument(
            trading_symbol=trading_symbol,
            custom_symbol=trading_symbol,
            exchange="DELTA",
            segment="D",
            instrument_type="FUT",
            expiry=expiry,
            strike=None,
            option_type=None,
            lot_size=1,
            instrument_id=DeltaInstrumentStore.dummy_security_counter,
            series="FUT",
        )
