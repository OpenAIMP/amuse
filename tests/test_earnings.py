"""Tests for issue #33: earnings-in-window auto-reject.

The screener loads src/earnings_dates.json by default. A candidate whose
earnings date falls between today and expiration is rejected with
'earnings in short window'. Unknown dates keep the flag but don't reject.
"""
import json
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
os.environ.setdefault("PUBLIC_ACCOUNT_ID", "test-account")

import unittest
from spread_screener import RUN_DATE, spread_events


class TestEarningsReject(unittest.TestCase):
    def setUp(self):
        # Issue #101: dates relative to RUN_DATE so the test is stable
        # regardless of when it runs (hardcoded 2026-10-13 rotted).
        self.today = RUN_DATE.isoformat()
        self.tomorrow = (RUN_DATE + timedelta(days=1)).isoformat()
        self.next_month = (RUN_DATE + timedelta(days=30)).isoformat()
        self.yesterday = (RUN_DATE - timedelta(days=1)).isoformat()
        self.events = {"JPM": {"earnings": self.today},
                       "BAC": {"earnings": self.tomorrow}}

    def test_earnings_in_window_rejects(self):
        flags, reasons = spread_events("JPM", self.next_month, self.events)
        self.assertIn(f"earnings {self.today} in window", flags)
        self.assertIn("earnings in short window", reasons)

    def test_earnings_after_expiry_passes(self):
        flags, reasons = spread_events("JPM", self.yesterday, self.events)
        self.assertEqual(reasons, [])

    def test_unknown_date_flags_but_passes(self):
        flags, reasons = spread_events("NVDA", self.next_month, self.events)
        self.assertIn("earnings date unknown", flags)
        self.assertEqual(reasons, [])

    def test_curated_file_loads(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "src", "earnings_dates.json")
        data = json.load(open(path))
        self.assertIn("JPM", data)
        self.assertEqual(data["JPM"]["earnings"], "2026-10-13")


if __name__ == "__main__":
    unittest.main()
