"""
NSE equity master downloader: fetches EQUITY_L.csv once per day,
saves to Dependencies/equity_universe/EQUITY_L_{YYYYMMDD}.csv and EQUITY_L_latest.csv.
No network calls inside strategy execution.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

NSE_EQUITY_L_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
REFERER = "https://www.nseindia.com/"


class NseMasterDownloader:
    """
    Download EQUITY_L.csv once per day. Save as EQUITY_L_{YYYYMMDD}.csv and
    EQUITY_L_latest.csv under the given directory (e.g. Dependencies/equity_universe).
    Uses User-Agent and Referer headers. Errors are logged; does not crash engine.
    """

    def __init__(self, cache_dir: Path):
        """cache_dir: directory for equity universe files (e.g. Dependencies/equity_universe)."""
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _headers(self) -> dict:
        return {
            "User-Agent": USER_AGENT,
            "Referer": REFERER,
        }

    def download(self) -> Optional[Path]:
        """
        Download EQUITY_L.csv; save to EQUITY_L_{YYYYMMDD}.csv and EQUITY_L_latest.csv.
        Returns path to latest file on success, None on failure. Logs nse_master_downloaded
        or nse_master_download_failed.
        """
        try:
            resp = requests.get(NSE_EQUITY_L_URL, headers=self._headers(), timeout=30)
            resp.raise_for_status()
        except Exception as e:
            logger.warning("nse_master_download_failed url=%s error=%s", NSE_EQUITY_L_URL, e)
            return None

        today = datetime.now().strftime("%Y%m%d")
        dated_path = self._cache_dir / f"EQUITY_L_{today}.csv"
        latest_path = self._cache_dir / "EQUITY_L_latest.csv"

        try:
            dated_path.write_text(resp.text, encoding="utf-8")
            latest_path.write_text(resp.text, encoding="utf-8")
        except OSError as e:
            logger.warning("nse_master_download_failed write error=%s path=%s", e, self._cache_dir)
            return None

        logger.info("nse_master_downloaded path=%s", latest_path)
        return latest_path

    def ensure_latest(self) -> Optional[Path]:
        """
        If EQUITY_L_latest.csv is missing or outdated (no file for today), run download.
        Return path to EQUITY_L_latest.csv or None if download failed.
        Directory is typically Dependencies/equity_universe.
        """
        latest_path = self._cache_dir / "EQUITY_L_latest.csv"
        today = datetime.now().strftime("%Y%m%d")
        dated_path = self._cache_dir / f"EQUITY_L_{today}.csv"

        if latest_path.exists() and dated_path.exists():
            return latest_path
        return self.download()
