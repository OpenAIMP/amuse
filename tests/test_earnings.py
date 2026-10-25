"""Tests for issue #33: earnings-in-window auto-reject.

The screener loads src/earnings_dates.json by default. A candidate whose
earnings date falls between today and expiration is rejected with
'earnings in short window'. Unknown dates keep the flag but don't reject.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
os.environ.setdefault("PUBLIC_ACCOUNT_ID", "test-account")

import unittest
from spread_screener import spread_events


class TestEarningsReject(unittest.TestCase):
    def setUp(self):
        from datetime import date, timedelta
        today = date.today()
        # Earnings 2 days from now (in window for a 36-DTE expiration)
        # and 40 days from now (outside window)
        self.events = {"JPM": {"earnings": (today + timedelta(days=2)).isoformat()},
                       "BAC": {"earnings": (today + timedelta(days=40)).isoformat()}}
        self.exp_in_window = (today + timedelta(days=36)).isoformat()
        self.exp_before = (today - timedelta(days=1)).isoformat()

    def test_earnings_in_window_rejects(self):
        flags, reasons = spread_events("JPM", self.exp_in_window, self.events)
        self.assertTrue(any("earnings" in f for f in flags))
        self.assertIn("earnings in short window", reasons)

    def test_earnings_after_expiry_passes(self):
        flags, reasons = spread_events("BAC", self.exp_in_window, self.events)
        # BAC earnings 40 days out, expiration 36 days out — no conflict
        self.assertEqual(reasons, [])

    def test_unknown_date_flags_but_passes(self):
        flags, reasons = spread_events("NVDA", "2026-11-20", self.events)
        self.assertIn("earnings date unknown", flags)
        self.assertEqual(reasons, [])

    def test_curated_file_loads(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "src", "earnings_dates.json")
        data = json.load(open(path))
        self.assertIn("AAPL", data)
        # Just verify it's a valid date string, not a specific hardcoded date (#101)
        import re
        self.assertRegex(data["AAPL"]["earnings"], r"^\d{4}-\d{2}-\d{2}$")


if __name__ == "__main__":
    unittest.main()
