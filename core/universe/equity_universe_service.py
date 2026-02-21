"""
Equity universe service: loads NSE equity list from EQUITY_L (daily sync).
Source: data_cache/EQUITY_L_latest.csv. Listing date from NSE; IPO = (today - listing_date) <= days.
No Dhan instrument CSV for universe. Broker used only for order execution, LTP, positions.
"""

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import pdb

from core.universe.models import EquityMeta
from core.universe.nse_master_downloader import NseMasterDownloader
from core.universe.stock_filter_engine import StockFilterEngine

logger = logging.getLogger(__name__)

# DATE OF LISTING format in NSE file: 06-Oct-08
LISTING_DATE_FMT = "%d-%b-%Y"


def _parse_nse_equity_l(csv_path: Path) -> List[EquityMeta]:
    """
    Parse data_cache/EQUITY_L_latest.csv. Include only SERIES == "EQ".
    Extract: symbol=SYMBOL, listing_date=DATE OF LISTING (%d-%b-%y), isin=ISIN NUMBER, market_lot=MARKET LOT.
    """
    import csv

    if not csv_path.exists():
        raise FileNotFoundError(f"NSE equity file not found: {csv_path}")
    out: List[EquityMeta] = []
    with open(csv_path, "r", encoding="utf-8", newline="", errors="replace") as f:
        reader = csv.DictReader(f, skipinitialspace=True)
        for row in reader:
            series = (row.get("SERIES") or "").strip().upper()
            if series != "EQ":
                continue
            sym = (row.get("SYMBOL") or "").strip()
            if not sym:
                continue
            listing_date = None
            raw = (row.get("DATE OF LISTING") or "").strip()
            if raw:
                try:
                    listing_date = datetime.strptime(raw, LISTING_DATE_FMT).date()
                except ValueError:
                    pass
            isin = (row.get("ISIN NUMBER") or "").strip() or None
            market_lot = None
            try:
                ml = row.get("MARKET LOT") or row.get("MARKET LOT ") or ""
                if ml:
                    market_lot = int(float(ml))
            except (ValueError, TypeError):
                pass
            out.append(
                EquityMeta(
                    symbol=sym,
                    listing_date=listing_date,
                    isin=isin,
                    market_lot=market_lot,
                    security_id=None,
                )
            )
    return out


