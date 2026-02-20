"""
IPO tracker: maintains data_cache/ipo_stocks.json, detects new listings,
exposes get_recent_ipos(days). Uses datetime arithmetic.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

IPO_DB_FILENAME = "ipo_stocks.json"


class IpoTracker:
    """
    Maintains data_cache/ipo_stocks.json: { "symbol": "listing_date_iso" }.
    On refresh: compare current symbols vs stored; new symbols get listing_date = today;
    entries older than 365 days are removed. Uses datetime arithmetic.
    """

    def __init__(self, cache_dir: Path):
        self._cache_dir = Path(cache_dir)
        self._db_path = self._cache_dir / IPO_DB_FILENAME
        self._ipo_listing_dates: dict = {}  # symbol -> date (date object)
        self._load_or_create()

    def _load_or_create(self) -> None:
        """Load JSON from disk; create file if missing."""
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        if not self._db_path.exists():
            self._ipo_listing_dates = {}
            self._save()
            logger.info("ipo_db_created path=%s", self._db_path)
            return
        try:
            with open(self._db_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for sym, date_str in raw.items():
                if date_str:
                    try:
                        self._ipo_listing_dates[sym] = datetime.fromisoformat(
                            date_str.replace("Z", "+00:00")
                        ).date()
                    except Exception:
                        self._ipo_listing_dates[sym] = datetime.now().date()
                else:
                    self._ipo_listing_dates[sym] = datetime.now().date()
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("ipo_db_load_failed", extra={"path": str(self._db_path), "error": str(e)})
            self._ipo_listing_dates = {}

    def _save(self) -> None:
        data = {
            sym: d.isoformat() if hasattr(d, "isoformat") else str(d)
            for sym, d in self._ipo_listing_dates.items()
        }
        with open(self._db_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=0)

    def get_recent_ipos(self, days: int = 365) -> List[str]:
        """Return symbols listed in the last `days` days. Uses datetime arithmetic."""
        if days <= 0:
            return []
        cutoff = datetime.now().date() - timedelta(days=days)
        return [
            sym
            for sym, listing_date in self._ipo_listing_dates.items()
            if listing_date >= cutoff
        ]

    def refresh(self, current_equity_symbols: List[str]) -> List[str]:
        """
        Compare current_equity_symbols with stored IPO DB. New symbols get listing_date = today;
        remove entries older than 365 days. Persist and return list of newly detected symbols.
        """
        now = datetime.now().date()
        cutoff_365 = now - timedelta(days=365)
        current_set = set(current_equity_symbols)
        new_listings: List[str] = []

        # New symbols not in DB -> add with listing_date = today
        for sym in current_set:
            if sym not in self._ipo_listing_dates:
                self._ipo_listing_dates[sym] = now
                new_listings.append(sym)

        # Remove symbols older than 365 days
        to_remove = [
            sym
            for sym, listing_date in self._ipo_listing_dates.items()
            if listing_date < cutoff_365
        ]
        for sym in to_remove:
            del self._ipo_listing_dates[sym]

        self._save()
        if new_listings:
            logger.info("new_listing_detected symbols=%s listing_date=%s", new_listings, now.isoformat())
        logger.info("ipo_db_updated total=%s removed_old=%s", len(self._ipo_listing_dates), len(to_remove))
        return new_listings

    def get_listing_date(self, symbol: str):
        """Return listing_date (date) for symbol, or None."""
        return self._ipo_listing_dates.get(symbol)
