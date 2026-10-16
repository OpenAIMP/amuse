"""
Tests for src/update_earnings.py (#33).

Tests merge logic with synthetic data (no network calls).
Network-dependent fetch functions are not tested here.
"""

import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import update_earnings as ue


class TestMergeEarnings(unittest.TestCase):
    def test_adds_new_symbols(self):
        existing = {"_note": "test"}
        fetched = {"AAPL": "2026-10-28", "MSFT": "2026-10-29"}
        merged, changes = ue.merge_earnings(existing, fetched)
        self.assertIn("AAPL", merged)
        self.assertIn("MSFT", merged)
        self.assertEqual(set(changes["added"]), {"AAPL", "MSFT"})

    def test_updates_changed_dates(self):
        existing = {"AAPL": {"earnings": "2026-10-20"}}
        fetched = {"AAPL": "2026-10-28"}
        merged, changes = ue.merge_earnings(existing, fetched)
        self.assertEqual(merged["AAPL"]["earnings"], "2026-10-28")
        self.assertIn("AAPL", changes["updated"])

    def test_no_change_when_same(self):
        existing = {"AAPL": {"earnings": "2026-10-28"}}
        fetched = {"AAPL": "2026-10-28"}
        merged, changes = ue.merge_earnings(existing, fetched)
        self.assertEqual(changes["added"], [])
        self.assertEqual(changes["updated"], [])

    def test_prunes_old_earnings(self):
        old_date = (dt.date.today() - dt.timedelta(days=10)).isoformat()
        existing = {
            "OLD": {"earnings": old_date},
            "_note": "keep me",
        }
        merged, changes = ue.merge_earnings(existing, {})
        self.assertNotIn("OLD", merged)
        self.assertIn("OLD", changes["pruned"])
        self.assertIn("_note", merged)  # note preserved

    def test_keeps_recent_earnings(self):
        recent = (dt.date.today() - dt.timedelta(days=3)).isoformat()
        existing = {"RECENT": {"earnings": recent}}
        merged, changes = ue.merge_earnings(existing, {})
        self.assertIn("RECENT", merged)
        self.assertEqual(changes["pruned"], [])

    def test_preserves_note(self):
        existing = {"_note": "original note"}
        merged, _ = ue.merge_earnings(existing, {"AAPL": "2026-10-28"})
        self.assertEqual(merged["_note"], "original note")

    def test_skips_note_in_fetched(self):
        existing = {}
        fetched = {"_note": "malicious", "AAPL": "2026-10-28"}
        merged, _ = ue.merge_earnings(existing, fetched)
        # _note from fetched should not overwrite (it's skipped)
        self.assertNotEqual(merged.get("_note"), "malicious")


class TestLoadUniverseSymbols(unittest.TestCase):
    def test_loads_symbols(self):
        syms = ue.load_universe_symbols()
        # Should load from actual universe files
        self.assertGreater(len(syms), 0)
        # All uppercase, no blanks
        for s in syms:
            self.assertEqual(s, s.upper())
            self.assertTrue(s.strip())


if __name__ == "__main__":
    unittest.main()