class EquityUniverseService:
    """
    Loads equity universe from NSE EQUITY_L (data_cache/EQUITY_L_latest.csv).
    At startup: if file missing, attempt download; if download fails, log and run with empty universe.
    IPO = (today - listing_date).days <= days. No file I/O inside on_candle. DHAN only.
    """

    def __init__(
        self,
        cache_dir: Path,
        data_provider: Any,
        instrument_store: Optional[Any] = None,
        engine_logger: Optional[Any] = None,
    ):
        """
        Args:
            cache_dir: Path to data_cache/ (EQUITY_L_latest.csv lives here)
            data_provider: DhanDataProvider (for filter engine)
            instrument_store: Optional Dhan instrument store for symbol->security_id (LTP/quote API)
            engine_logger: Optional EngineLogger for structured logs
        """
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._engine_logger = engine_logger
        self._data_provider = data_provider
        self._instrument_store = instrument_store
        self._downloader = NseMasterDownloader(self._cache_dir)
        self._filter_engine = StockFilterEngine(
            data_provider=data_provider,
            segment="NSE_EQ",
            engine_logger=engine_logger,
        )
        self.all_equities: Dict[str, EquityMeta] = {}
        try:
            self._load()
        except Exception as e:
            self._log("universe_load_error", error=str(e))
            logger.error("Universe failed to load: %s", e)

    def _log(self, event: str, **kwargs: Any) -> None:
        if self._engine_logger and hasattr(self._engine_logger, "log"):
            self._engine_logger.log(event, **kwargs)
        else:
            logger.info(event, extra=kwargs)

    def _load(self) -> None:
        """Load from EQUITY_L_latest.csv; if missing, try download. Do not call from strategy loop."""
        latest_path = self._cache_dir / "EQUITY_L_latest.csv"
        if not latest_path.exists():
            downloaded = self._downloader.ensure_latest()
            if not downloaded:
                self._log(
                    "universe_load_error", error="NSE file missing and download failed"
                )
                return
        try:
            meta_list = _parse_nse_equity_l(latest_path)
        except FileNotFoundError as e:
            self._log("universe_load_error", error=str(e), path=str(latest_path))
            return
        self.all_equities = {m.symbol: m for m in meta_list}
        self._log("universe_loaded", count=len(self.all_equities))

    def get_all_equities(self) -> List[str]:
        """Return list of all equity symbols."""
        return list(self.all_equities.keys())

    def get_ipo_equities(
        self,
        days: int = 365,
        as_of: Optional[Union[date, datetime]] = None,
    ) -> List[str]:

        if as_of is None:
            as_of = datetime.now().date()
        elif isinstance(as_of, datetime):
            as_of = as_of.date()

        filtered = []

        for sym, meta in self.all_equities.items():
            if meta.listing_date is None:
                continue

            ld = (
                meta.listing_date.date()
                if hasattr(meta.listing_date, "date")
                else meta.listing_date
            )

            age = (as_of - ld).days

            if age <= days:
                filtered.append((sym, ld))

        # 🔥 Sort by listing_date descending (newest first)
        filtered.sort(key=lambda x: x[1], reverse=True)
        return [sym for sym, _ in filtered]

    def get_listing_days(
        self, symbol: str, as_of_date: Optional[Union[date, datetime]] = None
    ) -> Optional[int]:
        """
        Days since listing for symbol. None if unknown or not in universe.
        Pure in-memory lookup: equity master is cached at load; no IO, no CSV reads.

        Use in strategy for lazy per-symbol IPO window (e.g. 30–90 days, 180–365 base).
        Pass as_of_date in backtest (e.g. candle["timestamp"]) for deterministic results;
        omit for live (uses today).
        """
        meta = self.all_equities.get(symbol)
        if not meta or meta.listing_date is None:
            return None
        ld = (
            meta.listing_date.date()
            if hasattr(meta.listing_date, "date")
            else meta.listing_date
        )
        if as_of_date is None:
            ref = datetime.now().date()
        else:
            ref = as_of_date.date() if isinstance(as_of_date, datetime) else as_of_date
        return (ref - ld).days

    def refresh_universe(self) -> None:
        """Re-download if needed and reload from EQUITY_L_latest.csv."""
        self._downloader.download()
        self._load()

    @property
    def filter_engine(self) -> StockFilterEngine:  # uses stock filter engine
        return self._filter_engine

    def get_meta_for_symbols(self, symbols: List[str]) -> Dict[str, EquityMeta]:
        """Return { symbol: EquityMeta } for symbols that exist in universe."""
        return {s: self.all_equities[s] for s in symbols if s in self.all_equities}

    def schedule_daily_refresh(self, hour: int = 20) -> None:
        """
        Optional: schedule refresh (e.g. hour=20 after market close).
        Call from scheduler or cron; not run inside engine loop.
        """
        self.refresh_universe()

    def build_instruments_by_segment(self, symbols: List[str]) -> Dict[str, List[int]]:
        """
        Build { 'NSE_EQ': [security_id, ...] } for v2 API using broker instrument store.
        Only used for LTP/quote retrieval; universe itself is from NSE. Returns {} if no instrument_store.
        """
        if not self._instrument_store or not hasattr(
            self._instrument_store, "get_feed_instruments"
        ):
            return {}
        try:
            instruments = self._instrument_store.get_feed_instruments(symbols)
        except Exception:
            return {}
        if not instruments:
            return {}
        ids: List[int] = []
        for item in instruments:
            if item.get("symbol") in self.all_equities:
                try:
                    ids.append(int(item["SecurityId"]))
                except (KeyError, ValueError, TypeError):
                    pass
        return {"NSE_EQ": ids} if ids else {}

    def get_security_id_to_symbol(self, symbols: List[str]) -> Dict[str, str]:
        """Build { security_id_str: symbol } for given symbols using broker instrument store (for filter/quote)."""
        if not self._instrument_store or not hasattr(
            self._instrument_store, "get_feed_instruments"
        ):
            return {}
        try:
            instruments = self._instrument_store.get_feed_instruments(symbols)
        except Exception:
            return {}
        return {
            str(item["SecurityId"]): item["symbol"]
            for item in instruments
            if item.get("SecurityId") is not None and item.get("symbol") is not None
        }
