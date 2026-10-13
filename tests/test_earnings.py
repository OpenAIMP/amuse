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
        self.events = {"JPM": {"earnings": "2026-10-13"},
                       "BAC": {"earnings": "2026-10-14"}}

    def test_earnings_in_window_rejects(self):
        flags, reasons = spread_events("JPM", "2026-11-20", self.events)
        self.assertIn("earnings 2026-10-13 in window", flags)
        self.assertIn("earnings in short window", reasons)

    def test_earnings_after_expiry_passes(self):
        flags, reasons = spread_events("JPM", "2026-10-12", self.events)
        self.assertEqual(reasons, [])

    def test_unknown_date_flags_but_passes(self):
        flags, reasons = spread_events("NVDA", "2026-11-20", self.events)
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
