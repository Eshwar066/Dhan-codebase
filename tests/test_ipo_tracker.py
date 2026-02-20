"""
Minimal unit tests for IpoTracker: new stock detected, older than 365 days removed, JSON updated.
"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from core.universe.ipo_tracker import IpoTracker, IPO_DB_FILENAME


class TestIpoTracker(unittest.TestCase):
    def test_new_stock_detected_and_json_updated(self):
        """Refresh with new symbols: they are detected and persisted to ipo_stocks.json."""
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            tracker = IpoTracker(cache_dir)
            db_path = cache_dir / IPO_DB_FILENAME
            self.assertTrue(db_path.exists())

            new_listings = tracker.refresh(["SYM1", "SYM2"])
            self.assertEqual(set(new_listings), {"SYM1", "SYM2"})
            self.assertIsNotNone(tracker.get_listing_date("SYM1"))
            self.assertEqual(set(tracker.get_recent_ipos(days=365)), {"SYM1", "SYM2"})

            with open(db_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertIn("SYM1", data)
            self.assertIn("SYM2", data)
            self.assertIsInstance(data["SYM1"], str)

    def test_older_than_365_days_removed(self):
        """Entries with listing_date older than 365 days are removed on refresh."""
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            cache_dir.mkdir(parents=True, exist_ok=True)
            db_path = cache_dir / IPO_DB_FILENAME
            old_date = (datetime.now().date() - timedelta(days=400)).isoformat()
            with open(db_path, "w", encoding="utf-8") as f:
                json.dump({"OLDSTOCK": old_date}, f)

            tracker = IpoTracker(cache_dir)
            self.assertIsNotNone(tracker.get_listing_date("OLDSTOCK"))
            self.assertNotIn("OLDSTOCK", tracker.get_recent_ipos(days=365))

            tracker.refresh([])
            self.assertNotIn("OLDSTOCK", tracker._ipo_listing_dates)

            with open(db_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertNotIn("OLDSTOCK", data)

    def test_json_structure(self):
        """IPO file has correct structure: symbol -> listing_date string."""
        with tempfile.TemporaryDirectory() as tmp:
            tracker = IpoTracker(Path(tmp))
            tracker.refresh(["ABC"])
            path = Path(tmp) / IPO_DB_FILENAME
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertIsInstance(data, dict)
            self.assertIn("ABC", data)
            self.assertIsInstance(data["ABC"], str)


if __name__ == "__main__":
    unittest.main()
