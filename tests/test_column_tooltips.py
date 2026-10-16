"""
Tests for src/column_tooltips.py.

Verifies tooltip dictionary completeness and the th() helper.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from column_tooltips import TOOLTIPS, th, th_row


class TestTooltips(unittest.TestCase):
    def test_key_columns_have_tooltips(self):
        # Critical columns the user asked about
        for col in ["P/D 30d", "Breach", "Long / Short", "Capital",
                    "Win%", "EV$", "RoR", "Lucrative", "Score", "Verdict"]:
            self.assertIn(col, TOOLTIPS, f"Missing tooltip for {col}")

    def test_tooltips_are_ascii(self):
        for name, tip in TOOLTIPS.items():
            non_ascii = [c for c in tip if ord(c) >= 128]
            self.assertEqual(
                non_ascii, [],
                f"Non-ASCII in tooltip for {name}: {non_ascii}")

    def test_tooltips_non_empty(self):
        for name, tip in TOOLTIPS.items():
            self.assertTrue(tip.strip(), f"Empty tooltip for {name}")

    def test_th_generates_title(self):
        result = th("Win%")
        self.assertIn("title=", result)
        self.assertIn("Win%", result)

    def test_th_unknown_column_no_title(self):
        result = th("NonexistentColumn123")
        self.assertNotIn("title=", result)
        self.assertIn("NonexistentColumn123", result)

    def test_th_row_generates_all(self):
        result = th_row(["Sym", "Price", "Score"])
        self.assertEqual(result.count("<th"), 3)
        self.assertIn("title=", result)


if __name__ == "__main__":
    unittest.main()
